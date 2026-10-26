#!/usr/bin/env python3
# Copyright (C) 2026 Sudhir Chauhan
# License: GNU General Public License v2
# SPDX-License-Identifier: GPL-2.0-only

from __future__ import annotations

from collections.abc import Iterator

from cmk.server_side_calls.v1 import (
    EnvProxy,
    HostConfig,
    NoProxy,
    SpecialAgentCommand,
    SpecialAgentConfig,
    URLProxy,
    noop_parser,
)


def _commands(params: dict, _host_config: HostConfig) -> Iterator[SpecialAgentCommand]:
    args: list[object] = [
        "--admin-key-id",
        params["admin_key"],
        "--base-url",
        params.get("base_url", "https://api.openai.com/v1"),
        "--timeout",
        str(params.get("timeout", 10.0)),
        "--usage-window",
        str(int(params.get("usage_window", 86400))),
        "--project-include",
        params.get("project_include", ".*"),
    ]
    if params.get("project_key"):
        args += ["--project-key-id", params["project_key"]]
    if params.get("project_exclude"):
        args += ["--project-exclude", params["project_exclude"]]
    if params.get("include_archived", False):
        args.append("--include-archived")
    if not params.get("verify_tls", True):
        args.append("--no-verify-tls")
    if not params.get("collect_usage_attribution", True):
        args.append("--no-usage-attribution")

    proxy = params.get("proxy")
    if proxy:
        match proxy:
            case URLProxy(url=url):
                args += ["--proxy", url]
            case EnvProxy():
                args += ["--proxy", "FROM_ENVIRONMENT"]
            case NoProxy():
                args += ["--proxy", "NO_PROXY"]

    yield SpecialAgentCommand(command_arguments=args)  # type: ignore[arg-type]


special_agent_openai_platform = SpecialAgentConfig(
    name="openai_platform",
    parameter_parser=noop_parser,
    commands_function=_commands,
)
