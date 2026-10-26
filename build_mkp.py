#!/usr/bin/env python3
"""Build and verify a Checkmk 2.5 MKP from this source repository.

Usage:
    python3 build_mkp.py
    python3 build_mkp.py --bundle
    python3 build_mkp.py --verify dist/openai-0.0.1.mkp

No Checkmk installation or third-party Python dependencies required.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import pprint
import subprocess
import sys
import tarfile
import zipfile


# MKP section -> repository directory. Paths INSIDE the nested tar are
# relative to these directories, not relative to the repository root.
SOURCES = {
    "cmk_addons_plugins": Path("cmk_addons/plugins"),
    "lib": Path("local/lib"),
}
EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".swp", ".swo"}


@dataclass(frozen=True)
class Payload:
    section: str
    entries: tuple[tuple[str, Path], ...]


def allowed_file(path: Path) -> bool:
    """Check the relative path name; callers check file type/symlinks."""
    return (
        not any(part in EXCLUDED_DIRS for part in path.parts)
        and path.suffix not in EXCLUDED_SUFFIXES
        and (not path.name.startswith(".") or path.name == ".gitignore")
        and not path.name.endswith("~")
    )


def collected_payloads(repo: Path) -> list[Payload]:
    payloads = []
    for section, relative_root in SOURCES.items():
        base = repo / relative_root
        if not base.is_dir():
            continue
        entries = tuple(
            (file.relative_to(base).as_posix(), file)
            for file in sorted(base.rglob("*"))
            if file.is_file()
            and not file.is_symlink()
            and allowed_file(file.relative_to(repo))
            and file.resolve().is_relative_to(base.resolve())
        )
        if entries:
            payloads.append(Payload(section, entries))
    if not payloads or not any(p.section == "cmk_addons_plugins" for p in payloads):
        raise ValueError("No Checkmk add-on files found under cmk_addons/plugins/")
    return payloads


def read_manifest(repo: Path, filename: str) -> dict:
    manifest = repo / filename
    if not manifest.is_file():
        raise FileNotFoundError(f"Missing package manifest: {manifest}")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest.json must contain a JSON object")
    # Supports the metadata shape used by the other Checkmk extensions.
    required = ("name", "title", "version", "author", "description")
    missing = [key for key in required if not isinstance(data.get(key), str) or not data[key].strip()]
    if missing:
        raise ValueError(f"Missing/empty manifest fields: {', '.join(missing)}")
    for key in ("name", "version"):
        if not all(c.isalnum() or c in "._-" for c in data[key]):
            raise ValueError(f"Unsafe {key} in manifest.json: {data[key]!r}")
    return data


def package_info(manifest: dict, payloads: list[Payload]) -> dict:
    # Checkmk MKP info is not the same format as the root project manifest.
    # Only the fields understood by the Checkmk package manager go into info.
    return {
        "author": manifest["author"],
        "description": manifest["description"],
        "download_url": manifest.get("download_url", ""),
        "files": {p.section: [name for name, _ in p.entries] for p in payloads},
        "name": manifest["name"],
        "title": manifest["title"],
        "version": manifest["version"],
        "version.min_required": manifest.get("version.min_required", "2.5.0"),
        "version.packaged": manifest.get("version.packaged", "2.5.0"),
        "version.usable_until": manifest.get("version.usable_until"),
    }


def tar_info(name: str, size: int, mode: int = 0o644) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = mode
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def tar_bytes(entries: tuple[tuple[str, Path], ...]) -> bytes:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, source in entries:
            if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                raise ValueError(f"Unsafe MKP payload path: {name}")
            raw = source.read_bytes()
            # Ensure special-agent launchers remain executable after installation.
            executable = name.split("/")[-2:] if "/" in name else []
            agent_launcher = len(executable) == 2 and executable[0] == "libexec" and executable[1].startswith("agent_")
            mode = (source.stat().st_mode & 0o777) | (0o755 if agent_launcher else 0)
            tar.addfile(tar_info(name, len(raw), mode), io.BytesIO(raw))
    return data.getvalue()


def build_mkp(repo: Path, manifest: dict, payloads: list[Payload], output: Path) -> dict:
    info = package_info(manifest, payloads)
    files: list[tuple[str, bytes]] = [
        ("info", (pprint.pformat(info, sort_dicts=False, width=120) + "\n").encode()),
        ("info.json", (json.dumps(info, indent=2) + "\n").encode()),
    ]
    files.extend((f"{p.section}.tar", tar_bytes(p.entries)) for p in payloads)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        for name, raw in files:
            tar.addfile(tar_info(name, len(raw)), io.BytesIO(raw))
    verify_mkp(output, expected=info)
    return info


def verify_mkp(path: Path, expected: dict | None = None) -> dict:
    with tarfile.open(path, mode="r:gz") as outer:
        members = {m.name: m for m in outer.getmembers()}
        if not {"info", "info.json"}.issubset(members):
            raise ValueError("MKP is missing info and/or info.json")
        raw_info = outer.extractfile(members["info"]).read().decode()
        info = ast.literal_eval(raw_info)
        json_info = json.load(outer.extractfile(members["info.json"]))
        if info != json_info:
            raise ValueError("MKP info and info.json disagree")
        if expected is not None and info != expected:
            raise ValueError("Built MKP metadata does not match the source manifest")
        for section, paths in info["files"].items():
            inner_name = f"{section}.tar"
            if inner_name not in members:
                raise ValueError(f"Missing MKP payload: {inner_name}")
            inner_data = outer.extractfile(members[inner_name]).read()
            with tarfile.open(fileobj=io.BytesIO(inner_data), mode="r:") as inner:
                actual = inner.getnames()
                if actual != paths:
                    raise ValueError(f"{inner_name} manifest mismatch")
                for item in inner.getmembers():
                    p = PurePosixPath(item.name)
                    if p.is_absolute() or ".." in p.parts or not item.isfile():
                        raise ValueError(f"Unsafe MKP member: {item.name}")
                    if item.name.split("/")[-2:-1] == ["libexec"] and item.name.rsplit("/", 1)[-1].startswith("agent_"):
                        if not item.mode & 0o111:
                            raise ValueError(f"Agent launcher not executable: {item.name}")
    return info


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_files(repo: Path) -> list[Path]:
    """Use tracked + untracked nonignored files; never include .git history."""
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=repo, stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Useful if somebody downloaded GitHub's auto-generated source ZIP.
        candidates = [p.relative_to(repo) for p in repo.rglob("*")]
    else:
        candidates = [Path(s.decode("utf-8")) for s in output.split(b"\0") if s]
    result = []
    for rel in sorted(set(candidates)):
        path = repo / rel
        if not allowed_file(rel) or not path.is_file() or path.is_symlink():
            continue
        if rel.parts[0].startswith(".") and rel.parts[0] not in {".github"} and rel.name != ".gitignore":
            continue
        if rel.parts[0] == "dist" or rel.suffix == ".mkp":
            continue
        if not path.resolve().is_relative_to(repo.resolve()):
            continue
        result.append(rel)
    return result


def bundle_release(repo: Path, mkp: Path, output_dir: Path, manifest: dict) -> Path:
    """Make an optional complete release ZIP with source + MKP inside it."""
    version = manifest["version"]
    folder = f"checkmk-openai-v{version}"
    zip_path = output_dir / f"{folder}.zip"
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in repo_files(repo):
            zf.write(repo / rel, arcname=f"{folder}/{rel.as_posix()}")
        zf.write(mkp, arcname=f"{folder}/dist/{mkp.name}")
        zf.writestr(f"{folder}/dist/SHA256SUMS", f"{sha256(mkp)}  {mkp.name}\n")
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad:
            raise ValueError(f"Release ZIP has corrupt entry: {bad}")
        if f"{folder}/build_mkp.py" not in zf.namelist():
            raise ValueError("Release ZIP missing build_mkp.py; put it at the repository root")
        if f"{folder}/dist/{mkp.name}" not in zf.namelist():
            raise ValueError("Release ZIP missing built MKP")
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="dist", help="Output directory relative to repo root")
    parser.add_argument("--manifest", default="manifest.json", help="Project manifest relative to repo root")
    parser.add_argument("--bundle", action="store_true", help="Also create a complete source + MKP release ZIP")
    parser.add_argument("--verify", metavar="MKP", type=Path, help="Verify an existing MKP instead of building")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent
    try:
        if args.verify:
            info = verify_mkp(args.verify.resolve())
            print(f"OK: {args.verify} ({info['name']} v{info['version']})")
            return 0
        manifest = read_manifest(repo, args.manifest)
        payloads = collected_payloads(repo)
        output_dir = (repo / args.output_dir).resolve()
        if not output_dir.is_relative_to(repo):
            raise ValueError("Output directory must stay inside the repository")
        mkp = output_dir / f"{manifest['name']}-{manifest['version']}.mkp"
        info = build_mkp(repo, manifest, payloads, mkp)
        (output_dir / "SHA256SUMS").write_text(f"{sha256(mkp)}  {mkp.name}\n", encoding="utf-8")
        print(f"OK: built and verified {mkp}")
        for section, paths in info["files"].items():
            print(f"  {section}: {len(paths)} file(s)")
        if args.bundle:
            bundle = bundle_release(repo, mkp, output_dir, manifest)
            with (output_dir / "SHA256SUMS").open("a", encoding="utf-8") as sums:
                sums.write(f"{sha256(bundle)}  {bundle.name}\n")
            print(f"OK: built source + MKP bundle {bundle}")
        return 0
    except (OSError, ValueError, tarfile.TarError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
