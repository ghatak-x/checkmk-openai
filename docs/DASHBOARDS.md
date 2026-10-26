# OpenAI dashboards

The package includes two packaged Checkmk dashboard definitions under `local/lib/python3/cmk/gui/plugins/dashboard/`.

- `openai` — core status and Platform monitoring.
- `openai_otel` — core dashboard plus OpenTelemetry runtime services.

Both dashboards use a mandatory runtime host filter rather than hard-coding a host name.

The OpenTelemetry dashboard expects the custom-query services created by `examples/otel/setup-openai-otel.sh`.

The dashboard export contains the originating site's visibility scope (`testingsite`) because Checkmk requires at least one site in that GUI setting. On another site/distributed installation, adjust the dashboard visibility/access scope after installation if necessary.

## Platform layout

The provider-health row includes aggregate Status Components and Status API services. The Platform section now surfaces dynamic project attribution with `Project Cost Breakdown`, `Cost Allocation`, and `Usage Allocation`. Organization/project overview and access services remain monitored and are still visible through the Problems view when non-OK.

The dashboards intentionally do not assume a fixed number of OpenAI components, projects, users, API keys, rate-limit records, or project cost/usage shares.

## Presentation

`Project Cost Breakdown` and `Rate Limits` use the concise Checkmk service summary in the packaged dashboards. Drill into the service when the full details are needed.

## Platform usage efficiency and attribution

The packaged dashboards include organization-level **Prompt Cache** and **Caller / API Key Attribution** summary widgets. Detailed project/model cache statistics and ranked API-key/owner attribution remain available on the service detail pages; unresolved provider user IDs are diagnostic metadata on the same events and are not additional usage.
