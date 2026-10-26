#!/usr/bin/env python3
# Copyright (C) 2026 Sudhir Chauhan
# License: GNU General Public License v2
# SPDX-License-Identifier: GPL-2.0-only

from __future__ import annotations

from cmk.rulesets.v1 import Help, Title
from cmk.rulesets.v1.form_specs import (
    BooleanChoice,
    DefaultValue,
    DictElement,
    Dictionary,
    FieldSize,
    List,
    Proxy,
    SingleChoice,
    SingleChoiceElement,
    String,
    TimeMagnitude,
    TimeSpan,
    migrate_to_proxy,
)
from cmk.rulesets.v1.rule_specs import (
    CheckParameters,
    HostAndItemCondition,
    HostCondition,
    SpecialAgent,
    Topic,
)


def _migrate_status_params(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    params = dict(value)
    if "url" not in params:
        legacy_url = params.pop("base_url", None)
        if isinstance(legacy_url, str) and legacy_url:
            params["url"] = legacy_url
    if "verify_tls" not in params:
        for key in ("verify_ssl", "ssl_verify"):
            candidate = params.pop(key, None)
            if isinstance(candidate, bool):
                params["verify_tls"] = candidate
                break
    params.setdefault("url", "https://status.openai.com")
    params.setdefault("timeout", 10.0)
    params.setdefault("verify_tls", True)
    params.setdefault("component_services", "aggregate_only")
    params.setdefault("individual_endpoint_services", False)
    return params


def _form() -> Dictionary:
    return Dictionary(
        title=Title("OpenAI public status"),
        migrate=_migrate_status_params,
        help_text=Help(
            "Monitor the public OpenAI status service. Aggregate API and component services are "
            "created by default. Individual endpoint and component services are optional to keep "
            "service discovery concise."
        ),
        elements={
            "url": DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Status URL"),
                    field_size=FieldSize.LARGE,
                    prefill=DefaultValue("https://status.openai.com"),
                ),
            ),
            "component_services": DictElement(
                required=True,
                parameter_form=SingleChoice(
                    title=Title("Individual component services"),
                    help_text=Help(
                        "The aggregate 'OpenAI Status Components' service is always created. "
                        "Choose whether additional per-component services should be discovered."
                    ),
                    elements=[
                        SingleChoiceElement(name="aggregate_only", title=Title("Aggregate only (recommended)")),
                        SingleChoiceElement(name="selected", title=Title("Aggregate + selected components")),
                        SingleChoiceElement(name="all", title=Title("Aggregate + all components")),
                    ],
                    prefill=DefaultValue("aggregate_only"),
                ),
            ),
            "selected_components": DictElement(
                parameter_form=List[str](
                    title=Title("Selected component names"),
                    help_text=Help(
                        "Used only when 'Aggregate + selected components' is selected. Names are "
                        "matched exactly. Duplicate display names select all matching components; "
                        "duplicate services are disambiguated with a stable ID suffix."
                    ),
                    element_template=String(field_size=FieldSize.LARGE),
                )
            ),
            "individual_endpoint_services": DictElement(
                required=True,
                parameter_form=BooleanChoice(
                    title=Title("Individual Status API endpoint services"),
                    help_text=Help(
                        "The aggregate 'OpenAI Status API' service is always created. Enable this "
                        "only when you also want one service per API endpoint."
                    ),
                    prefill=DefaultValue(False),
                ),
            ),
            "proxy": DictElement(
                parameter_form=Proxy(
                    title=Title("HTTP proxy"),
                    help_text=Help("Use environment proxy settings, no proxy, or a configured URL."),
                    migrate=migrate_to_proxy,
                )
            ),
            "verify_tls": DictElement(
                required=True,
                parameter_form=BooleanChoice(
                    title=Title("Verify TLS certificates"),
                    prefill=DefaultValue(True),
                ),
            ),
            "timeout": DictElement(
                required=True,
                parameter_form=TimeSpan(
                    title=Title("Request timeout"),
                    displayed_magnitudes=[TimeMagnitude.SECOND],
                    prefill=DefaultValue(10.0),
                ),
            ),
        },
    )


rule_spec_openai_statuspage = SpecialAgent(
    name="openai_statuspage",
    title=Title("OpenAI public status"),
    parameter_form=_form,
    topic=Topic.CLOUD,
)


_STATE_ELEMENTS = [
    SingleChoiceElement(name="ok", title=Title("OK")),
    SingleChoiceElement(name="warn", title=Title("WARN")),
    SingleChoiceElement(name="crit", title=Title("CRIT")),
    SingleChoiceElement(name="unknown", title=Title("UNKNOWN")),
]


def _state(title: str, default: str, help_text: str | None = None) -> SingleChoice:
    return SingleChoice(
        title=Title(title),
        help_text=Help(help_text) if help_text else None,
        elements=_STATE_ELEMENTS,
        prefill=DefaultValue(default),
    )


def _overview_parameters() -> Dictionary:
    return Dictionary(
        title=Title("Provider overview"),
        elements={
            "minor": DictElement(required=True, parameter_form=_state("Minor indicator", "warn")),
            "major": DictElement(required=True, parameter_form=_state("Major indicator", "crit")),
            "critical": DictElement(required=True, parameter_form=_state("Critical indicator", "crit")),
            "unknown": DictElement(required=True, parameter_form=_state("Unknown indicator", "unknown")),
        },
    )


def _api_parameters() -> Dictionary:
    return Dictionary(
        title=Title("Status API"),
        elements={
            "required_failure": DictElement(required=True, parameter_form=_state("Required endpoint failure", "crit")),
            "optional_failure": DictElement(required=True, parameter_form=_state("Optional endpoint failure", "warn")),
            "optional_not_exposed": DictElement(
                required=True,
                parameter_form=_state(
                    "Optional endpoint not exposed (HTTP 404)",
                    "ok",
                    "OpenAI's status backend may not expose every optional Statuspage-compatible route.",
                ),
            ),
        },
    )


def _component_parameters() -> Dictionary:
    return Dictionary(
        title=Title("Component health"),
        help_text=Help("Component inventory is provider-controlled and dynamic; states are based on health, not a fixed count."),
        elements={
            "degraded_performance": DictElement(required=True, parameter_form=_state("Degraded performance", "warn")),
            "partial_outage": DictElement(required=True, parameter_form=_state("Partial outage", "crit")),
            "major_outage": DictElement(required=True, parameter_form=_state("Major outage", "crit")),
            "under_maintenance": DictElement(required=True, parameter_form=_state("Under maintenance", "ok")),
            "unknown": DictElement(required=True, parameter_form=_state("Unknown component state", "unknown")),
        },
    )


def _incident_parameters() -> Dictionary:
    return Dictionary(
        title=Title("Incidents"),
        elements={
            "none": DictElement(required=True, parameter_form=_state("Unresolved incident, impact none", "warn")),
            "minor": DictElement(required=True, parameter_form=_state("Unresolved incident, minor impact", "warn")),
            "major": DictElement(required=True, parameter_form=_state("Unresolved incident, major impact", "crit")),
            "critical": DictElement(required=True, parameter_form=_state("Unresolved incident, critical impact", "crit")),
            "unknown": DictElement(required=True, parameter_form=_state("Unresolved incident, unknown impact", "warn")),
        },
    )


def _maintenance_parameters() -> Dictionary:
    return Dictionary(
        title=Title("Maintenance"),
        elements={
            "active": DictElement(required=True, parameter_form=_state("Active maintenance", "warn")),
            "upcoming": DictElement(required=True, parameter_form=_state("Upcoming maintenance", "ok")),
        },
    )


def _integrity_parameters() -> Dictionary:
    return Dictionary(
        title=Title("Data integrity"),
        elements={
            "observation": DictElement(required=True, parameter_form=_state("Validated data-integrity conflict", "warn")),
        },
    )


def _aggregate_policy_form() -> Dictionary:
    return Dictionary(
        title=Title("OpenAI public status policy"),
        help_text=Help("One policy configures the aggregate OpenAI public-status services."),
        elements={
            "overview": DictElement(required=True, parameter_form=_overview_parameters()),
            "api": DictElement(required=True, parameter_form=_api_parameters()),
            "components": DictElement(required=True, parameter_form=_component_parameters()),
            "incidents": DictElement(required=True, parameter_form=_incident_parameters()),
            "maintenance": DictElement(required=True, parameter_form=_maintenance_parameters()),
            "integrity": DictElement(required=True, parameter_form=_integrity_parameters()),
        },
    )


rule_spec_openai_status_policy = CheckParameters(
    name="openai_status_policy",
    title=Title("OpenAI public status policy"),
    topic=Topic.CLOUD,
    parameter_form=_aggregate_policy_form,
    condition=HostCondition(),
    create_enforced_service=False,
)


def _detail_policy_form() -> Dictionary:
    return Dictionary(
        title=Title("OpenAI public status detail policy"),
        help_text=Help("Shared state policy for optional individual endpoint and component services."),
        elements={
            "api": DictElement(required=True, parameter_form=_api_parameters()),
            "components": DictElement(required=True, parameter_form=_component_parameters()),
        },
    )


rule_spec_openai_status_detail_policy = CheckParameters(
    name="openai_status_detail_policy",
    title=Title("OpenAI public status detail policy"),
    topic=Topic.CLOUD,
    parameter_form=_detail_policy_form,
    condition=HostAndItemCondition(item_title=Title("Endpoint or component")),
    create_enforced_service=False,
)
