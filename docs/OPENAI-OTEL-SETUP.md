# OpenAI OpenTelemetry setup for Checkmk 2.5

This helper configures curated OpenAI runtime services using Checkmk's **Metric backend (custom query)** rule.

## Requirements

- Checkmk 2.5 **Ultimate** (native OpenTelemetry / metric backend)
- An OpenTelemetry-instrumented OpenAI application exporting OTLP metrics to Checkmk
- `curl`, `jq`, and `python3`
- A Checkmk API automation user allowed to create/update rules

The OpenTelemetry exporter must use **DELTA** metric temporality:

```bash
export OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=DELTA
```

This was required for the Checkmk 2.5 generic OTel metric services to consume the GenAI histogram metrics correctly.

## Configure the Checkmk rule

```bash
export API_URL="https://checkmk.example/mysite/check_mk/api/v1"
export CMK_USER="automation"
export CMK_SECRET="..."

# Checkmk host on which the curated runtime services should appear
export CMK_HOST="openai-platform"

# OTel resource attribute service.name emitted by the application
export OTEL_SERVICE_NAME="my-openai-app"

# Optional; defaults shown
export LOOKBACK_SECONDS=120
export HISTOGRAM_PERCENTILE=95

# Optional: activate Checkmk changes automatically
export ACTIVATE_CHANGES=1
export CMK_SITE="mysite"

./setup-openai-otel.sh
```

The helper creates or updates these services:

- OpenAI Runtime Latency
- OpenAI Runtime Chat Input Tokens
- OpenAI Runtime Output Tokens
- OpenAI Runtime Time To First Chunk
- OpenAI Runtime Output Chunk Time
- OpenAI Runtime Embedding Input Tokens

All queries are filtered to:

- `service.name = $OTEL_SERVICE_NAME`
- `gen_ai.provider.name = openai`
- the relevant `gen_ai.operation.name`
- `gen_ai.token.type` where applicable

## Existing manually-created rule

The script automatically adopts a single matching OpenAI runtime custom-query rule on `CMK_HOST`. If more than one matching rule exists, select one explicitly:

```bash
export CMK_RULE_ID="<rule-id>"
./setup-openai-otel.sh
```

## Idempotency

Running the helper repeatedly is safe. If the rule already matches the requested configuration, it makes no change and skips activation.

## Checkmk 2.5 no-data behavior

The custom-query services are traffic-dependent. If no matching datapoint exists within `LOOKBACK_SECONDS`, Checkmk 2.5 can report the service as `UNKNOWN - Item not found in monitoring data` and later mark it vanished.

For event-driven GenAI metrics, this can simply mean that no OpenAI request occurred during the lookback window. You could also use the enforce check for custom queries if the custom queries needs to be persistent. It is not an OpenTelemetry ingestion failure.

A larger lookback reduces churn but also makes displayed values older. Choose the lookback according to application traffic patterns.
