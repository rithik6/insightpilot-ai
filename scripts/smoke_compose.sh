#!/usr/bin/env bash
set -euo pipefail

export INSIGHTPILOT_ENVIRONMENT=production
export INSIGHTPILOT_API_PORT="${INSIGHTPILOT_API_PORT:-18016}"
INSIGHTPILOT_POSTGRES_PASSWORD=$(openssl rand -hex 24)
export INSIGHTPILOT_POSTGRES_PASSWORD

project="insightpilot-smoke-${BASHPID}-${RANDOM}"
compose() {
    docker compose --env-file /dev/null --project-name "$project" "$@"
}

cleanup() {
    local result=$?
    if (( result != 0 )); then
        compose ps --all || true
    fi
    compose down --volumes
}
trap cleanup EXIT

compose config --quiet
compose up --build --wait --wait-timeout 120
base_url="http://127.0.0.1:${INSIGHTPILOT_API_PORT}/api/v1"
test "$(curl --fail --silent --show-error --max-time 10 "$base_url/health")" = '{"status":"ok"}'
test "$(curl --fail --silent --show-error --max-time 10 "$base_url/ready")" = '{"status":"ready"}'
printf 'Compose liveness and dependency readiness passed.\n'
