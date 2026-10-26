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
    Password,
    Proxy,
    String,
    TimeMagnitude,
    TimeSpan,
    migrate_to_password,
    migrate_to_proxy,
)
from cmk.rulesets.v1.rule_specs import SpecialAgent, Topic


def _unwrap_legacy_connection(value: object) -> dict[str, object]:
    """Return the settings dictionary from legacy connection representations."""
    if isinstance(value, dict):
        # Some older forms stored the actual settings one level deeper.
        for key in ("settings", "custom", "connection"):
            nested = value.get(key)
            if isinstance(nested, dict):
                return dict(nested)
        return dict(value)

    if isinstance(value, (tuple, list)) and len(value) >= 2:
        nested = value[1]
        if isinstance(nested, dict):
            return dict(nested)

    return {}


def _migrate_platform_params(value: object) -> dict[str, object]:
    """Migrate legacy special-agent rules to the current flat model.

    The migration is intentionally idempotent because Checkmk runs FormSpec
    migrations every time a stored value is loaded.
    """
    if not isinstance(value, dict):
        return {}

    params = dict(value)

    history_hours = params.pop("history_hours", None)
    if "usage_window" not in params:
        try:
            if history_hours is not None:
                params["usage_window"] = float(history_hours) * 3600.0
        except (TypeError, ValueError):
            pass

    connection = params.pop("connection", None)
    legacy_connection = _unwrap_legacy_connection(connection)

    if "base_url" not in params:
        for key in ("base_url", "api_url", "url"):
            candidate = legacy_connection.get(key)
            if isinstance(candidate, str) and candidate:
                params["base_url"] = candidate
                break

    if "timeout" not in params:
        candidate = legacy_connection.get("timeout")
        if isinstance(candidate, (int, float)):
            params["timeout"] = float(candidate)

    if "verify_tls" not in params:
        for key in ("verify_tls", "verify_ssl", "ssl_verify"):
            candidate = legacy_connection.get(key)
            if isinstance(candidate, bool):
                params["verify_tls"] = candidate
                break

    if "proxy" not in params and "proxy" in legacy_connection:
        params["proxy"] = legacy_connection["proxy"]

    # Required fields added after the legacy rule model. Defaults mirror the
    # collector defaults and therefore preserve the old behaviour.
    params.setdefault("base_url", "https://api.openai.com/v1")
    params.setdefault("project_include", ".*")
    params.setdefault("include_archived", False)
    params.setdefault("usage_window", 86400.0)
    params.setdefault("timeout", 10.0)
    params.setdefault("verify_tls", True)
    params.setdefault("collect_usage_attribution", True)

    return params


def _form() -> Dictionary:
    return Dictionary(
        title=Title("OpenAI Platform"),
        migrate=_migrate_platform_params,
        help_text=Help(
            "Monitor OpenAI organization/projects using an organization Admin API key. "
            "The optional project key validates project/model API access."
        ),
        elements={
            "admin_key": DictElement(
                required=True,
                parameter_form=Password(
                    title=Title("OpenAI Admin API key"),
                    migrate=migrate_to_password,
                ),
            ),
            "project_key": DictElement(
                parameter_form=Password(
                    title=Title("Project API key (optional)"),
                    help_text=Help("Optional project/service-account key used to validate /models access."),
                    migrate=migrate_to_password,
                )
            ),
            "base_url": DictElement(
                required=True,
                parameter_form=String(
                    title=Title("OpenAI API base URL"),
                    field_size=FieldSize.LARGE,
                    prefill=DefaultValue("https://api.openai.com/v1"),
                ),
            ),
            "project_include": DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Project include regex"),
                    prefill=DefaultValue(".*"),
                ),
            ),
            "project_exclude": DictElement(
                parameter_form=String(title=Title("Project exclude regex"))
            ),
            "include_archived": DictElement(
                required=True,
                parameter_form=BooleanChoice(
                    title=Title("Include archived projects"),
                    prefill=DefaultValue(False),
                ),
            ),
            "usage_window": DictElement(
                required=True,
                parameter_form=TimeSpan(
                    title=Title("Usage aggregation window"),
                    displayed_magnitudes=[TimeMagnitude.HOUR],
                    prefill=DefaultValue(86400.0),
                ),
            ),
            "collect_usage_attribution": DictElement(
                required=True,
                parameter_form=BooleanChoice(
                    title=Title("Collect caller/API-key usage attribution"),
                    help_text=Help(
                        "Adds api_key_id and user_id grouping to supported Usage API families. "
                        "API-key owner/caller identity is primary; provider user_id is secondary and unresolved IDs are diagnostic-only. "
                        "This enables the organization usage-attribution service without collecting API key secrets."
                    ),
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
            "verify_tls": DictElement(
                required=True,
                parameter_form=BooleanChoice(
                    title=Title("Verify TLS certificates"),
                    prefill=DefaultValue(True),
                ),
            ),
            "proxy": DictElement(
                parameter_form=Proxy(
                    title=Title("HTTP proxy"),
                    migrate=migrate_to_proxy,
                )
            ),
        },
    )


rule_spec_openai_platform = SpecialAgent(
    name="openai_platform",
    title=Title("OpenAI Platform"),
    parameter_form=_form,
    topic=Topic.CLOUD,
)
