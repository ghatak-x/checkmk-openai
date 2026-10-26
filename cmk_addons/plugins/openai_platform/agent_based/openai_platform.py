#!/usr/bin/env python3
# Copyright (C) 2026 Sudhir Chauhan
# License: GNU General Public License v2
# SPDX-License-Identifier: GPL-2.0-only

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from cmk.agent_based.v2 import (
    AgentSection,
    CheckPlugin,
    CheckResult,
    DiscoveryResult,
    Metric,
    Result,
    Service,
    State,
    StringTable,
)

Section = Mapping[str, Any]

CATEGORY_LABELS = {
    "completions": "Completions and Responses",
    "embeddings": "Embeddings",
    "images": "Images",
    "moderations": "Moderations",
    "audio_speeches": "Audio Speech",
    "audio_transcriptions": "Audio Transcription",
    "code_interpreter_sessions": "Code Interpreter",
    "vector_stores": "Vector Stores",
    "file_search_calls": "File Search",
    "web_search_calls": "Web Search",
}

ATTRIBUTION_CATEGORIES = (
    "completions",
    "embeddings",
    "images",
    "moderations",
    "audio_speeches",
    "audio_transcriptions",
)


PLATFORM_SETTINGS_URL = "https://platform.openai.com/settings/organization/general"
PLATFORM_USAGE_HELP_URL = "https://help.openai.com/en/articles/10478918-reviewing-api-usage-and-costs"
PLATFORM_PROJECTS_HELP_URL = "https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform"
PLATFORM_API_DOCS_URL = "https://platform.openai.com/docs/api-reference"

_STATE_BY_NAME = {
    "ok": State.OK,
    "warn": State.WARN,
    "crit": State.CRIT,
    "unknown": State.UNKNOWN,
}
_STATE_RANK = {State.OK: 0, State.WARN: 1, State.UNKNOWN: 2, State.CRIT: 3}


_NO_LEVELS = ("no_levels", None)
_ORG_POLICY_DEFAULTS = {
    "api": {"auth_failure": "crit", "required_failure": "crit", "optional_failure": "warn"},
    "overview": {"zero_active_projects": "ok", "zero_users": "ok"},
    "access": {"no_owner": "crit", "no_service_accounts": "ok", "no_api_keys": "ok"},
    "costs": {"today": _NO_LEVELS, "month_to_date": _NO_LEVELS},
    "usage": {"requests": _NO_LEVELS, "input_tokens": _NO_LEVELS, "output_tokens": _NO_LEVELS, "zero_activity": "ok"},
    "cost_allocation": {
        "largest_project_share": _NO_LEVELS,
        "unattributed_cost": _NO_LEVELS,
        "unattributed_share": _NO_LEVELS,
    },
    "usage_allocation": {"largest_project_share": _NO_LEVELS},
    "prompt_cache": {
        "minimum_hit_rate": _NO_LEVELS,
        "uncached_input_tokens": _NO_LEVELS,
    },
    "usage_attribution": {
        "largest_user_share": _NO_LEVELS,
        "largest_api_key_share": _NO_LEVELS,
    },
}
_PROJECT_POLICY_DEFAULTS = {
    "overview": {"archived": "ok", "inactive": "warn", "unknown": "unknown"},
    "access": {"no_owner": "crit", "no_service_accounts": "ok", "no_api_keys": "ok"},
    "costs": {"today": _NO_LEVELS, "month_to_date": _NO_LEVELS},
    "usage": {"requests": _NO_LEVELS, "input_tokens": _NO_LEVELS, "output_tokens": _NO_LEVELS, "zero_activity": "ok"},
    "rate_limits": {"used_model_without_limit": "warn", "no_records": "ok"},
}
_PROJECT_DISCOVERY_DEFAULTS = {
    "overview": True,
    "access": True,
    "costs": True,
    "usage": True,
    "rate_limits": True,
    "model_usage": True,
}


def _configured_state(params: Mapping[str, Any], key: str, default: State) -> State:
    return _STATE_BY_NAME.get(str(params.get(key, "")).lower(), default)


def _worst_state(states: list[State]) -> State:
    return max(states, key=lambda state: _STATE_RANK[state], default=State.OK)


def _nested_params(params: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = params.get(key)
    return value if isinstance(value, Mapping) else params


def _level_state(value: float, levels: object) -> State:
    if not isinstance(levels, tuple) or len(levels) != 2 or levels[0] != "fixed":
        return State.OK
    fixed = levels[1]
    if not isinstance(fixed, tuple) or len(fixed) != 2:
        return State.OK
    warn, crit = float(fixed[0]), float(fixed[1])
    if value >= crit:
        return State.CRIT
    if value >= warn:
        return State.WARN
    return State.OK


def _lower_level_state(value: float, levels: object) -> State:
    if not isinstance(levels, tuple) or len(levels) != 2 or levels[0] != "fixed":
        return State.OK
    fixed = levels[1]
    if not isinstance(fixed, tuple) or len(fixed) != 2:
        return State.OK
    warn, crit = float(fixed[0]), float(fixed[1])
    if value <= crit:
        return State.CRIT
    if value <= warn:
        return State.WARN
    return State.OK


def parse_openai_platform(string_table: StringTable) -> Section:
    if not string_table:
        return {}
    raw = "".join("".join(row) for row in string_table)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


agent_section_openai_platform = AgentSection(
    name="openai_platform",
    parse_function=parse_openai_platform,
)


def _org(section: Section) -> Mapping[str, Any]:
    value = section.get("organization", {})
    return value if isinstance(value, dict) else {}


def _projects(section: Section) -> list[dict[str, Any]]:
    value = section.get("projects", [])
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _usage(section: Section) -> Mapping[str, list[dict[str, Any]]]:
    value = _org(section).get("usage", {})
    return value if isinstance(value, dict) else {}


def _flatten_buckets(buckets: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(buckets, list):
        return
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        results = bucket.get("results", [])
        if not isinstance(results, list):
            continue
        for row in results:
            if isinstance(row, dict):
                yield row


def _num(row: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _category_stats(
    section: Section,
    category: str,
    *,
    project_id: str | None = None,
    model: str | None = None,
) -> dict[str, float]:
    buckets = _usage(section).get(category, [])
    stats: defaultdict[str, float] = defaultdict(float)
    for row in _flatten_buckets(buckets):
        if project_id is not None and str(row.get("project_id") or "") != project_id:
            continue
        if model is not None and str(row.get("model") or "") != model:
            continue
        stats["requests"] += _num(row, "num_model_requests", "num_requests", "requests")
        stats["input_tokens"] += _num(row, "input_tokens")
        stats["output_tokens"] += _num(row, "output_tokens")
        stats["cached_tokens"] += _num(row, "input_cached_tokens")
        stats["images"] += _num(row, "images")
        stats["characters"] += _num(row, "characters")
        stats["seconds"] += _num(row, "seconds")
        stats["sessions"] += _num(row, "num_sessions")
        stats["bytes"] += _num(row, "usage_bytes")
    return dict(stats)


def _category_active(stats: Mapping[str, float]) -> bool:
    return any(value > 0 for value in stats.values())


def _fmt_int(value: float) -> str:
    return f"{int(round(value)):,}"




def _usage_window_label(section: Section) -> str:
    config = section.get("configuration", {})
    seconds = 86400
    if isinstance(config, dict):
        raw = config.get("usage_window")
        if isinstance(raw, (int, float)) and raw > 0:
            seconds = int(raw)
    if seconds % 86400 == 0:
        days = seconds // 86400
        return f"{days}d"
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours}h"
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes}m"
    return f"{seconds}s"

def _usage_summary(
    section: Section,
    *,
    project_id: str | None = None,
    model: str | None = None,
) -> tuple[str, str, dict[str, dict[str, float]]]:
    window = _usage_window_label(section)
    all_stats = {
        category: _category_stats(section, category, project_id=project_id, model=model)
        for category in CATEGORY_LABELS
    }
    completions = all_stats["completions"]
    active = [cat for cat, stats in all_stats.items() if _category_active(stats)]

    if _category_active(completions) or not active:
        headline = (
            f"Last {window} completions/Responses: {_fmt_int(completions.get('requests', 0))} requests, "
            f"{_fmt_int(completions.get('input_tokens', 0))} input tokens, "
            f"{_fmt_int(completions.get('output_tokens', 0))} output tokens"
        )
    else:
        first = active[0]
        stats = all_stats[first]
        label = CATEGORY_LABELS[first]
        if first in {"embeddings", "moderations"}:
            headline = (
                f"Last {window} {label}: Requests: {_fmt_int(stats.get('requests', 0))}, "
                f"Input tokens: {_fmt_int(stats.get('input_tokens', 0))}"
            )
        elif first == "images":
            headline = (
                f"Last {window} {label}: Requests: {_fmt_int(stats.get('requests', 0))}, "
                f"Images: {_fmt_int(stats.get('images', 0))}"
            )
        elif first == "audio_speeches":
            headline = (
                f"Last {window} {label}: Requests: {_fmt_int(stats.get('requests', 0))}, "
                f"Characters: {_fmt_int(stats.get('characters', 0))}"
            )
        elif first == "audio_transcriptions":
            headline = (
                f"Last {window} {label}: Requests: {_fmt_int(stats.get('requests', 0))}, "
                f"Audio duration: {stats.get('seconds', 0):.2f} s"
            )
        elif first == "code_interpreter_sessions":
            headline = f"Last {window} {label}: Sessions: {_fmt_int(stats.get('sessions', 0))}"
        elif first == "vector_stores":
            headline = f"Last {window} {label}: Storage: {_fmt_int(stats.get('bytes', 0))} B"
        else:
            headline = f"Last {window} {label}: Requests: {_fmt_int(stats.get('requests', 0))}"

    input_tokens = float(completions.get("input_tokens", 0.0))
    cached_tokens = min(input_tokens, max(0.0, float(completions.get("cached_tokens", 0.0))))
    uncached_tokens = max(0.0, input_tokens - cached_tokens)
    cache_ratio = (cached_tokens / input_tokens * 100.0) if input_tokens > 0 else 0.0
    details = [
        f"Requests: {_fmt_int(completions.get('requests', 0))}",
        f"Input tokens: {_fmt_int(input_tokens)}",
        f"Output tokens: {_fmt_int(completions.get('output_tokens', 0))}",
        f"Cached input tokens: {_fmt_int(cached_tokens)} ({cache_ratio:.1f}% of input)",
        f"Uncached input tokens: {_fmt_int(uncached_tokens)}",
    ]
    additional = [CATEGORY_LABELS[c] for c in active if c != "completions"]
    if additional:
        details.append("Additional active usage families: " + ", ".join(additional))
    return headline, "\n".join(details), all_stats


def discover_platform_api(section: Section) -> DiscoveryResult:
    yield Service()


def check_platform_api(params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "api")
    api = section.get("api", {})
    calls = api.get("calls", []) if isinstance(api, dict) else []
    calls = [c for c in calls if isinstance(c, dict)] if isinstance(calls, list) else []
    failed = [c for c in calls if c.get("error_code")]
    auth_failed = [c for c in failed if c.get("error_code") in {"invalid_api_key", "access_denied"}]
    required_failed = [c for c in failed if c.get("required")]
    max_response = max((float(c.get("response_time") or 0.0) for c in calls), default=0.0)

    details: list[str] = []
    for call in failed:
        details.append(f"{call.get('label')}: {call.get('error_summary') or call.get('error_code')}")
    details.append(
        "The endpoint count is the set queried by this collector version; it is not a provider inventory "
        "baseline and can change when collector coverage changes."
    )
    details.append(f"Maximum endpoint response time: {max_response:.2f} s")

    if auth_failed:
        state = _configured_state(params, "auth_failure", State.CRIT)
        summary = f"OpenAI Admin API authentication/access failed; {len(auth_failed)} endpoint(s) affected"
    elif required_failed:
        state = _configured_state(params, "required_failure", State.CRIT)
        summary = f"API collection failed for {len(required_failed)} required endpoint(s)"
    elif failed:
        state = _configured_state(params, "optional_failure", State.WARN)
        summary = f"API collection completed with {len(failed)} endpoint warning(s)"
    else:
        state = State.OK
        summary = f"API collection successful across {len(calls)} configured endpoint(s)"
    yield Result(state=state, summary=summary, details="\n".join(details))
    yield Metric("openai_platform_api_response_time", max_response)


check_plugin_openai_platform_api = CheckPlugin(
    name="openai_platform_api",
    sections=["openai_platform"],
    service_name="OpenAI Platform API",
    discovery_function=discover_platform_api,
    check_function=check_platform_api,
    check_default_parameters=_ORG_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_organization_policy",
)


def discover_org_overview(section: Section) -> DiscoveryResult:
    yield Service()


def check_org_overview(params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "overview")
    projects = _org(section).get("projects", [])
    users = _org(section).get("users", [])
    projects = [p for p in projects if isinstance(p, dict)] if isinstance(projects, list) else []
    users = [u for u in users if isinstance(u, dict)] if isinstance(users, list) else []
    active = sum(str(p.get("status", "active")).lower() != "archived" for p in projects)
    archived = len(projects) - active
    states = [State.OK]
    if active == 0:
        states.append(_configured_state(params, "zero_active_projects", State.OK))
    if len(users) == 0:
        states.append(_configured_state(params, "zero_users", State.OK))
    yield Result(
        state=_worst_state(states),
        summary=f"Projects: {len(projects)} ({active} active, {archived} archived), users: {len(users)}",
        details=(
            "These are live organization inventory counts from OpenAI. They are intentionally not "
            "compared with fixed expected totals because projects and users can be created, archived "
            "or removed over time."
        ),
    )


check_plugin_openai_platform_org_overview = CheckPlugin(
    name="openai_platform_org_overview",
    sections=["openai_platform"],
    service_name="OpenAI Organization Overview",
    discovery_function=discover_org_overview,
    check_function=check_org_overview,
    check_default_parameters=_ORG_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_organization_policy",
)


def discover_org_access(section: Section) -> DiscoveryResult:
    yield Service()


def check_org_access(params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "access")
    users = _org(section).get("users", [])
    users = [u for u in users if isinstance(u, dict)] if isinstance(users, list) else []
    owners = sum(str(u.get("role", "")).lower() == "owner" for u in users)
    projects = _projects(section)
    service_accounts = sum(len(p.get("service_accounts", [])) for p in projects)
    api_keys = sum(len(p.get("api_keys", [])) for p in projects)
    project_rows: list[str] = []
    projects_with_owner = 0
    projects_with_service_accounts = 0
    projects_with_api_keys = 0
    for project in projects:
        pusers = project.get("users", []) if isinstance(project.get("users"), list) else []
        powners = sum(isinstance(u, dict) and str(u.get("role", "")).lower() == "owner" for u in pusers)
        psa = project.get("service_accounts", []) if isinstance(project.get("service_accounts"), list) else []
        pkeys = project.get("api_keys", []) if isinstance(project.get("api_keys"), list) else []
        projects_with_owner += int(powners > 0)
        projects_with_service_accounts += int(bool(psa))
        projects_with_api_keys += int(bool(pkeys))
        project_rows.append(
            f"{project.get('name', project.get('id', 'Unknown'))}: users {len(pusers)} ({powners} owners), "
            f"service accounts {len(psa)}, API keys {len(pkeys)}"
        )
    states = [State.OK]
    if owners == 0:
        states.append(_configured_state(params, "no_owner", State.CRIT))
    if service_accounts == 0:
        states.append(_configured_state(params, "no_service_accounts", State.OK))
    if api_keys == 0:
        states.append(_configured_state(params, "no_api_keys", State.OK))
    details = [
        "Counts are the current organization/project access inventory returned by OpenAI; they are dynamic and are not compared with fixed expected totals.",
        f"Projects with owner: {projects_with_owner}/{len(projects)}; with service accounts: {projects_with_service_accounts}/{len(projects)}; with API keys: {projects_with_api_keys}/{len(projects)}",
        *project_rows,
    ]
    yield Result(
        state=_worst_state(states),
        summary=(
            f"Users: {len(users)}, owners: {owners}, service accounts: {service_accounts}, API keys: {api_keys}; "
            f"projects with owners: {projects_with_owner}/{len(projects)}"
        ),
        details="\n".join(details),
    )
    yield Metric("openai_platform_projects_with_owner", projects_with_owner)
    yield Metric("openai_platform_projects_with_service_accounts", projects_with_service_accounts)
    yield Metric("openai_platform_projects_with_api_keys", projects_with_api_keys)


check_plugin_openai_platform_org_access = CheckPlugin(
    name="openai_platform_org_access",
    sections=["openai_platform"],
    service_name="OpenAI Organization Access",
    discovery_function=discover_org_access,
    check_function=check_org_access,
    check_default_parameters=_ORG_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_organization_policy",
)


def _cost_buckets(section: Section) -> list[dict[str, Any]]:
    costs = _org(section).get("costs", [])
    return [x for x in costs if isinstance(x, dict)] if isinstance(costs, list) else []


def _cost_totals(section: Section, project_id: str | None = None) -> tuple[float, float, float]:
    now = datetime.now(timezone.utc)
    today_key = now.date()
    previous_key = (datetime.fromtimestamp(now.timestamp() - 86400, timezone.utc)).date()
    today = previous = mtd = 0.0
    for bucket in _cost_buckets(section):
        start = bucket.get("start_time")
        try:
            day = datetime.fromtimestamp(float(start), timezone.utc).date()
        except (TypeError, ValueError, OSError):
            continue
        results = bucket.get("results", [])
        if not isinstance(results, list):
            continue
        bucket_total = 0.0
        for row in results:
            if not isinstance(row, dict):
                continue
            if project_id is not None and str(row.get("project_id") or "") != project_id:
                continue
            amount = row.get("amount", {})
            if isinstance(amount, dict):
                bucket_total += float(amount.get("value") or 0.0)
        mtd += bucket_total
        if day == today_key:
            today += bucket_total
        elif day == previous_key:
            previous += bucket_total
    return today, previous, mtd


def _check_costs(
    params: Mapping[str, Any], section: Section, project_id: str | None = None
) -> CheckResult:
    today, previous, mtd = _cost_totals(section, project_id)
    state = _worst_state([
        _level_state(today, params.get("today")),
        _level_state(mtd, params.get("month_to_date")),
    ])
    yield Result(
        state=state,
        summary=f"Today: ${today:.4f}, previous day: ${previous:.4f}, month-to-date: ${mtd:.4f}",
        details=(
            "Cost values are provider billing data for the selected organization/project and period; "
            "no fixed spend threshold is built into the check. Configure thresholds with the service "
            "monitoring rule if desired."
        ),
    )
    yield Metric("openai_platform_cost_today_usd", today)
    yield Metric("openai_platform_cost_previous_day_usd", previous)
    yield Metric("openai_platform_cost_month_to_date_usd", mtd)


def discover_org_costs(section: Section) -> DiscoveryResult:
    yield Service()


def check_org_costs(params: Mapping[str, Any], section: Section) -> CheckResult:
    yield from _check_costs(_nested_params(params, "costs"), section)


check_plugin_openai_platform_org_costs = CheckPlugin(
    name="openai_platform_org_costs",
    sections=["openai_platform"],
    service_name="OpenAI Organization Costs",
    discovery_function=discover_org_costs,
    check_function=check_org_costs,
    check_default_parameters=_ORG_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_organization_policy",
)


def _project_cost_rows(section: Section) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for project in _projects(section):
        project_id = str(project.get("id", ""))
        if not project_id:
            continue
        today, previous, mtd = _cost_totals(section, project_id)
        rows.append({
            "id": project_id,
            "name": str(project.get("name", project_id)),
            "today": today,
            "previous": previous,
            "mtd": mtd,
        })
    return rows


def discover_org_cost_allocation(section: Section) -> DiscoveryResult:
    yield Service()


def check_org_cost_allocation(params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "cost_allocation")
    _today, _previous, org_mtd = _cost_totals(section)
    rows = _project_cost_rows(section)
    attributed = sum(float(row["mtd"]) for row in rows)
    unattributed = org_mtd - attributed
    if abs(unattributed) < 0.0000005:
        unattributed = 0.0
    ranked = sorted(rows, key=lambda row: (-float(row["mtd"]), str(row["name"]).lower()))
    largest = ranked[0] if ranked else None
    largest_cost = float(largest["mtd"]) if largest else 0.0
    largest_share = (largest_cost / org_mtd * 100.0) if org_mtd > 0 else 0.0
    unattributed_share = (unattributed / org_mtd * 100.0) if org_mtd > 0 else 0.0
    projects_with_spend = sum(float(row["mtd"]) > 0 for row in rows)
    states = [
        _level_state(largest_share, params.get("largest_project_share")),
        _level_state(max(unattributed, 0.0), params.get("unattributed_cost")),
        _level_state(max(unattributed_share, 0.0), params.get("unattributed_share")),
    ]
    if largest and org_mtd > 0:
        summary = (
            f"MTD ${org_mtd:.4f} across {len(rows)} project(s); largest: {largest['name']} "
            f"${largest_cost:.4f} ({largest_share:.1f}%)"
        )
    else:
        summary = f"MTD ${org_mtd:.4f} across {len(rows)} project(s); no attributed project spend"
    if abs(unattributed) >= 0.0000005:
        summary += f", unattributed/other ${unattributed:.4f}"
    details = [
        "Project attribution is calculated dynamically from provider-reported organization cost rows grouped by project_id.",
        "Organization totals can differ from the sum of project-attributed rows because of provider attribution, aggregation, timing or rounding.",
    ]
    for row in ranked:
        share = (float(row["mtd"]) / org_mtd * 100.0) if org_mtd > 0 else 0.0
        details.append(
            f"{row['name']}: today ${float(row['today']):.4f}, previous ${float(row['previous']):.4f}, "
            f"MTD ${float(row['mtd']):.4f}, share {share:.1f}%"
        )
    if abs(unattributed) >= 0.0000005:
        details.append(f"Unattributed/other: ${unattributed:.4f} ({unattributed_share:.1f}% of organization MTD)")
    yield Result(state=_worst_state(states), summary=summary, details="\n".join(details))
    yield Metric("openai_platform_largest_project_cost_mtd_usd", largest_cost)
    yield Metric("openai_platform_largest_project_cost_share_percent", largest_share)
    yield Metric("openai_platform_projects_with_spend", projects_with_spend)
    yield Metric("openai_platform_unattributed_cost_mtd_usd", unattributed)
    yield Metric("openai_platform_unattributed_cost_share_percent", unattributed_share)


check_plugin_openai_platform_org_cost_allocation = CheckPlugin(
    name="openai_platform_org_cost_allocation",
    sections=["openai_platform"],
    service_name="OpenAI Organization Cost Allocation",
    discovery_function=discover_org_cost_allocation,
    check_function=check_org_cost_allocation,
    check_default_parameters=_ORG_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_organization_policy",
)


def _check_usage(
    params: Mapping[str, Any],
    section: Section,
    *,
    project_id: str | None = None,
    model: str | None = None,
) -> CheckResult:
    summary, details, stats = _usage_summary(section, project_id=project_id, model=model)
    comp = stats["completions"]
    any_activity = any(_category_active(category_stats) for category_stats in stats.values())
    states = [
        _level_state(comp.get("requests", 0.0), params.get("requests")),
        _level_state(comp.get("input_tokens", 0.0), params.get("input_tokens")),
        _level_state(comp.get("output_tokens", 0.0), params.get("output_tokens")),
    ]
    if not any_activity:
        states.append(_configured_state(params, "zero_activity", State.OK))
    full_details = (
        details
        + "\nUsage values are provider-reported for the configured aggregation window; totals are dynamic. "
        "Thresholds are disabled by default."
    )
    yield Result(
        state=_worst_state(states),
        summary=summary,
        details=full_details,
    )
    input_tokens = float(comp.get("input_tokens", 0.0))
    cached_tokens = min(input_tokens, max(0.0, float(comp.get("cached_tokens", 0.0))))
    uncached_tokens = max(0.0, input_tokens - cached_tokens)
    cache_ratio = (cached_tokens / input_tokens * 100.0) if input_tokens > 0 else 0.0
    yield Metric("openai_platform_requests", comp.get("requests", 0.0))
    yield Metric("openai_platform_input_tokens", input_tokens)
    yield Metric("openai_platform_output_tokens", comp.get("output_tokens", 0.0))
    yield Metric("openai_platform_cached_input_tokens", cached_tokens)
    yield Metric("openai_platform_uncached_input_tokens", uncached_tokens)
    yield Metric("openai_platform_prompt_cache_hit_percent", cache_ratio)


def discover_org_usage(section: Section) -> DiscoveryResult:
    yield Service()


def check_org_usage(params: Mapping[str, Any], section: Section) -> CheckResult:
    yield from _check_usage(_nested_params(params, "usage"), section)


_USAGE_DEFAULTS = {
    "requests": ("no_levels", None),
    "input_tokens": ("no_levels", None),
    "output_tokens": ("no_levels", None),
    "zero_activity": "ok",
}


check_plugin_openai_platform_org_usage = CheckPlugin(
    name="openai_platform_org_usage",
    sections=["openai_platform"],
    service_name="OpenAI Organization Usage",
    discovery_function=discover_org_usage,
    check_function=check_org_usage,
    check_default_parameters=_ORG_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_organization_policy",
)



def _prompt_cache_stats(
    section: Section,
    *,
    project_id: str | None = None,
    model: str | None = None,
) -> dict[str, float]:
    stats = _category_stats(section, "completions", project_id=project_id, model=model)
    input_tokens = max(0.0, float(stats.get("input_tokens", 0.0)))
    cached_tokens = min(input_tokens, max(0.0, float(stats.get("cached_tokens", 0.0))))
    uncached_tokens = max(0.0, input_tokens - cached_tokens)
    return {
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "uncached_tokens": uncached_tokens,
        "hit_percent": (cached_tokens / input_tokens * 100.0) if input_tokens > 0 else 0.0,
    }


def discover_org_prompt_cache(section: Section) -> DiscoveryResult:
    yield Service()


def check_org_prompt_cache(params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "prompt_cache")
    window = _usage_window_label(section)
    stats = _prompt_cache_stats(section)
    input_tokens = stats["input_tokens"]
    cached_tokens = stats["cached_tokens"]
    uncached_tokens = stats["uncached_tokens"]
    hit_percent = stats["hit_percent"]

    project_names = {
        str(project.get("id", "")): str(project.get("name", project.get("id", "")))
        for project in _projects(section)
        if project.get("id")
    }
    project_rows: list[tuple[str, dict[str, float]]] = []
    for project_id, project_name in project_names.items():
        row_stats = _prompt_cache_stats(section, project_id=project_id)
        if row_stats["input_tokens"] > 0:
            project_rows.append((project_name, row_stats))
    project_rows.sort(key=lambda item: (-item[1]["input_tokens"], item[0].lower()))

    models: set[str] = set()
    for row in _flatten_buckets(_usage(section).get("completions", [])):
        model = str(row.get("model") or "")
        if model:
            models.add(model)
    model_rows: list[tuple[str, dict[str, float]]] = []
    for model in models:
        row_stats = _prompt_cache_stats(section, model=model)
        if row_stats["input_tokens"] > 0:
            model_rows.append((model, row_stats))
    model_rows.sort(key=lambda item: (-item[1]["input_tokens"], item[0].lower()))

    states = [
        _level_state(uncached_tokens, params.get("uncached_input_tokens")),
    ]
    if input_tokens > 0:
        states.append(_lower_level_state(hit_percent, params.get("minimum_hit_rate")))

    summary = (
        f"Last {window}: {_fmt_int(cached_tokens)} cached / {_fmt_int(input_tokens)} input tokens "
        f"({hit_percent:.1f}% cache-read ratio), {_fmt_int(uncached_tokens)} uncached"
    )
    details = [
        "Cache-read ratio is calculated as provider-reported input_cached_tokens / input_tokens "
        "for Completions/Responses usage. It is a token-level ratio, not a request hit rate.",
        "Scope note: Prompt Cache covers Completions/Responses input tokens only. Other usage families "
        "such as embeddings are not part of this denominator, so these token totals can be lower than "
        "Organization Usage Attribution totals.",
        "The organization Usage API exposes cached input tokens but does not expose the portal's "
        "cache-write token windows, so cache writes are intentionally not inferred.",
    ]
    if project_rows:
        details.append("Projects:")
        for name, row_stats in project_rows[:10]:
            details.append(
                f"{name}: {_fmt_int(row_stats['cached_tokens'])} cached / "
                f"{_fmt_int(row_stats['input_tokens'])} input tokens "
                f"({row_stats['hit_percent']:.1f}%)"
            )
        if len(project_rows) > 10:
            details.append(f"... {len(project_rows) - 10} more project(s)")
    if model_rows:
        details.append("Models:")
        for name, row_stats in model_rows[:10]:
            details.append(
                f"{name}: {_fmt_int(row_stats['cached_tokens'])} cached / "
                f"{_fmt_int(row_stats['input_tokens'])} input tokens "
                f"({row_stats['hit_percent']:.1f}%)"
            )
        if len(model_rows) > 10:
            details.append(f"... {len(model_rows) - 10} more model(s)")

    yield Result(state=_worst_state(states), summary=summary, details="\n".join(details))
    yield Metric("openai_platform_cached_input_tokens", cached_tokens)
    yield Metric("openai_platform_uncached_input_tokens", uncached_tokens)
    yield Metric("openai_platform_prompt_cache_hit_percent", hit_percent)


check_plugin_openai_platform_org_prompt_cache = CheckPlugin(
    name="openai_platform_org_prompt_cache",
    sections=["openai_platform"],
    service_name="OpenAI Organization Prompt Cache",
    discovery_function=discover_org_prompt_cache,
    check_function=check_org_prompt_cache,
    check_default_parameters=_ORG_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_organization_policy",
)


def _user_display_label(row: Mapping[str, Any], fallback_id: str) -> str:
    nested = row.get("user") if isinstance(row.get("user"), dict) else {}
    name = str(row.get("name") or nested.get("name") or "").strip()
    email = str(row.get("email") or nested.get("email") or "").strip()
    if name and email and email.lower() not in name.lower():
        return f"{name} <{email}>"
    if name:
        return name
    if email:
        return email
    return fallback_id


def _user_id_aliases(user_id: str) -> set[str]:
    aliases = {user_id}
    # OpenAI documentation/examples have historically shown both user_... and user-...
    # forms. Treat the first separator as an alias only for display-name resolution.
    if user_id.startswith("user_"):
        aliases.add("user-" + user_id[5:])
    elif user_id.startswith("user-"):
        aliases.add("user_" + user_id[5:])
    return aliases


def _org_user_labels(section: Section) -> dict[str, str]:
    labels: dict[str, str] = {}

    def add_rows(rows: object) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            nested = row.get("user") if isinstance(row.get("user"), dict) else {}
            user_id = str(row.get("id") or nested.get("id") or "")
            if not user_id:
                continue
            label = _user_display_label(row, user_id)
            for alias in _user_id_aliases(user_id):
                labels.setdefault(alias, label)

    # Organization users are authoritative, but project membership can contain a
    # friendlier name/email even when the organization-user response is sparse.
    add_rows(_org(section).get("users", []))
    for project in _projects(section):
        add_rows(project.get("users", []))

    return labels


def _api_key_metadata(section: Section) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    for project in _projects(section):
        project_name = str(project.get("name", project.get("id", "project")))
        api_keys = project.get("api_keys", [])
        if not isinstance(api_keys, list):
            continue
        for row in api_keys:
            if not isinstance(row, dict):
                continue
            key_id = str(row.get("id") or "")
            if not key_id:
                continue
            key_name = str(row.get("name") or key_id)
            info = {
                "label": f"{project_name}/{key_name}",
                "owner_type": "",
                "owner_label": "",
            }
            owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
            owner_type = str(owner.get("type") or "").strip().lower()
            if owner_type == "service_account":
                service_account = owner.get("service_account") if isinstance(owner.get("service_account"), dict) else {}
                owner_id = str(service_account.get("id") or "")
                owner_name = str(service_account.get("name") or "").strip()
                info["owner_type"] = "service_account"
                info["owner_label"] = owner_name or owner_id
            elif owner_type == "user":
                user = owner.get("user") if isinstance(owner.get("user"), dict) else {}
                owner_id = str(user.get("id") or "")
                info["owner_type"] = "user"
                info["owner_label"] = _user_display_label(user, owner_id or "user")
            metadata[key_id] = info
    return metadata


def _api_key_labels(section: Section) -> dict[str, str]:
    return {key_id: info["label"] for key_id, info in _api_key_metadata(section).items()}


def _attribution_enabled(section: Section) -> bool:
    config = section.get("configuration", {})
    return bool(config.get("collect_usage_attribution", False)) if isinstance(config, dict) else False


def _attribution_totals(section: Section) -> tuple[
    dict[str, dict[str, float]],
    dict[str, dict[str, float]],
    dict[str, float],
]:
    users: defaultdict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))
    api_keys: defaultdict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))
    totals: defaultdict[str, float] = defaultdict(float)

    for category in ATTRIBUTION_CATEGORIES:
        for row in _flatten_buckets(_usage(section).get(category, [])):
            requests = _num(row, "num_model_requests", "num_requests", "requests")
            input_tokens = _num(row, "input_tokens")
            output_tokens = _num(row, "output_tokens")
            cached_tokens = _num(row, "input_cached_tokens")

            totals["requests"] += requests
            totals["input_tokens"] += input_tokens
            totals["output_tokens"] += output_tokens
            totals["cached_tokens"] += cached_tokens

            user_id = str(row.get("user_id") or "")
            key_id = str(row.get("api_key_id") or "")
            user_bucket = users[user_id or "__unattributed__"]
            key_bucket = api_keys[key_id or "__unattributed__"]
            for bucket in (user_bucket, key_bucket):
                bucket["requests"] += requests
                bucket["input_tokens"] += input_tokens
                bucket["output_tokens"] += output_tokens
                bucket["cached_tokens"] += cached_tokens

    return (
        {key: dict(value) for key, value in users.items()},
        {key: dict(value) for key, value in api_keys.items()},
        dict(totals),
    )


def discover_org_usage_attribution(section: Section) -> DiscoveryResult:
    if _attribution_enabled(section):
        yield Service()


def check_org_usage_attribution(params: Mapping[str, Any], section: Section) -> CheckResult:
    if not _attribution_enabled(section):
        return
    params = _nested_params(params, "usage_attribution")
    window = _usage_window_label(section)
    users, api_keys, totals = _attribution_totals(section)
    user_labels = _org_user_labels(section)
    key_metadata = _api_key_metadata(section)
    key_labels = {key_id: info["label"] for key_id, info in key_metadata.items()}
    total_requests = float(totals.get("requests", 0.0))

    provider_users = [(key, value) for key, value in users.items() if key != "__unattributed__"]
    resolved_users = [(key, value) for key, value in provider_users if key in user_labels]
    unresolved_users = [(key, value) for key, value in provider_users if key not in user_labels]
    attributed_keys = [(key, value) for key, value in api_keys.items() if key != "__unattributed__"]
    resolved_users.sort(key=lambda item: (-item[1].get("requests", 0.0), user_labels[item[0]].lower()))
    unresolved_users.sort(key=lambda item: (-item[1].get("requests", 0.0), item[0].lower()))
    attributed_keys.sort(key=lambda item: (-item[1].get("requests", 0.0), key_labels.get(item[0], item[0]).lower()))

    top_user = resolved_users[0] if resolved_users else None
    top_key = attributed_keys[0] if attributed_keys else None
    top_user_requests = float(top_user[1].get("requests", 0.0)) if top_user else 0.0
    top_key_requests = float(top_key[1].get("requests", 0.0)) if top_key else 0.0
    top_user_share = (top_user_requests / total_requests * 100.0) if total_requests > 0 else 0.0
    top_key_share = (top_key_requests / total_requests * 100.0) if total_requests > 0 else 0.0
    missing_user_id_requests = float(users.get("__unattributed__", {}).get("requests", 0.0))
    unresolved_user_requests = sum(float(stats.get("requests", 0.0)) for _, stats in unresolved_users)
    unattributed_user = missing_user_id_requests + unresolved_user_requests
    unattributed_key = float(api_keys.get("__unattributed__", {}).get("requests", 0.0))

    states = [
        _level_state(top_user_share, params.get("largest_user_share")),
        _level_state(top_key_share, params.get("largest_api_key_share")),
    ]

    if total_requests <= 0:
        summary = f"Last {window}: no attributable request/call activity"
    else:
        summary_parts = [f"Last {window}: {_fmt_int(total_requests)} request/call events"]
        if top_key:
            key_id, _ = top_key
            key_info = key_metadata.get(key_id, {})
            key_label = key_labels.get(key_id, key_id)
            owner_type = key_info.get("owner_type", "")
            owner_label = key_info.get("owner_label", "")
            if owner_type == "service_account" and owner_label:
                summary_parts.append(
                    f"top caller service account {owner_label} via API key {key_label} "
                    f"{_fmt_int(top_key_requests)} ({top_key_share:.1f}%)"
                )
            elif owner_type == "user" and owner_label:
                summary_parts.append(
                    f"top caller {owner_label} via API key {key_label} "
                    f"{_fmt_int(top_key_requests)} ({top_key_share:.1f}%)"
                )
            else:
                summary_parts.append(
                    f"top API key {key_label} {_fmt_int(top_key_requests)} ({top_key_share:.1f}%)"
                )
        elif top_user:
            summary_parts.append(
                f"top resolved user {user_labels[top_user[0]]} "
                f"{_fmt_int(top_user_requests)} ({top_user_share:.1f}%)"
            )
        summary = "; ".join(summary_parts)

    details = [
        "Attribution covers Usage API families where OpenAI documents user_id and api_key_id grouping: "
        "Completions/Responses, Embeddings, Images, Moderations, Audio Speech and Audio Transcription.",
        "API-key owner identity is taken from the project API-key inventory. Provider-reported Usage API user_id "
        "values are treated as human users only when they resolve to organization/project user inventory.",
        "API key secret values are never collected or displayed.",
        "Token totals here aggregate the supported attribution families and can exceed Prompt Cache totals, "
        "which cover Completions/Responses only.",
    ]
    if attributed_keys:
        details.append("API keys / owners:")
        for key_id, stats in attributed_keys[:10]:
            share = (float(stats.get("requests", 0.0)) / total_requests * 100.0) if total_requests > 0 else 0.0
            key_info = key_metadata.get(key_id, {})
            owner_type = key_info.get("owner_type", "")
            owner_label = key_info.get("owner_label", "")
            owner_suffix = ""
            if owner_type == "service_account" and owner_label:
                owner_suffix = f" [owner: service account {owner_label}]"
            elif owner_type == "user" and owner_label:
                owner_suffix = f" [owner: user {owner_label}]"
            details.append(
                f"{key_labels.get(key_id, key_id)}{owner_suffix}: {_fmt_int(stats.get('requests', 0))} requests/calls "
                f"({share:.1f}%), {_fmt_int(stats.get('input_tokens', 0))} input tokens, "
                f"{_fmt_int(stats.get('output_tokens', 0))} output tokens"
            )
        if len(attributed_keys) > 10:
            details.append(f"... {len(attributed_keys) - 10} more active API key(s)")
    if resolved_users:
        details.append("Resolved Usage API users:")
        for user_id, stats in resolved_users[:10]:
            share = (float(stats.get("requests", 0.0)) / total_requests * 100.0) if total_requests > 0 else 0.0
            details.append(
                f"{user_labels[user_id]}: {_fmt_int(stats.get('requests', 0))} requests/calls "
                f"({share:.1f}%), {_fmt_int(stats.get('input_tokens', 0))} input tokens, "
                f"{_fmt_int(stats.get('output_tokens', 0))} output tokens"
            )
        if len(resolved_users) > 10:
            details.append(f"... {len(resolved_users) - 10} more resolved active user(s)")
    if unresolved_users:
        details.append(
            "Provider-reported unresolved usage user_id metadata (diagnostic only; same events, not additional usage):"
        )
        for user_id, stats in unresolved_users[:10]:
            share = (float(stats.get("requests", 0.0)) / total_requests * 100.0) if total_requests > 0 else 0.0
            details.append(
                f"{user_id}: attached to {_fmt_int(stats.get('requests', 0))} request/call events "
                f"({share:.1f}% of the window)"
            )
        if len(unresolved_users) > 10:
            details.append(f"... {len(unresolved_users) - 10} more unresolved provider user_id value(s)")
    if missing_user_id_requests > 0:
        details.append(f"Requests/calls without provider user_id: {_fmt_int(missing_user_id_requests)}")
    if unattributed_key > 0:
        details.append(f"Requests/calls without API-key attribution: {_fmt_int(unattributed_key)}")

    yield Result(state=_worst_state(states), summary=summary, details="\n".join(details))
    yield Metric("openai_platform_attributed_requests", total_requests)
    yield Metric("openai_platform_active_users", len(resolved_users))
    yield Metric("openai_platform_active_api_keys", len(attributed_keys))
    yield Metric("openai_platform_largest_user_requests", top_user_requests)
    yield Metric("openai_platform_largest_user_request_share_percent", top_user_share)
    yield Metric("openai_platform_largest_api_key_requests", top_key_requests)
    yield Metric("openai_platform_largest_api_key_request_share_percent", top_key_share)
    yield Metric("openai_platform_unattributed_user_requests", unattributed_user)
    yield Metric("openai_platform_unattributed_api_key_requests", unattributed_key)


check_plugin_openai_platform_org_usage_attribution = CheckPlugin(
    name="openai_platform_org_usage_attribution",
    sections=["openai_platform"],
    service_name="OpenAI Organization Usage Attribution",
    discovery_function=discover_org_usage_attribution,
    check_function=check_org_usage_attribution,
    check_default_parameters=_ORG_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_organization_policy",
)


def _project_usage_totals(section: Section, project_id: str) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for category in CATEGORY_LABELS:
        stats = _category_stats(section, category, project_id=project_id)
        totals["requests"] += float(stats.get("requests", 0.0))
        totals["input_tokens"] += float(stats.get("input_tokens", 0.0))
        totals["output_tokens"] += float(stats.get("output_tokens", 0.0))
        totals["sessions"] += float(stats.get("sessions", 0.0))
    return dict(totals)


def discover_org_usage_allocation(section: Section) -> DiscoveryResult:
    yield Service()


def check_org_usage_allocation(params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "usage_allocation")
    window = _usage_window_label(section)
    rows: list[dict[str, Any]] = []
    for project in _projects(section):
        project_id = str(project.get("id", ""))
        if not project_id:
            continue
        totals = _project_usage_totals(section, project_id)
        rows.append({"name": str(project.get("name", project_id)), **totals})
    total_requests = sum(float(row.get("requests", 0.0)) for row in rows)
    ranked = sorted(rows, key=lambda row: (-float(row.get("requests", 0.0)), str(row["name"]).lower()))
    largest = ranked[0] if ranked else None
    largest_requests = float(largest.get("requests", 0.0)) if largest else 0.0
    largest_share = (largest_requests / total_requests * 100.0) if total_requests > 0 else 0.0
    active_projects = sum(float(row.get("requests", 0.0)) > 0 for row in rows)
    state = _level_state(largest_share, params.get("largest_project_share"))
    if largest and total_requests > 0:
        summary = (
            f"Last {window}: {_fmt_int(total_requests)} request/call(s) across {len(rows)} project(s); largest: "
            f"{largest['name']} {_fmt_int(largest_requests)} ({largest_share:.1f}%)"
        )
    else:
        summary = f"Last {window}: no request/call activity attributed across {len(rows)} project(s)"
    details = [
        "Project usage attribution sums request-like activity across the collected OpenAI usage families and groups it by project_id.",
        "The project inventory and activity mix are dynamic; no fixed expected project count is used.",
    ]
    for row in ranked:
        requests = float(row.get("requests", 0.0))
        share = (requests / total_requests * 100.0) if total_requests > 0 else 0.0
        details.append(
            f"{row['name']}: {_fmt_int(requests)} requests/calls, {_fmt_int(float(row.get('input_tokens', 0.0)))} input tokens, "
            f"{_fmt_int(float(row.get('output_tokens', 0.0)))} output tokens, share {share:.1f}%"
        )
    yield Result(state=state, summary=summary, details="\n".join(details))
    yield Metric("openai_platform_all_requests", total_requests)
    yield Metric("openai_platform_largest_project_requests", largest_requests)
    yield Metric("openai_platform_largest_project_request_share_percent", largest_share)
    yield Metric("openai_platform_projects_with_activity", active_projects)


check_plugin_openai_platform_org_usage_allocation = CheckPlugin(
    name="openai_platform_org_usage_allocation",
    sections=["openai_platform"],
    service_name="OpenAI Organization Usage Allocation",
    discovery_function=discover_org_usage_allocation,
    check_function=check_org_usage_allocation,
    check_default_parameters=_ORG_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_organization_policy",
)


def _project_by_name(section: Section, item: str) -> dict[str, Any] | None:
    return next((p for p in _projects(section) if str(p.get("name")) == item), None)


def _discover_projects(section: Section) -> DiscoveryResult:
    for project in _projects(section):
        yield Service(item=str(project.get("name", project.get("id", "Unknown"))))


def discover_project_overview(params: Mapping[str, Any], section: Section) -> DiscoveryResult:
    if params.get("overview", True):
        yield from _discover_projects(section)


def check_project_overview(item: str, params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "overview")
    project = _project_by_name(section, item)
    if project is None:
        return
    status = str(project.get("status", "unknown")).lower()
    project_id = str(project.get("id", ""))
    details: list[str] = []
    created_raw = project.get("created_at")
    if created_raw:
        try:
            if isinstance(created_raw, (int, float)):
                created = datetime.fromtimestamp(float(created_raw), timezone.utc)
            else:
                created = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds() / 86400
            details.append(f"Created: {created.isoformat()}, age: {age_days:.1f} days")
        except (ValueError, TypeError, OSError):
            details.append(f"Created: {created_raw}")
    if status == "active":
        state = State.OK
    elif status == "archived":
        state = _configured_state(params, "archived", State.OK)
    elif status in {"inactive", "disabled"}:
        state = _configured_state(params, "inactive", State.WARN)
    else:
        state = _configured_state(params, "unknown", State.UNKNOWN)
    yield Result(
        state=state,
        summary=f"Status: {status}, ID: {project_id}",
        details="\n".join(details),
    )


check_plugin_openai_platform_project_overview = CheckPlugin(
    name="openai_platform_project_overview",
    sections=["openai_platform"],
    service_name="OpenAI Project %s Overview",
    discovery_function=discover_project_overview,
    discovery_default_parameters=_PROJECT_DISCOVERY_DEFAULTS,
    discovery_ruleset_name="openai_platform_project_services",
    check_function=check_project_overview,
    check_default_parameters=_PROJECT_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_project_policy",
)


def discover_project_access(params: Mapping[str, Any], section: Section) -> DiscoveryResult:
    if params.get("access", True):
        yield from _discover_projects(section)


def check_project_access(item: str, params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "access")
    project = _project_by_name(section, item)
    if project is None:
        return
    users = project.get("users", []) if isinstance(project.get("users"), list) else []
    owners = sum(isinstance(u, dict) and str(u.get("role", "")).lower() == "owner" for u in users)
    service_accounts = project.get("service_accounts", [])
    api_keys = project.get("api_keys", [])
    service_account_count = len(service_accounts) if isinstance(service_accounts, list) else 0
    api_key_count = len(api_keys) if isinstance(api_keys, list) else 0
    states = [State.OK]
    if owners == 0:
        states.append(_configured_state(params, "no_owner", State.CRIT))
    if service_account_count == 0:
        states.append(_configured_state(params, "no_service_accounts", State.OK))
    if api_key_count == 0:
        states.append(_configured_state(params, "no_api_keys", State.OK))
    yield Result(
        state=_worst_state(states),
        summary=(
            f"Users: {len(users)} ({owners} owners), service accounts: {service_account_count}, "
            f"API keys: {api_key_count}"
        ),
        details=(
            "Counts are current project access inventory and are not compared with fixed expected totals."
        ),
    )


check_plugin_openai_platform_project_access = CheckPlugin(
    name="openai_platform_project_access",
    sections=["openai_platform"],
    service_name="OpenAI Project %s Access",
    discovery_function=discover_project_access,
    discovery_default_parameters=_PROJECT_DISCOVERY_DEFAULTS,
    discovery_ruleset_name="openai_platform_project_services",
    check_function=check_project_access,
    check_default_parameters=_PROJECT_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_project_policy",
)


def discover_project_costs(params: Mapping[str, Any], section: Section) -> DiscoveryResult:
    if params.get("costs", True):
        yield from _discover_projects(section)


def check_project_costs(item: str, params: Mapping[str, Any], section: Section) -> CheckResult:
    project = _project_by_name(section, item)
    if project is None:
        return
    yield from _check_costs(_nested_params(params, "costs"), section, str(project.get("id", "")))


check_plugin_openai_platform_project_costs = CheckPlugin(
    name="openai_platform_project_costs",
    sections=["openai_platform"],
    service_name="OpenAI Project %s Costs",
    discovery_function=discover_project_costs,
    discovery_default_parameters=_PROJECT_DISCOVERY_DEFAULTS,
    discovery_ruleset_name="openai_platform_project_services",
    check_function=check_project_costs,
    check_default_parameters=_PROJECT_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_project_policy",
)


def discover_project_usage(params: Mapping[str, Any], section: Section) -> DiscoveryResult:
    if params.get("usage", True):
        yield from _discover_projects(section)


def check_project_usage(item: str, params: Mapping[str, Any], section: Section) -> CheckResult:
    project = _project_by_name(section, item)
    if project is None:
        return
    yield from _check_usage(_nested_params(params, "usage"), section, project_id=str(project.get("id", "")))


check_plugin_openai_platform_project_usage = CheckPlugin(
    name="openai_platform_project_usage",
    sections=["openai_platform"],
    service_name="OpenAI Project %s Usage",
    discovery_function=discover_project_usage,
    discovery_default_parameters=_PROJECT_DISCOVERY_DEFAULTS,
    discovery_ruleset_name="openai_platform_project_services",
    check_function=check_project_usage,
    check_default_parameters=_PROJECT_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_project_policy",
)


def _used_models_for_project(section: Section, project_id: str) -> set[str]:
    models: set[str] = set()
    for category in CATEGORY_LABELS:
        for row in _flatten_buckets(_usage(section).get(category, [])):
            if str(row.get("project_id") or "") != project_id:
                continue
            model = row.get("model")
            if model and _category_active(_category_stats(section, category, project_id=project_id, model=str(model))):
                models.add(str(model))
    return models


def discover_project_rate_limits(params: Mapping[str, Any], section: Section) -> DiscoveryResult:
    if params.get("rate_limits", True):
        yield from _discover_projects(section)


def check_project_rate_limits(item: str, params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "rate_limits")
    project = _project_by_name(section, item)
    if project is None:
        return
    limits = project.get("rate_limits", [])
    limits = [r for r in limits if isinstance(r, dict)] if isinstance(limits, list) else []
    used = _used_models_for_project(section, str(project.get("id", "")))
    limit_models = {str(r.get("model", "")) for r in limits if r.get("model")}
    active_rows = [r for r in limits if str(r.get("model", "")) in used]
    missing = sorted(used - limit_models)
    details: list[str] = [
        "Rate-limit record counts are provider inventory and can change as OpenAI changes model "
        "availability or limit records; no fixed expected count is used."
    ]
    for row in sorted(active_rows, key=lambda r: str(r.get("model", ""))):
        model = str(row.get("model", "unknown"))
        rpm = int(row.get("max_requests_per_1_minute") or 0)
        tpm = int(row.get("max_tokens_per_1_minute") or 0)
        batch = int(row.get("batch_1_day_max_input_tokens") or 0)
        line = f"{model}: RPM {rpm:,} / TPM {tpm:,}"
        if batch:
            line += f", batch/day {batch:,} tokens"
        details.append(line)
    if missing:
        details.append("Used models without matching limit records: " + ", ".join(missing))
    elif not limits and not used:
        details.append("No rate-limit records returned, and no model usage was observed in the configured usage window.")
    states = [State.OK]
    if not limits:
        states.append(_configured_state(params, "no_records", State.OK))
    if missing:
        states.append(_configured_state(params, "used_model_without_limit", State.WARN))
    summary = (
        f"Rate-limit records: {len(limits)}, used models with matching limits: {len(active_rows)}"
    )
    if missing:
        summary += f", used models without matching limits: {len(missing)}"
    yield Result(state=_worst_state(states), summary=summary, details="\n".join(details))


check_plugin_openai_platform_project_rate_limits = CheckPlugin(
    name="openai_platform_project_rate_limits",
    sections=["openai_platform"],
    service_name="OpenAI Project %s Rate Limits",
    discovery_function=discover_project_rate_limits,
    discovery_default_parameters=_PROJECT_DISCOVERY_DEFAULTS,
    discovery_ruleset_name="openai_platform_project_services",
    check_function=check_project_rate_limits,
    check_default_parameters=_PROJECT_POLICY_DEFAULTS,
    check_ruleset_name="openai_platform_project_policy",
)


def _model_items(section: Section) -> list[tuple[str, str, str]]:
    project_names = {str(p.get("id")): str(p.get("name", p.get("id"))) for p in _projects(section)}
    found: set[tuple[str, str, str]] = set()
    for category in CATEGORY_LABELS:
        for row in _flatten_buckets(_usage(section).get(category, [])):
            project_id = str(row.get("project_id") or "")
            model = str(row.get("model") or "")
            if not project_id or not model:
                continue
            stats = _category_stats(section, category, project_id=project_id, model=model)
            if _category_active(stats):
                found.add((project_id, project_names.get(project_id, project_id), model))
    return sorted(found, key=lambda x: (x[1].lower(), x[2].lower()))


def discover_model_usage(params: Mapping[str, Any], section: Section) -> DiscoveryResult:
    if not params.get("model_usage", True):
        return
    for _project_id, project_name, model in _model_items(section):
        yield Service(item=f"{project_name}/{model}")


def check_model_usage(item: str, section: Section) -> CheckResult:
    match = next(
        ((pid, pname, model) for pid, pname, model in _model_items(section) if f"{pname}/{model}" == item),
        None,
    )
    if match is None:
        return
    project_id, _project_name, model = match
    yield from _check_usage(_USAGE_DEFAULTS, section, project_id=project_id, model=model)


check_plugin_openai_platform_model_usage = CheckPlugin(
    name="openai_platform_model_usage",
    sections=["openai_platform"],
    service_name="OpenAI Model %s Usage",
    discovery_function=discover_model_usage,
    discovery_default_parameters=_PROJECT_DISCOVERY_DEFAULTS,
    discovery_ruleset_name="openai_platform_project_services",
    check_function=check_model_usage,
)
