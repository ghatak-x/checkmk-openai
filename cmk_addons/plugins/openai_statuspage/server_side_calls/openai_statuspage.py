#!/usr/bin/env python3
# Copyright (C) 2026 Sudhir Chauhan
# License: GNU General Public License v2
# SPDX-License-Identifier: GPL-2.0-only

from __future__ import annotations

from typing import Iterator, Literal

from pydantic import BaseModel, Field

from cmk.server_side_calls.v1 import (
    EnvProxy,
    HostConfig,
    NoProxy,
    SpecialAgentCommand,
    SpecialAgentConfig,
    URLProxy,
)


class Params(BaseModel):
    url: str = "https://status.openai.com"
    timeout: float = 10.0
    proxy: URLProxy | NoProxy | EnvProxy | None = None
    component_services: Literal["aggregate_only", "selected", "all"] = "aggregate_only"
    selected_components: list[str] = Field(default_factory=list)
    individual_endpoint_services: bool = False
    verify_tls: bool = True


def _commands(params: Params, _host_config: HostConfig) -> Iterator[SpecialAgentCommand]:
    args: list[str] = [
        "--url",
        params.url,
        "--timeout",
        str(params.timeout),
        "--component-services",
        params.component_services,
    ]
    for component in params.selected_components:
        args += ["--selected-component", component]
    if params.individual_endpoint_services:
        args.append("--individual-endpoint-services")
    if not params.verify_tls:
        args.append("--no-verify-tls")

    if params.proxy:
        match params.proxy:
            case URLProxy(url=url):
                args += ["--proxy", url]
            case EnvProxy():
                args += ["--proxy", "FROM_ENVIRONMENT"]
            case NoProxy():
                args += ["--proxy", "NO_PROXY"]

    yield SpecialAgentCommand(command_arguments=args)


special_agent_openai_statuspage = SpecialAgentConfig(
    name="openai_statuspage",
    parameter_parser=Params.model_validate,
    commands_function=_commands,
)
