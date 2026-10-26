# Checkmk OpenAI Monitoring

Checkmk extension for monitoring OpenAI at three layers:

1. **Public status** — provider status, incidents, maintenance, components and API integrity.
2. **OpenAI Platform** — organization/projects, access, usage, costs and rate limits using an Admin API key.
3. **OpenTelemetry runtime metrics (optional)** — application-observed latency, streaming and token metrics. Native OpenTelemetry ingestion in Checkmk 2.5 is edition-gated; use only on an eligible Ultimate-tier deployment.

## Requirements

- Checkmk 2.5.0 or newer
- Python `requests` as provided by the Checkmk site
- For authenticated Platform monitoring: OpenAI organization Admin API key
- Optional project/service-account API key for project API validation

## Installation

Install `openai-0.0.1.mkp` with the Checkmk extension package mechanism, then enable/configure either or both special agents:

- **OpenAI public status**
- **OpenAI Platform**

The public-status defaults intentionally stay concise:

- OpenAI Status Overview
- OpenAI Status API
- OpenAI Status Incidents
- OpenAI Status Maintenance
- OpenAI Status Components
- OpenAI Status Data Integrity

Individual status API endpoints and individual components can be enabled in the special-agent rule when desired. Upgrading from a version that discovered them individually will cause those old services to appear as vanished once; accept the vanished services after verifying the new aggregate services are present.

All primary OpenAI checks include Checkmk check-manual pages explaining what their counts mean, whether the values are dynamic, and the relevant OpenAI status/API/help URL. Service output only includes a clickable URL when it is operationally useful (for example the provider status/component view, a concrete Status API endpoint, or an active incident/maintenance context). Routine Platform inventory/usage/cost checks keep the summary concise. Service monitoring configuration is consolidated into four shared policy rules: OpenAI Platform organization policy, OpenAI Platform project policy, OpenAI public status policy, and OpenAI public status detail policy. Automatic enforced-service duplicates are intentionally disabled because these services are discovered from provider data; this keeps Setup concise while retaining configurable state/threshold behavior. Inventory totals such as component/project/user/rate-limit counts are deliberately not compared with hard-coded expected numbers.


Project-level services are controlled separately by the **OpenAI Platform project service discovery** rule. This keeps collection and service discovery separate: the special agent still collects project dimensions needed for allocation, while Checkmk decides which per-project service families to create.

The organization layer also includes **Cost Allocation** and **Usage Allocation** services. They dynamically rank projects and show the largest contributor/share without assuming a fixed project inventory.

It also includes **Prompt Cache** and optional **Caller/API-key Usage Attribution**:

- Prompt Cache reports cached/uncached input tokens and the token-level cache-read ratio for Completions/Responses, with project/model breakdowns in Details. Its token totals intentionally exclude other Usage API families, so they can be lower than Caller/API-key Attribution totals.
- Caller/API-key Usage Attribution ranks project API keys and their inventory owners (user or service account) by request/call activity for Usage API families that expose `api_key_id` and `user_id`. API-key ownership is the primary caller identity. Provider-reported `user_id` values are shown as human users only when they resolve to organization/project user inventory; unresolved IDs are diagnostic metadata on the same events and are not counted as additional usage. The Special Agent option is enabled by default and can be disabled if the additional grouping/cardinality is not desired. API key secrets are never collected.

## OpenAI Platform credentials

The Admin API key is used for `/v1/organization/...` endpoints. The optional project key can be a project service-account key and is used for project API validation such as `/v1/models`.

Secrets are passed through Checkmk's password-store reference mechanism; raw keys are not put on the special-agent command line.

## Dashboards

Two dashboard definitions are included:

- **OpenAI Monitoring** — provider/status/platform dashboard.
- **OpenAI Monitoring + OpenTelemetry** — adds runtime OTel charts.

Both dashboards require a runtime **Host** filter so the package is not tied to a particular OpenAI host name. The exported visibility contains the originating site name because Checkmk requires at least one site on the dashboard definition; adjust dashboard visibility after installation when deploying to another site/distributed setup.

## OpenTelemetry

See [`docs/OPENAI-OTEL-SETUP.md`](docs/OPENAI-OTEL-SETUP.md). The helper in `examples/otel/setup-openai-otel.sh` creates the six custom-query services through the Checkmk REST API.

For the tested Python OpenTelemetry instrumentation, export:

```bash
export OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=DELTA
```

Checkmk 2.5 custom-query services are traffic-dependent: if no event-driven datapoint exists inside the configured lookback, a discovered service can become `UNKNOWN - Item not found in monitoring data` and later appear as vanished. One could also create a enforced check if those custom services is supposed to be persistent.This is not an OpenAI telemetry failure.

## Security

The Platform collector sanitizes upstream HTTP errors at the collection boundary. It does not forward OpenAI `error.message` bodies into Checkmk, because those bodies can contain API-key fragments.

## License

GNU General Public License v2. See `LICENSE`.
