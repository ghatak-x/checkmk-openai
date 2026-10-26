#!/usr/bin/env python3
# Copyright (C) 2026 Sudhir Chauhan
# License: GNU General Public License v2
# SPDX-License-Identifier: GPL-2.0-only

from cmk.graphing.v1 import Title
from cmk.graphing.v1.metrics import Color, DecimalNotation, Metric, StrictPrecision, TimeNotation, Unit

metric_openai_platform_requests = Metric(
    name="openai_platform_requests",
    title=Title("OpenAI requests"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.BLUE,
)

metric_openai_platform_input_tokens = Metric(
    name="openai_platform_input_tokens",
    title=Title("OpenAI input tokens"),
    unit=Unit(DecimalNotation(" tokens"), StrictPrecision(0)),
    color=Color.CYAN,
)

metric_openai_platform_output_tokens = Metric(
    name="openai_platform_output_tokens",
    title=Title("OpenAI output tokens"),
    unit=Unit(DecimalNotation(" tokens"), StrictPrecision(0)),
    color=Color.PURPLE,
)

metric_openai_platform_api_response_time = Metric(
    name="openai_platform_api_response_time",
    title=Title("OpenAI API response time"),
    unit=Unit(TimeNotation()),
    color=Color.GREEN,
)

metric_openai_platform_cost_today_usd = Metric(
    name="openai_platform_cost_today_usd",
    title=Title("OpenAI cost today"),
    unit=Unit(DecimalNotation(" $"), StrictPrecision(4)),
    color=Color.ORANGE,
)

metric_openai_platform_cost_previous_day_usd = Metric(
    name="openai_platform_cost_previous_day_usd",
    title=Title("OpenAI cost previous day"),
    unit=Unit(DecimalNotation(" $"), StrictPrecision(4)),
    color=Color.YELLOW,
)

metric_openai_platform_cost_month_to_date_usd = Metric(
    name="openai_platform_cost_month_to_date_usd",
    title=Title("OpenAI cost month-to-date"),
    unit=Unit(DecimalNotation(" $"), StrictPrecision(4)),
    color=Color.BLUE,
)

metric_openai_platform_largest_project_cost_mtd_usd = Metric(
    name="openai_platform_largest_project_cost_mtd_usd",
    title=Title("Largest OpenAI project cost MTD"),
    unit=Unit(DecimalNotation(" $"), StrictPrecision(4)),
    color=Color.ORANGE,
)

metric_openai_platform_largest_project_cost_share_percent = Metric(
    name="openai_platform_largest_project_cost_share_percent",
    title=Title("Largest OpenAI project cost share"),
    unit=Unit(DecimalNotation(" %"), StrictPrecision(1)),
    color=Color.PURPLE,
)

metric_openai_platform_projects_with_spend = Metric(
    name="openai_platform_projects_with_spend",
    title=Title("OpenAI projects with spend"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.BLUE,
)

metric_openai_platform_unattributed_cost_mtd_usd = Metric(
    name="openai_platform_unattributed_cost_mtd_usd",
    title=Title("OpenAI unattributed cost MTD"),
    unit=Unit(DecimalNotation(" $"), StrictPrecision(4)),
    color=Color.YELLOW,
)

metric_openai_platform_unattributed_cost_share_percent = Metric(
    name="openai_platform_unattributed_cost_share_percent",
    title=Title("OpenAI unattributed cost share"),
    unit=Unit(DecimalNotation(" %"), StrictPrecision(1)),
    color=Color.YELLOW,
)

metric_openai_platform_all_requests = Metric(
    name="openai_platform_all_requests",
    title=Title("OpenAI request/call activity"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.BLUE,
)

metric_openai_platform_largest_project_requests = Metric(
    name="openai_platform_largest_project_requests",
    title=Title("Largest OpenAI project request/call activity"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.CYAN,
)

metric_openai_platform_largest_project_request_share_percent = Metric(
    name="openai_platform_largest_project_request_share_percent",
    title=Title("Largest OpenAI project request share"),
    unit=Unit(DecimalNotation(" %"), StrictPrecision(1)),
    color=Color.PURPLE,
)

metric_openai_platform_projects_with_activity = Metric(
    name="openai_platform_projects_with_activity",
    title=Title("OpenAI projects with activity"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.GREEN,
)

metric_openai_platform_projects_with_owner = Metric(
    name="openai_platform_projects_with_owner",
    title=Title("OpenAI projects with owner"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.GREEN,
)

metric_openai_platform_projects_with_service_accounts = Metric(
    name="openai_platform_projects_with_service_accounts",
    title=Title("OpenAI projects with service accounts"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.BLUE,
)

metric_openai_platform_projects_with_api_keys = Metric(
    name="openai_platform_projects_with_api_keys",
    title=Title("OpenAI projects with API keys"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.CYAN,
)


metric_openai_platform_cached_input_tokens = Metric(
    name="openai_platform_cached_input_tokens",
    title=Title("OpenAI cached input tokens"),
    unit=Unit(DecimalNotation(" tokens"), StrictPrecision(0)),
    color=Color.GREEN,
)

metric_openai_platform_uncached_input_tokens = Metric(
    name="openai_platform_uncached_input_tokens",
    title=Title("OpenAI uncached input tokens"),
    unit=Unit(DecimalNotation(" tokens"), StrictPrecision(0)),
    color=Color.ORANGE,
)

metric_openai_platform_prompt_cache_hit_percent = Metric(
    name="openai_platform_prompt_cache_hit_percent",
    title=Title("OpenAI prompt cache-read ratio"),
    unit=Unit(DecimalNotation(" %"), StrictPrecision(1)),
    color=Color.PURPLE,
)

metric_openai_platform_attributed_requests = Metric(
    name="openai_platform_attributed_requests",
    title=Title("OpenAI attributable requests/calls"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.BLUE,
)

metric_openai_platform_active_users = Metric(
    name="openai_platform_active_users",
    title=Title("OpenAI active resolved human users"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.GREEN,
)

metric_openai_platform_active_api_keys = Metric(
    name="openai_platform_active_api_keys",
    title=Title("OpenAI active attributed API keys"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.CYAN,
)

metric_openai_platform_largest_user_requests = Metric(
    name="openai_platform_largest_user_requests",
    title=Title("Largest OpenAI resolved-user request/call activity"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.BLUE,
)

metric_openai_platform_largest_user_request_share_percent = Metric(
    name="openai_platform_largest_user_request_share_percent",
    title=Title("Largest OpenAI resolved-user request share"),
    unit=Unit(DecimalNotation(" %"), StrictPrecision(1)),
    color=Color.PURPLE,
)

metric_openai_platform_largest_api_key_requests = Metric(
    name="openai_platform_largest_api_key_requests",
    title=Title("Largest OpenAI API-key request/call activity"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.BLUE,
)

metric_openai_platform_largest_api_key_request_share_percent = Metric(
    name="openai_platform_largest_api_key_request_share_percent",
    title=Title("Largest OpenAI API-key request share"),
    unit=Unit(DecimalNotation(" %"), StrictPrecision(1)),
    color=Color.PURPLE,
)

metric_openai_platform_unattributed_user_requests = Metric(
    name="openai_platform_unattributed_user_requests",
    title=Title("OpenAI events without resolved-user identity"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.YELLOW,
)

metric_openai_platform_unattributed_api_key_requests = Metric(
    name="openai_platform_unattributed_api_key_requests",
    title=Title("OpenAI requests/calls without API-key attribution"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.YELLOW,
)
