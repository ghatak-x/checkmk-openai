# Building the OpenAI Checkmk MKP

This repository contains source code in `cmk_addons/plugins/` and dashboards in
`local/lib/`. The package **must** include both directory trees.

The root-level `manifest.json` is the source of truth for package name,
version, title, author, required Checkmk version, and download URL.

## Build

From the repository root, with Python 3.10 or newer:

```bash
python3 build_mkp.py --bundle
```

The build uses only Python's standard library; a Checkmk site is **not**
required to create the package.

For a manifest with `"name": "openai"` and `"version": "0.0.1"`, it creates:

```text
dist/
├── openai-0.0.1.mkp
├── checkmk-openai-v0.0.1.zip
└── SHA256SUMS
```

The MKP is a gzip tar archive with `info`, `info.json`,
`cmk_addons_plugins.tar` and, when `local/lib/` contains files, `lib.tar`.

The release ZIP contains the source repository, `build_mkp.py`, and the
installable `.mkp` under `checkmk-openai-v0.0.1/dist/`.

The dashboard files under `local/lib/python3/cmk/gui/plugins/dashboard/`
are packaged in `lib.tar`. Python bytecode and `__pycache__` are excluded.
Executable permissions on special-agent `libexec/agent_*` launchers are retained.

## Verify

```bash
python3 build_mkp.py --verify dist/openai-0.0.1.mkp
(cd dist && sha256sum -c SHA256SUMS)
tar -tzf dist/openai-0.0.1.mkp
unzip -l dist/checkmk-openai-v0.0.1.zip | tail -20
```

To verify integration on a Checkmk 2.5 test site, copy the MKP to the
server and, as the site user, run:

```bash
mkp add /path/to/openai-0.0.1.mkp
mkp enable openai
```

Activate changes and discover services after configuring the special-agent
rules. A successful local archive test is not a substitute for an actual
installation test in Checkmk.

## GitHub release

Keep generated build outputs outside Git history. Add `dist/` to `.gitignore`
(alongside the existing `*.mkp` rule), then:

```bash
python3 build_mkp.py --bundle
git add build_mkp.py BUILDING-MKP.md .gitignore
git commit -m "Add reproducible MKP builder"
git push -u origin main
git tag -a v0.0.1 -m "Initial release 0.0.1"
git push origin v0.0.1
gh release create v0.0.1 dist/openai-0.0.1.mkp dist/SHA256SUMS \
  --verify-tag --title "OpenAI Monitoring v0.0.1" --generate-notes
```

If the remote repository has no branch yet, pushing `main` is a regular
non-forced push. If your tag already exists, inspect it first rather than
unconditionally re-creating it.
