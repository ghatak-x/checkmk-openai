#!/usr/bin/env bash
set -euo pipefail

# Configure curated OpenAI runtime services in Checkmk 2.5 via
# "Metric backend (custom query)".
#
# Requirements:
#   - Checkmk 2.5 Ultimate (native OpenTelemetry / metric backend)
#   - curl, jq, python3
#   - An API automation user allowed to read/write rules
#   - OpenTelemetry exporter configured for DELTA metric temporality:
#       OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=DELTA
#
# Required environment variables:
#   API_URL           e.g. https://cmk.example/mysite/check_mk/api/v1
#   CMK_USER          Checkmk automation/API user
#   CMK_SECRET        automation secret
#   CMK_HOST          Checkmk host that should receive the curated services
#   OTEL_SERVICE_NAME OTel resource attribute service.name to query
#
# Optional environment variables:
#   LOOKBACK_SECONDS  default: 120
#   HISTOGRAM_PERCENTILE default: 95
#   CMK_RULE_ID       force update/adoption of this rule ID
#   ACTIVATE_CHANGES  0|1, default: 0
#   CMK_SITE          site to activate; derived from API_URL when possible
#   FORCE_FOREIGN_CHANGES false|true, default: false
#
# The script is idempotent. If CMK_RULE_ID is not supplied, it searches the
# custom-query ruleset for exactly one rule on CMK_HOST containing the six
# OpenAI Runtime service templates and adopts/updates it. Otherwise it creates
# a new rule.

RULESET='special_agents:custom_query_metric_backend'
LOOKBACK_SECONDS="${LOOKBACK_SECONDS:-120}"
HISTOGRAM_PERCENTILE="${HISTOGRAM_PERCENTILE:-95}"
ACTIVATE_CHANGES="${ACTIVATE_CHANGES:-0}"
FORCE_FOREIGN_CHANGES="${FORCE_FOREIGN_CHANGES:-false}"

required_vars=(API_URL CMK_USER CMK_SECRET CMK_HOST OTEL_SERVICE_NAME)
for var in "${required_vars[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        printf 'ERROR: required environment variable %s is not set\n' "$var" >&2
        exit 2
    fi
done

for cmd in curl jq python3; do
    command -v "$cmd" >/dev/null 2>&1 || {
        printf 'ERROR: required command not found: %s\n' "$cmd" >&2
        exit 2
    }
done

API_URL="${API_URL%/}"

if [[ ! "$LOOKBACK_SECONDS" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo 'ERROR: LOOKBACK_SECONDS must be numeric' >&2
    exit 2
fi
if [[ ! "$HISTOGRAM_PERCENTILE" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo 'ERROR: HISTOGRAM_PERCENTILE must be numeric' >&2
    exit 2
fi

AUTH_HEADER="Authorization: Bearer ${CMK_USER} ${CMK_SECRET}"

TMPDIR_CMK_OPENAI="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_CMK_OPENAI"' EXIT

http_json() {
    local method="$1"
    local url="$2"
    local data_file="${3:-}"
    local etag="${4:-}"
    local out="$5"
    local -a args=(
        -sS
        -X "$method"
        "$url"
        -H "$AUTH_HEADER"
        -H 'Accept: application/json'
        -o "$out"
        -w '%{http_code}'
    )
    if [[ -n "$data_file" ]]; then
        args+=( -H 'Content-Type: application/json' --data-binary "@$data_file" )
    fi
    if [[ -n "$etag" ]]; then
        args+=( -H "If-Match: $etag" )
    fi
    curl "${args[@]}"
}

show_error_and_exit() {
    local status="$1"
    local file="$2"
    printf 'ERROR: Checkmk REST API returned HTTP %s\n' "$status" >&2
    if jq -e . "$file" >/dev/null 2>&1; then
        jq . "$file" >&2
    else
        cat "$file" >&2
    fi
    exit 1
}

# Build value_raw as a Python literal. This mirrors the current Checkmk 2.5
# REST representation exported by the GUI and safely quotes user values.
VALUE_RAW="$({
    CMK_OPENAI_OTEL_SERVICE_NAME="$OTEL_SERVICE_NAME" \
    CMK_OPENAI_LOOKBACK="$LOOKBACK_SECONDS" \
    CMK_OPENAI_PERCENTILE="$HISTOGRAM_PERCENTILE" \
    python3 - <<'PY'
import os

service_name = os.environ["CMK_OPENAI_OTEL_SERVICE_NAME"]
lookback = float(os.environ["CMK_OPENAI_LOOKBACK"])
percentile = float(os.environ["CMK_OPENAI_PERCENTILE"])

resource = [{"key": "service.name", "value": service_name}]
provider = {"key": "gen_ai.provider.name", "value": "openai"}
chat = {"key": "gen_ai.operation.name", "value": "chat"}
embeddings = {"key": "gen_ai.operation.name", "value": "embeddings"}

queries = [
    {
        "metric_name": "gen_ai.client.operation.duration",
        "resource_attributes": resource,
        "scope_attributes": [],
        "data_point_attributes": [provider, chat],
        "aggregation_lookback": lookback,
        "aggregation_histogram_percentile": percentile,
        "service_name_template": "OpenAI Runtime Latency",
    },
    {
        "metric_name": "gen_ai.client.token.usage",
        "resource_attributes": resource,
        "scope_attributes": [],
        "data_point_attributes": [provider, {"key": "gen_ai.token.type", "value": "input"}, chat],
        "aggregation_lookback": lookback,
        "aggregation_histogram_percentile": percentile,
        "service_name_template": "OpenAI Runtime Chat Input Tokens",
    },
    {
        "metric_name": "gen_ai.client.token.usage",
        "resource_attributes": resource,
        "scope_attributes": [],
        "data_point_attributes": [provider, {"key": "gen_ai.token.type", "value": "output"}, chat],
        "aggregation_lookback": lookback,
        "aggregation_histogram_percentile": percentile,
        "service_name_template": "OpenAI Runtime Output Tokens",
    },
    {
        "metric_name": "gen_ai.client.operation.time_to_first_chunk",
        "resource_attributes": resource,
        "scope_attributes": [],
        "data_point_attributes": [provider, chat],
        "aggregation_lookback": lookback,
        "aggregation_histogram_percentile": percentile,
        "service_name_template": "OpenAI Runtime Time To First Chunk",
    },
    {
        "metric_name": "gen_ai.client.operation.time_per_output_chunk",
        "resource_attributes": resource,
        "scope_attributes": [],
        "data_point_attributes": [provider, chat],
        "aggregation_lookback": lookback,
        "aggregation_histogram_percentile": percentile,
        "service_name_template": "OpenAI Runtime Output Chunk Time",
    },
    {
        "metric_name": "gen_ai.client.token.usage",
        "resource_attributes": resource,
        "scope_attributes": [],
        "data_point_attributes": [provider, {"key": "gen_ai.token.type", "value": "input"}, embeddings],
        "aggregation_lookback": lookback,
        "aggregation_histogram_percentile": percentile,
        "service_name_template": "OpenAI Runtime Embedding Input Tokens",
    },
]

print(repr({"metric_backend_custom_query": queries}))
PY
})"

CONDITIONS_JSON="$(jq -cn --arg host "$CMK_HOST" '{
    host_name: {match_on: [$host], operator: "one_of"},
    host_tags: [],
    host_label_groups: [],
    service_label_groups: []
}')"

RULES_FILE="$TMPDIR_CMK_OPENAI/rules.json"
STATUS="$(curl -sS \
    "${API_URL}/domain-types/rule/collections/all?ruleset_name=special_agents%3Acustom_query_metric_backend" \
    -H "$AUTH_HEADER" \
    -H 'Accept: application/json' \
    -o "$RULES_FILE" \
    -w '%{http_code}')"
[[ "$STATUS" == "200" ]] || show_error_and_exit "$STATUS" "$RULES_FILE"

RULE_ID="${CMK_RULE_ID:-}"
if [[ -z "$RULE_ID" ]]; then
    mapfile -t MATCHING_RULE_IDS < <(
        jq -r --arg host "$CMK_HOST" '
          .value[]
          | select(.extensions.conditions.host_name.operator == "one_of")
          | select((.extensions.conditions.host_name.match_on // []) | index($host))
          | select(.extensions.value_raw | contains("OpenAI Runtime Latency"))
          | select(.extensions.value_raw | contains("OpenAI Runtime Chat Input Tokens"))
          | select(.extensions.value_raw | contains("OpenAI Runtime Output Tokens"))
          | select(.extensions.value_raw | contains("OpenAI Runtime Time To First Chunk"))
          | select(.extensions.value_raw | contains("OpenAI Runtime Output Chunk Time"))
          | select(.extensions.value_raw | contains("OpenAI Runtime Embedding Input Tokens"))
          | .id
        ' "$RULES_FILE"
    )

    if (( ${#MATCHING_RULE_IDS[@]} > 1 )); then
        echo 'ERROR: more than one matching OpenAI OTel custom-query rule found.' >&2
        echo 'Set CMK_RULE_ID explicitly to select the rule to manage.' >&2
        printf '  %s\n' "${MATCHING_RULE_IDS[@]}" >&2
        exit 1
    elif (( ${#MATCHING_RULE_IDS[@]} == 1 )); then
        RULE_ID="${MATCHING_RULE_IDS[0]}"
        printf 'Found existing OpenAI OTel rule: %s\n' "$RULE_ID"
    fi
fi

CHANGED=0

if [[ -n "$RULE_ID" ]]; then
    RULE_FILE="$TMPDIR_CMK_OPENAI/rule.json"
    RULE_HEADERS="$TMPDIR_CMK_OPENAI/rule.headers"
    STATUS="$(curl -sS -D "$RULE_HEADERS" \
        "${API_URL}/objects/rule/${RULE_ID}" \
        -H "$AUTH_HEADER" \
        -H 'Accept: application/json' \
        -o "$RULE_FILE" \
        -w '%{http_code}')"
    [[ "$STATUS" == "200" ]] || show_error_and_exit "$STATUS" "$RULE_FILE"

    CURRENT_VALUE_RAW="$(jq -r '.extensions.value_raw' "$RULE_FILE")"
    CURRENT_CONDITIONS="$(jq -c '.extensions.conditions' "$RULE_FILE")"
    CURRENT_DISABLED="$(jq -r '.extensions.properties.disabled // false' "$RULE_FILE")"

    if [[ "$CURRENT_VALUE_RAW" == "$VALUE_RAW" ]] \
       && [[ "$(jq -S -c . <<<"$CURRENT_CONDITIONS")" == "$(jq -S -c . <<<"$CONDITIONS_JSON")" ]] \
       && [[ "$CURRENT_DISABLED" == "false" ]]; then
        echo 'OpenAI OTel custom-query rule is already up to date.'
    else
        ETAG="$(awk 'tolower($1) == "etag:" {sub(/\r$/, "", $2); print $2; exit}' "$RULE_HEADERS")"
        if [[ -z "$ETAG" ]]; then
            echo 'ERROR: no ETag returned while reading existing rule.' >&2
            exit 1
        fi

        UPDATE_FILE="$TMPDIR_CMK_OPENAI/update.json"
        jq -n \
            --arg value_raw "$VALUE_RAW" \
            --argjson conditions "$CONDITIONS_JSON" \
            --slurpfile current "$RULE_FILE" \
            '{
                properties: (($current[0].extensions.properties // {}) + {disabled: false}),
                conditions: $conditions,
                value_raw: $value_raw
            }' > "$UPDATE_FILE"

        RESPONSE_FILE="$TMPDIR_CMK_OPENAI/update-response.json"
        STATUS="$(http_json PUT "${API_URL}/objects/rule/${RULE_ID}" "$UPDATE_FILE" "$ETAG" "$RESPONSE_FILE")"
        case "$STATUS" in
            200|201|204)
                echo "Updated OpenAI OTel custom-query rule: $RULE_ID"
                CHANGED=1
                ;;
            *) show_error_and_exit "$STATUS" "$RESPONSE_FILE" ;;
        esac
    fi
else
    CREATE_FILE="$TMPDIR_CMK_OPENAI/create.json"
    jq -n \
        --arg ruleset "$RULESET" \
        --arg value_raw "$VALUE_RAW" \
        --argjson conditions "$CONDITIONS_JSON" \
        '{
            ruleset: $ruleset,
            folder: "/",
            properties: {disabled: false},
            value_raw: $value_raw,
            conditions: $conditions
        }' > "$CREATE_FILE"

    RESPONSE_FILE="$TMPDIR_CMK_OPENAI/create-response.json"
    STATUS="$(http_json POST "${API_URL}/domain-types/rule/collections/all" "$CREATE_FILE" '' "$RESPONSE_FILE")"
    case "$STATUS" in
        200|201)
            RULE_ID="$(jq -r '.id // empty' "$RESPONSE_FILE")"
            echo "Created OpenAI OTel custom-query rule${RULE_ID:+: $RULE_ID}"
            CHANGED=1
            ;;
        *) show_error_and_exit "$STATUS" "$RESPONSE_FILE" ;;
    esac
fi

if [[ "$ACTIVATE_CHANGES" == "1" ]]; then
    if [[ "$CHANGED" == "0" ]]; then
        echo 'No rule change was required; activation skipped.'
    else
        CMK_SITE="${CMK_SITE:-}"
        if [[ -z "$CMK_SITE" ]]; then
            # Derive site from .../<site>/check_mk/api/v1
            CMK_SITE="$(sed -nE 's#^https?://[^/]+/([^/]+)/check_mk/api/v[0-9]+$#\1#p' <<<"$API_URL")"
        fi
        if [[ -z "$CMK_SITE" ]]; then
            echo 'ERROR: ACTIVATE_CHANGES=1 requires CMK_SITE when it cannot be derived from API_URL.' >&2
            exit 2
        fi

        PENDING_HEADERS="$TMPDIR_CMK_OPENAI/pending.headers"
        PENDING_FILE="$TMPDIR_CMK_OPENAI/pending.json"
        STATUS="$(curl -sS -D "$PENDING_HEADERS" \
            "${API_URL}/domain-types/activation_run/collections/pending_changes" \
            -H "$AUTH_HEADER" \
            -H 'Accept: application/json' \
            -o "$PENDING_FILE" \
            -w '%{http_code}')"
        [[ "$STATUS" == "200" ]] || show_error_and_exit "$STATUS" "$PENDING_FILE"

        PENDING_ETAG="$(awk 'tolower($1) == "etag:" {sub(/\r$/, "", $2); print $2; exit}' "$PENDING_HEADERS")"
        if [[ -z "$PENDING_ETAG" ]]; then
            echo 'ERROR: pending changes response did not contain an ETag.' >&2
            exit 1
        fi

        ACTIVATE_FILE="$TMPDIR_CMK_OPENAI/activate.json"
        jq -n \
            --arg site "$CMK_SITE" \
            --argjson force "$FORCE_FOREIGN_CHANGES" \
            '{redirect: false, sites: [$site], force_foreign_changes: $force}' \
            > "$ACTIVATE_FILE"

        ACTIVATE_RESPONSE="$TMPDIR_CMK_OPENAI/activate-response.json"
        STATUS="$(http_json POST \
            "${API_URL}/domain-types/activation_run/actions/activate-changes/invoke" \
            "$ACTIVATE_FILE" "$PENDING_ETAG" "$ACTIVATE_RESPONSE")"
        case "$STATUS" in
            200|201|204|303)
                echo "Activation requested for site: $CMK_SITE"
                ;;
            *) show_error_and_exit "$STATUS" "$ACTIVATE_RESPONSE" ;;
        esac
    fi
fi

echo
echo 'Configured services:'
printf '  - %s\n' \
    'OpenAI Runtime Latency' \
    'OpenAI Runtime Chat Input Tokens' \
    'OpenAI Runtime Output Tokens' \
    'OpenAI Runtime Time To First Chunk' \
    'OpenAI Runtime Output Chunk Time' \
    'OpenAI Runtime Embedding Input Tokens'
echo
echo "OTel service.name filter: $OTEL_SERVICE_NAME"
echo "Checkmk target host:     $CMK_HOST"
echo "Lookback:                ${LOOKBACK_SECONDS}s"
echo "Histogram percentile:    p${HISTOGRAM_PERCENTILE}"
echo
echo 'Exporter requirement:'
echo '  export OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=DELTA'
