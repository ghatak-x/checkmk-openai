#!/usr/bin/env python3
# Copyright (C) 2026 Sudhir Chauhan
# License: GNU General Public License v2
# SPDX-License-Identifier: GPL-2.0-only

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
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


def parse_openai_statuspage(string_table: StringTable) -> Section:
    if not string_table:
        return {}
    raw = "".join("".join(row) for row in string_table)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


agent_section_openai_statuspage = AgentSection(
    name="openai_statuspage",
    parse_function=parse_openai_statuspage,
)


def _components(section: Section) -> list[dict[str, Any]]:
    rows = section.get("components", [])
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _endpoint_rows(section: Section) -> list[dict[str, Any]]:
    rows = section.get("endpoints", [])
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _config(section: Section) -> Mapping[str, Any]:
    cfg = section.get("configuration", {})
    return cfg if isinstance(cfg, dict) else {}


def _component_state(status: str) -> State:
    return {
        "operational": State.OK,
        "degraded_performance": State.WARN,
        "partial_outage": State.CRIT,
        "major_outage": State.CRIT,
        "under_maintenance": State.OK,
    }.get(status.lower(), State.UNKNOWN)


def _overview_state(indicator: str) -> State:
    return {
        "none": State.OK,
        "operational": State.OK,
        "minor": State.WARN,
        "major": State.CRIT,
        "critical": State.CRIT,
    }.get(indicator.lower(), State.UNKNOWN)


STATUS_URL = "https://status.openai.com/"

_STATE_BY_NAME = {
    "ok": State.OK,
    "warn": State.WARN,
    "crit": State.CRIT,
    "unknown": State.UNKNOWN,
}

_STATE_RANK = {
    State.OK: 0,
    State.WARN: 1,
    State.UNKNOWN: 2,
    State.CRIT: 3,
}

_STATUS_POLICY_DEFAULTS = {
    "overview": {"minor": "warn", "major": "crit", "critical": "crit", "unknown": "unknown"},
    "api": {"required_failure": "crit", "optional_failure": "warn", "optional_not_exposed": "ok"},
    "components": {
        "degraded_performance": "warn",
        "partial_outage": "crit",
        "major_outage": "crit",
        "under_maintenance": "ok",
        "unknown": "unknown",
    },
    "incidents": {"none": "warn", "minor": "warn", "major": "crit", "critical": "crit", "unknown": "warn"},
    "maintenance": {"active": "warn", "upcoming": "ok"},
    "integrity": {"observation": "warn"},
}
_STATUS_DETAIL_DEFAULTS = {
    "api": {"required_failure": "crit", "optional_failure": "warn", "optional_not_exposed": "ok"},
    "components": {
        "degraded_performance": "warn",
        "partial_outage": "crit",
        "major_outage": "crit",
        "under_maintenance": "ok",
        "unknown": "unknown",
    },
}


def _nested_params(params: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = params.get(key)
    return value if isinstance(value, Mapping) else params


def _configured_state(params: Mapping[str, Any], key: str, default: State) -> State:
    return _STATE_BY_NAME.get(str(params.get(key, "")).lower(), default)


def _worst_state(states: list[State]) -> State:
    return max(states, key=lambda state: _STATE_RANK[state], default=State.OK)


def _status_url(section: Section) -> str:
    value = section.get("base_url")
    if isinstance(value, str) and value:
        return value.rstrip("/") + "/"
    return STATUS_URL


def discover_overview(section: Section) -> DiscoveryResult:
    yield Service()


def check_overview(params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "overview")
    overview = section.get("overview", {})
    if not isinstance(overview, dict):
        overview = {}
    indicator = str(overview.get("indicator", "unknown")).lower()
    description = str(overview.get("description", "Unknown"))
    default_state = _overview_state(indicator)
    state = (
        State.OK
        if indicator in {"none", "operational"}
        else _configured_state(
            params,
            indicator if indicator in {"minor", "major", "critical"} else "unknown",
            default_state,
        )
    )
    url = _status_url(section)
    yield Result(
        state=state,
        summary=f"{description} | {url}",
        details=(
            "This is OpenAI's provider-wide status indicator. Component counts are reported by "
            "the separate 'OpenAI Status Components' service.\n"
            f"Live provider status: {url}"
        ),
    )


check_plugin_openai_statuspage_overview = CheckPlugin(
    name="openai_statuspage_overview",
    sections=["openai_statuspage"],
    service_name="OpenAI Status Overview",
    discovery_function=discover_overview,
    check_function=check_overview,
    check_default_parameters=_STATUS_POLICY_DEFAULTS,
    check_ruleset_name="openai_status_policy",
)


def discover_api(section: Section) -> DiscoveryResult:
    yield Service()


def check_api(params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "api")
    required_ok = 0
    required_total = 0
    optional_unavailable = 0
    required_failures: list[str] = []
    optional_failures: list[str] = []
    detail_lines: list[str] = []
    max_response = 0.0

    for endpoint in _endpoint_rows(section):
        label = str(endpoint.get("label", endpoint.get("name", "Endpoint")))
        optional = bool(endpoint.get("optional", False))
        status = endpoint.get("http_status")
        error = endpoint.get("error")
        response_time = float(endpoint.get("response_time") or 0.0)
        endpoint_url = str(endpoint.get("url") or "")
        max_response = max(max_response, response_time)
        if optional:
            if status == 404:
                optional_unavailable += 1
                rendered = "HTTP 404 - optional/not exposed"
            elif status == 200 and not error:
                rendered = f"HTTP 200 - {response_time:.2f} s"
            else:
                optional_failures.append(label)
                rendered = f"HTTP {status if status is not None else '-'} - {error or 'failed'}"
        else:
            required_total += 1
            if status == 200 and not error:
                required_ok += 1
                rendered = f"HTTP 200 - {response_time:.2f} s"
            else:
                required_failures.append(label)
                rendered = f"HTTP {status if status is not None else '-'} - {error or 'failed'}"
        if endpoint_url:
            rendered += f" - {endpoint_url}"
        detail_lines.append(f"{label}: {rendered}")

    detail_lines.append(
        "Required endpoints are the collector's core inputs (summary, components and incidents). "
        "Optional Statuspage-compatible routes may legitimately be absent on OpenAI's backend."
    )
    if max_response:
        detail_lines.append(f"Maximum response time: {max_response:.2f} s")
    if required_failures:
        state = _configured_state(params, "required_failure", State.CRIT)
        summary = f"Required Status API endpoint failure: {', '.join(required_failures)}"
    elif optional_failures:
        state = _configured_state(params, "optional_failure", State.WARN)
        summary = f"Optional Status API endpoint failures: {len(optional_failures)}"
    elif optional_unavailable:
        state = _configured_state(params, "optional_not_exposed", State.OK)
        summary = (
            f"All required Status API endpoints reachable; {optional_unavailable} optional route(s) "
            f"not exposed"
        )
    else:
        state = State.OK
        summary = "All required and optional Status API endpoints reachable"

    yield Result(state=state, summary=summary, details="\n".join(detail_lines))
    yield Metric("openai_status_api_max_response_time", max_response)
    yield Metric("openai_status_api_required_endpoints", required_total)
    yield Metric("openai_status_api_required_endpoints_ok", required_ok)


check_plugin_openai_statuspage_api = CheckPlugin(
    name="openai_statuspage_api",
    sections=["openai_statuspage"],
    service_name="OpenAI Status API",
    discovery_function=discover_api,
    check_function=check_api,
    check_default_parameters=_STATUS_POLICY_DEFAULTS,
    check_ruleset_name="openai_status_policy",
)


def discover_endpoint(section: Section) -> DiscoveryResult:
    if not _config(section).get("individual_endpoint_services", False):
        return
    for endpoint in _endpoint_rows(section):
        yield Service(item=str(endpoint.get("label", endpoint.get("name", "Endpoint"))))


def check_endpoint(item: str, params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "api")
    endpoint = next(
        (
            row
            for row in _endpoint_rows(section)
            if str(row.get("label", row.get("name", "Endpoint"))) == item
        ),
        None,
    )
    if endpoint is None:
        return
    optional = bool(endpoint.get("optional", False))
    status = endpoint.get("http_status")
    error = endpoint.get("error")
    response_time = float(endpoint.get("response_time") or 0.0)
    endpoint_url = str(endpoint.get("url") or "")
    suffix = f" | {endpoint_url}" if endpoint_url else ""
    if optional and status == 404:
        yield Result(
            state=_configured_state(params, "optional_not_exposed", State.OK),
            summary=f"Optional endpoint is not exposed (HTTP 404){suffix}",
        )
    elif status == 200 and not error:
        yield Result(state=State.OK, summary=f"HTTP 200, response time: {response_time:.2f} s{suffix}")
    else:
        key = "optional_failure" if optional else "required_failure"
        default = State.WARN if optional else State.CRIT
        yield Result(
            state=_configured_state(params, key, default),
            summary=f"HTTP {status if status is not None else '-'} - {error or 'request failed'}{suffix}",
        )


check_plugin_openai_statuspage_endpoint = CheckPlugin(
    name="openai_statuspage_endpoint",
    sections=["openai_statuspage"],
    service_name="OpenAI Status API %s",
    discovery_function=discover_endpoint,
    check_function=check_endpoint,
    check_default_parameters=_STATUS_DETAIL_DEFAULTS,
    check_ruleset_name="openai_status_detail_policy",
)


def discover_components(section: Section) -> DiscoveryResult:
    yield Service()


def check_components(params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "components")
    components = _components(section)
    counts = Counter(str(c.get("status", "unknown")) for c in components)
    operational = counts.get("operational", 0)
    degraded = counts.get("degraded_performance", 0)
    partial = counts.get("partial_outage", 0)
    major = counts.get("major_outage", 0)
    maintenance = counts.get("under_maintenance", 0)
    outage = partial + major
    unknown = len(components) - operational - degraded - outage - maintenance

    states: list[State] = [State.OK]
    if degraded:
        states.append(_configured_state(params, "degraded_performance", State.WARN))
    if partial:
        states.append(_configured_state(params, "partial_outage", State.CRIT))
    if major:
        states.append(_configured_state(params, "major_outage", State.CRIT))
    if maintenance:
        states.append(_configured_state(params, "under_maintenance", State.OK))
    if unknown:
        states.append(_configured_state(params, "unknown", State.UNKNOWN))
    state = _worst_state(states)

    details = [
        "The total is the live component inventory returned by OpenAI's Status API. "
        "It is provider-controlled: components may be added, renamed or retired, so no fixed "
        "expected component count is used for alerting.",
        "Current component inventory:",
    ]
    for component in sorted(
        components,
        key=lambda row: str(row.get("service_item") or row.get("name") or "").lower(),
    ):
        name = str(component.get("service_item") or component.get("name") or "Unknown")
        component_status = str(component.get("status", "unknown"))
        details.append(f"  {name}: {component_status}")
    status_url = _status_url(section)
    details.append(f"Live component status: {status_url}")

    summary = (
        f"Provider components: {len(components)} total ({operational} operational, "
        f"{degraded} degraded, {outage} outage"
    )
    if maintenance:
        summary += f", {maintenance} maintenance"
    if unknown:
        summary += f", {unknown} unknown"
    summary += f") | {status_url}"
    yield Result(state=state, summary=summary, details="\n".join(details))
    yield Metric("openai_status_components_total", len(components))
    yield Metric("openai_status_components_operational", operational)
    yield Metric("openai_status_components_degraded", degraded)
    yield Metric("openai_status_components_outage", outage)
    yield Metric("openai_status_components_maintenance", maintenance)
    yield Metric("openai_status_components_unknown", unknown)


check_plugin_openai_statuspage_components = CheckPlugin(
    name="openai_statuspage_components",
    sections=["openai_statuspage"],
    service_name="OpenAI Status Components",
    discovery_function=discover_components,
    check_function=check_components,
    check_default_parameters=_STATUS_POLICY_DEFAULTS,
    check_ruleset_name="openai_status_policy",
)


def _selected_component(component: Mapping[str, Any], cfg: Mapping[str, Any]) -> bool:
    mode = str(cfg.get("component_services", "aggregate_only"))
    if mode == "all":
        return True
    if mode != "selected":
        return False
    selected = cfg.get("selected_components", [])
    if not isinstance(selected, list):
        return False
    return str(component.get("name", "")) in {str(x) for x in selected}


def discover_component(section: Section) -> DiscoveryResult:
    cfg = _config(section)
    for component in _components(section):
        if _selected_component(component, cfg):
            yield Service(item=str(component.get("service_item") or component.get("name") or "Unknown"))


def check_component(item: str, params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "components")
    component = next(
        (
            row
            for row in _components(section)
            if str(row.get("service_item") or row.get("name") or "Unknown") == item
        ),
        None,
    )
    if component is None:
        return
    status = str(component.get("status", "unknown")).lower()
    default_state = _component_state(status)
    state = State.OK if status == "operational" else _configured_state(params, status, default_state)
    details = []
    if component.get("description"):
        details.append(f"Description: {component['description']}")
    if component.get("id"):
        details.append(f"Component ID: {component['id']}")
    if component.get("updated_at"):
        details.append(f"Updated: {component['updated_at']}")
    status_url = _status_url(section)
    details.append(f"Live component status: {status_url}")
    yield Result(
        state=state,
        summary=f"Status: {status} | {status_url}",
        details="\n".join(details),
    )


check_plugin_openai_statuspage_component = CheckPlugin(
    name="openai_statuspage_component",
    sections=["openai_statuspage"],
    service_name="OpenAI Status Component %s",
    discovery_function=discover_component,
    check_function=check_component,
    check_default_parameters=_STATUS_DETAIL_DEFAULTS,
    check_ruleset_name="openai_status_detail_policy",
)


def discover_incidents(section: Section) -> DiscoveryResult:
    yield Service()


def check_incidents(params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "incidents")
    incidents = section.get("incidents", [])
    if not isinstance(incidents, list):
        incidents = []
    unresolved_ids = section.get("unresolved_incident_ids", [])
    unresolved_set = {str(x) for x in unresolved_ids} if isinstance(unresolved_ids, list) else set()
    unresolved = [i for i in incidents if isinstance(i, dict) and str(i.get("id", "")) in unresolved_set]

    states = [State.OK]
    for incident in unresolved:
        impact = str(incident.get("impact", "unknown")).lower()
        key = impact if impact in {"none", "minor", "major", "critical"} else "unknown"
        default = State.CRIT if key in {"major", "critical"} else State.WARN
        states.append(_configured_state(params, key, default))
    state = _worst_state(states)

    details: list[str] = [
        "The incident-record count is the number currently returned by OpenAI's incidents API; "
        "it is not a fixed baseline and may change as the provider's incident history changes."
    ]
    for incident in unresolved:
        title = str(incident.get("name", "Unnamed incident"))
        status = str(incident.get("status", "unknown"))
        impact = str(incident.get("impact", "none"))
        details.append(f"{title}: {status} ({impact})")
        affected = incident.get("affected_components", [])
        if isinstance(affected, list) and affected:
            details.append(f"  Affected components: {', '.join(str(x) for x in affected)}")
        if incident.get("started_at"):
            details.append(f"  Started: {incident['started_at']}")
        if incident.get("latest_update_at"):
            details.append(f"  Latest update: {incident['latest_update_at']}")
        if incident.get("latest_update"):
            details.append(f"  {incident['latest_update']}")
        if incident.get("url"):
            details.append(f"  URL: {incident['url']}")

    if unresolved and not any(incident.get("url") for incident in unresolved):
        details.append(f"OpenAI status: {_status_url(section)}")
    if unresolved:
        summary = f"{len(unresolved)} unresolved incident(s); {len(incidents)} incident record(s) returned"
    else:
        summary = f"No unresolved incidents; {len(incidents)} incident record(s) returned"
    yield Result(state=state, summary=summary, details="\n".join(details))
    yield Metric("openai_status_recent_incidents", len(incidents))
    yield Metric("openai_status_unresolved_incidents", len(unresolved))


check_plugin_openai_statuspage_incidents = CheckPlugin(
    name="openai_statuspage_incidents",
    sections=["openai_statuspage"],
    service_name="OpenAI Status Incidents",
    discovery_function=discover_incidents,
    check_function=check_incidents,
    check_default_parameters=_STATUS_POLICY_DEFAULTS,
    check_ruleset_name="openai_status_policy",
)


def discover_maintenance(section: Section) -> DiscoveryResult:
    yield Service()


def check_maintenance(params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "maintenance")
    maintenance = section.get("maintenance", {})
    if not isinstance(maintenance, dict):
        maintenance = {}
    active = maintenance.get("active", [])
    upcoming = maintenance.get("upcoming", [])
    active = active if isinstance(active, list) else []
    upcoming = upcoming if isinstance(upcoming, list) else []
    details: list[str] = [
        "Counts reflect maintenance records returned by the provider. The inventory is dynamic and "
        "is not compared with a fixed expected number."
    ]
    for row in active:
        if isinstance(row, dict):
            details.append(f"Active: {row.get('name')} ({row.get('status')})")
    for row in upcoming[:10]:
        if isinstance(row, dict):
            details.append(
                f"Upcoming: {row.get('name')} - {row.get('scheduled_for') or 'time unavailable'}"
            )
    states = [State.OK]
    if active:
        states.append(_configured_state(params, "active", State.WARN))
    if upcoming:
        states.append(_configured_state(params, "upcoming", State.OK))
    state = _worst_state(states)
    summary = f"{len(active)} active, {len(upcoming)} upcoming maintenance window(s)"
    if active or upcoming:
        status_url = _status_url(section)
        details.append(f"OpenAI status: {status_url}")
        summary += f" | {status_url}"
    yield Result(state=state, summary=summary, details="\n".join(details))
    yield Metric("openai_status_maintenance_active", len(active))
    yield Metric("openai_status_maintenance_upcoming", len(upcoming))


check_plugin_openai_statuspage_maintenance = CheckPlugin(
    name="openai_statuspage_maintenance",
    sections=["openai_statuspage"],
    service_name="OpenAI Status Maintenance",
    discovery_function=discover_maintenance,
    check_function=check_maintenance,
    check_default_parameters=_STATUS_POLICY_DEFAULTS,
    check_ruleset_name="openai_status_policy",
)


def discover_integrity(section: Section) -> DiscoveryResult:
    yield Service()


def check_integrity(params: Mapping[str, Any], section: Section) -> CheckResult:
    params = _nested_params(params, "integrity")
    observations = section.get("integrity_observations", [])
    if not isinstance(observations, list):
        observations = []
    clean = [str(x) for x in observations if str(x)]
    if clean:
        yield Result(
            state=_configured_state(params, "observation", State.WARN),
            summary=f"{len(clean)} validated Status API integrity conflict(s)",
            details=(
                "Only conflicting records for the same stable component ID or malformed required "
                "records are considered integrity conflicts. Duplicate display names and endpoint "
                "membership differences are intentionally ignored.\n"
                + "\n".join(clean)
            ),
        )
    else:
        yield Result(
            state=State.OK,
            summary="Status API sources are internally consistent",
            details=(
                "Checks stable component IDs and required fields across the Status API sources. "
                "Duplicate component display names and differing endpoint membership are valid and "
                "do not produce warnings."
            ),
        )


check_plugin_openai_statuspage_integrity = CheckPlugin(
    name="openai_statuspage_integrity",
    sections=["openai_statuspage"],
    service_name="OpenAI Status Data Integrity",
    discovery_function=discover_integrity,
    check_function=check_integrity,
    check_default_parameters=_STATUS_POLICY_DEFAULTS,
    check_ruleset_name="openai_status_policy",
)
