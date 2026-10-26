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
    Float,
    Integer,
    LevelDirection,
    LevelsType,
    SimpleLevels,
    SingleChoice,
    SingleChoiceElement,
)
from cmk.rulesets.v1.rule_specs import (
    CheckParameters,
    DiscoveryParameters,
    HostAndItemCondition,
    HostCondition,
    Topic,
)

_STATE_ELEMENTS = [
    SingleChoiceElement(name="ok", title=Title("OK")),
    SingleChoiceElement(name="warn", title=Title("WARN")),
    SingleChoiceElement(name="crit", title=Title("CRIT")),
    SingleChoiceElement(name="unknown", title=Title("UNKNOWN")),
]


def _state(title: str, default: str) -> SingleChoice:
    return SingleChoice(title=Title(title), elements=_STATE_ELEMENTS, prefill=DefaultValue(default))


def _float_levels(title: str, unit: str = "") -> SimpleLevels:
    return SimpleLevels(
        title=Title(title),
        form_spec_template=Float(unit_symbol=unit),
        level_direction=LevelDirection.UPPER,
        prefill_levels_type=DefaultValue(LevelsType.NONE),
        prefill_fixed_levels=DefaultValue((0.0, 0.0)),
    )


def _float_lower_levels(title: str, unit: str = "") -> SimpleLevels:
    return SimpleLevels(
        title=Title(title),
        form_spec_template=Float(unit_symbol=unit),
        level_direction=LevelDirection.LOWER,
        prefill_levels_type=DefaultValue(LevelsType.NONE),
        prefill_fixed_levels=DefaultValue((0.0, 0.0)),
    )


def _int_levels(title: str, unit: str = "") -> SimpleLevels:
    return SimpleLevels(
        title=Title(title),
        form_spec_template=Integer(unit_symbol=unit),
        level_direction=LevelDirection.UPPER,
        prefill_levels_type=DefaultValue(LevelsType.NONE),
        prefill_fixed_levels=DefaultValue((0, 0)),
    )


def _api_form() -> Dictionary:
    return Dictionary(
        title=Title("API health"),
        elements={
            "auth_failure": DictElement(required=True, parameter_form=_state("Authentication/access failure", "crit")),
            "required_failure": DictElement(required=True, parameter_form=_state("Required API endpoint failure", "crit")),
            "optional_failure": DictElement(required=True, parameter_form=_state("Optional API endpoint failure", "warn")),
        },
    )


def _overview_form(*, project: bool) -> Dictionary:
    if project:
        return Dictionary(
            title=Title("Project status"),
            elements={
                "archived": DictElement(required=True, parameter_form=_state("Archived project", "ok")),
                "inactive": DictElement(required=True, parameter_form=_state("Inactive project", "warn")),
                "unknown": DictElement(required=True, parameter_form=_state("Unknown project state", "unknown")),
            },
        )
    return Dictionary(
        title=Title("Organization inventory"),
        help_text=Help("Project and user counts are dynamic provider inventory; no fixed expected total is used."),
        elements={
            "zero_active_projects": DictElement(required=True, parameter_form=_state("No active projects", "ok")),
            "zero_users": DictElement(required=True, parameter_form=_state("No organization users", "ok")),
        },
    )


def _access_form() -> Dictionary:
    return Dictionary(
        title=Title("Access policy"),
        elements={
            "no_owner": DictElement(required=True, parameter_form=_state("No owner", "crit")),
            "no_service_accounts": DictElement(required=True, parameter_form=_state("No service accounts", "ok")),
            "no_api_keys": DictElement(required=True, parameter_form=_state("No API keys", "ok")),
        },
    )


def _cost_form() -> Dictionary:
    return Dictionary(
        title=Title("Cost thresholds"),
        help_text=Help("No spend thresholds are enabled by default."),
        elements={
            "today": DictElement(required=True, parameter_form=_float_levels("Cost today", "$")),
            "month_to_date": DictElement(required=True, parameter_form=_float_levels("Month-to-date cost", "$")),
        },
    )


def _usage_form() -> Dictionary:
    return Dictionary(
        title=Title("Usage thresholds"),
        help_text=Help("Usage is dynamic and thresholds are disabled by default."),
        elements={
            "requests": DictElement(required=True, parameter_form=_int_levels("Completions/Responses requests", "requests")),
            "input_tokens": DictElement(required=True, parameter_form=_int_levels("Input tokens", "tokens")),
            "output_tokens": DictElement(required=True, parameter_form=_int_levels("Output tokens", "tokens")),
            "zero_activity": DictElement(required=True, parameter_form=_state("No activity in aggregation window", "ok")),
        },
    )


def _cost_allocation_form() -> Dictionary:
    return Dictionary(
        title=Title("Cost allocation"),
        help_text=Help(
            "Optional concentration and unattributed-cost thresholds. Project attribution is dynamic and no project count is assumed."
        ),
        elements={
            "largest_project_share": DictElement(required=True, parameter_form=_float_levels("Largest project share", "%")),
            "unattributed_cost": DictElement(required=True, parameter_form=_float_levels("Unattributed/other MTD cost", "$")),
            "unattributed_share": DictElement(required=True, parameter_form=_float_levels("Unattributed/other share", "%")),
        },
    )


def _usage_allocation_form() -> Dictionary:
    return Dictionary(
        title=Title("Usage allocation"),
        help_text=Help("Optional threshold for concentration of request/call activity in one project."),
        elements={
            "largest_project_share": DictElement(required=True, parameter_form=_float_levels("Largest project request share", "%")),
        },
    )


def _prompt_cache_form() -> Dictionary:
    return Dictionary(
        title=Title("Prompt cache"),
        help_text=Help(
            "Cache-read ratio is cached input tokens divided by total input tokens for Completions/Responses. "
            "Thresholds are disabled by default."
        ),
        elements={
            "minimum_hit_rate": DictElement(
                required=True,
                parameter_form=_float_lower_levels("Minimum cache-read ratio", "%"),
            ),
            "uncached_input_tokens": DictElement(
                required=True,
                parameter_form=_int_levels("Uncached input tokens", "tokens"),
            ),
        },
    )


def _usage_attribution_form() -> Dictionary:
    return Dictionary(
        title=Title("Caller/API-key usage attribution"),
        help_text=Help(
            "Optional concentration thresholds for request/call activity attributed to a resolved human user or API key. "
            "API-key ownership is the primary caller signal; provider user_id values affect the user threshold only when they resolve to known users. "
            "No thresholds are enabled by default."
        ),
        elements={
            "largest_user_share": DictElement(
                required=True,
                parameter_form=_float_levels("Largest resolved-user request share", "%"),
            ),
            "largest_api_key_share": DictElement(
                required=True,
                parameter_form=_float_levels("Largest API-key request share", "%"),
            ),
        },
    )


def _rate_limit_form() -> Dictionary:
    return Dictionary(
        title=Title("Rate-limit policy"),
        elements={
            "used_model_without_limit": DictElement(required=True, parameter_form=_state("Used model without matching rate-limit record", "warn")),
            "no_records": DictElement(
                required=True,
                parameter_form=_state(
                    "No rate-limit records returned when no model usage is observed",
                    "ok",
                ),
            ),
        },
    )


def _migrate_organization_policy(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    params = dict(value)
    params.setdefault(
        "prompt_cache",
        {
            "minimum_hit_rate": ("no_levels", None),
            "uncached_input_tokens": ("no_levels", None),
        },
    )
    params.setdefault(
        "usage_attribution",
        {
            "largest_user_share": ("no_levels", None),
            "largest_api_key_share": ("no_levels", None),
        },
    )
    return params


def _organization_policy_form() -> Dictionary:
    return Dictionary(
        title=Title("OpenAI Platform organization policy"),
        migrate=_migrate_organization_policy,
        help_text=Help(
            "One policy rule configures the organization-level OpenAI Platform services. Dynamic inventory counts are descriptive; only semantic states or explicitly configured thresholds alert."
        ),
        elements={
            "api": DictElement(required=True, parameter_form=_api_form()),
            "overview": DictElement(required=True, parameter_form=_overview_form(project=False)),
            "access": DictElement(required=True, parameter_form=_access_form()),
            "costs": DictElement(required=True, parameter_form=_cost_form()),
            "usage": DictElement(required=True, parameter_form=_usage_form()),
            "cost_allocation": DictElement(required=True, parameter_form=_cost_allocation_form()),
            "usage_allocation": DictElement(required=True, parameter_form=_usage_allocation_form()),
            "prompt_cache": DictElement(required=True, parameter_form=_prompt_cache_form()),
            "usage_attribution": DictElement(required=True, parameter_form=_usage_attribution_form()),
        },
    )


rule_spec_openai_platform_organization_policy = CheckParameters(
    name="openai_platform_organization_policy",
    title=Title("OpenAI Platform organization policy"),
    topic=Topic.CLOUD,
    parameter_form=_organization_policy_form,
    condition=HostCondition(),
    create_enforced_service=False,
)


def _project_policy_form() -> Dictionary:
    return Dictionary(
        title=Title("OpenAI Platform project policy"),
        help_text=Help(
            "One policy rule configures all project-level OpenAI services. Project inventory is provider-controlled and can change over time."
        ),
        elements={
            "overview": DictElement(required=True, parameter_form=_overview_form(project=True)),
            "access": DictElement(required=True, parameter_form=_access_form()),
            "costs": DictElement(required=True, parameter_form=_cost_form()),
            "usage": DictElement(required=True, parameter_form=_usage_form()),
            "rate_limits": DictElement(required=True, parameter_form=_rate_limit_form()),
        },
    )


rule_spec_openai_platform_project_policy = CheckParameters(
    name="openai_platform_project_policy",
    title=Title("OpenAI Platform project policy"),
    topic=Topic.CLOUD,
    parameter_form=_project_policy_form,
    condition=HostAndItemCondition(item_title=Title("OpenAI project")),
    create_enforced_service=False,
)


def _project_discovery_form() -> Dictionary:
    return Dictionary(
        title=Title("OpenAI Platform project service discovery"),
        help_text=Help(
            "Choose which project-level service families Checkmk should discover. The special agent still collects project dimensions needed for organization allocation services."
        ),
        elements={
            "overview": DictElement(required=True, parameter_form=BooleanChoice(title=Title("Project overview services"), prefill=DefaultValue(True))),
            "access": DictElement(required=True, parameter_form=BooleanChoice(title=Title("Project access services"), prefill=DefaultValue(True))),
            "costs": DictElement(required=True, parameter_form=BooleanChoice(title=Title("Project cost services"), prefill=DefaultValue(True))),
            "usage": DictElement(required=True, parameter_form=BooleanChoice(title=Title("Project usage services"), prefill=DefaultValue(True))),
            "rate_limits": DictElement(required=True, parameter_form=BooleanChoice(title=Title("Project rate-limit services"), prefill=DefaultValue(True))),
            "model_usage": DictElement(required=True, parameter_form=BooleanChoice(title=Title("Activity-based model usage services"), prefill=DefaultValue(True))),
        },
    )


rule_spec_openai_platform_project_services = DiscoveryParameters(
    name="openai_platform_project_services",
    title=Title("OpenAI Platform project service discovery"),
    topic=Topic.CLOUD,
    parameter_form=_project_discovery_form,
)
