#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
dc() { docker compose --project-directory "$ROOT" -f "$ROOT/compose.yaml" "$@"; }
doctor() {
  command -v docker >/dev/null || { echo 'Docker is required. Install Docker Desktop or Docker Engine with Compose v2. No SQLite fallback.' >&2; return 1; }
  docker info >/dev/null || { echo 'Docker daemon is unavailable.' >&2; return 1; }
  dc version
  dc up --help | grep -q -- '--wait-timeout' || { echo 'Update Compose v2: --wait and --wait-timeout are required.' >&2; return 1; }
  dc config --quiet
  echo 'Docker/Compose and configuration checks passed. Allow 10 GB Docker memory and 15 GB free disk (unmeasured starting budget).'
}
build() {
  dc build tools
  dc run --rm --no-deps --user "$(id -u):$(id -g)" tools scripts/build.py
  dc run --rm --no-deps --user "$(id -u):$(id -g)" tools scripts/verify.py
}
ready() { dc exec -T monitor python health_probe.py; }
case "${1:-help}" in
  doctor) doctor ;;
  build) doctor; build ;;
  up)
    doctor; build
    dc up --build -d --wait --wait-timeout 240
    ready
    dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/logging_integration.py
    echo 'Ready. Default portal: http://localhost:8080 (LAB_PORT in .env overrides the port).'
    ;;
  status) dc ps; ready ;;
  smoke) dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/lab_acceptance.py --smoke ;;
  telemetry) dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/logging_integration.py ;;
  test)
    ready
    dc run --rm --no-deps --user "$(id -u):$(id -g)" tools scripts/verify.py
    for file in engine.mjs operational_engine.mjs migration_engine.mjs migration_ui.mjs lab_mode.mjs; do
      dc run --rm --no-deps node-tools "poc/tests/$file"
    done
    dc run --rm --no-deps node-tools design/tests/check.js
    dc exec -T monitor python tests/observability_test.py
    dc exec -T opa-sg /opa test /policies
    dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/integration.py
    dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/operational_integration.py
    dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/lab_acceptance.py
    dc restart monitor
    dc up -d --wait --wait-timeout 240 monitor gateway
    dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/lab_acceptance.py --restart-check
    dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/logging_integration.py
    # Collector debug exporter emits a positive exported span count after its batch flush.
    exported=0
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
      if dc logs --no-color otel-collector | grep -E '"spans": *[1-9][0-9]*|#Spans: *[1-9][0-9]*' >/dev/null; then exported=1; break; fi
      sleep 1
    done
    [ "$exported" = 1 ] || { echo 'OTLP receipt was not observed in Collector logs.' >&2; exit 1; }
    echo 'PASS CockroachDB integration, restart persistence, gateway routing, Collector span receipt and Loki/Grafana logs.'
    ;;
  generate) shift; dc exec -T monitor python scripts/generate.py "$@" ;;
  business) shift; dc exec -T monitor python scripts/business_commands.py "$@" ;;
  migrate)
    shift
    if [ "${1:-}" = '--reset' ]; then
      dc exec -T monitor python -c 'import httpx; r=httpx.post("http://127.0.0.1:8000/api/migration/reset",json={"scenario":"synthetic-india"},timeout=30);r.raise_for_status()'
      shift
    fi
    dc exec -T monitor python scripts/migration_commands.py --base-url http://127.0.0.1:8000 --walkthrough "$@"
    ;;
  migration-traffic) shift; dc exec -T monitor python scripts/migration_commands.py --base-url http://127.0.0.1:8000 "$@" ;;
  logs) shift; dc logs --tail 150 -f "$@" ;;
  sql)
    region=$(printf '%s' "${2:-}" | tr '[:upper:]' '[:lower:]')
    case "$region" in sg|uk|us|in) ;; *) echo 'Usage: ./lab sql SG|UK|US|IN [Cockroach SQL flags]' >&2; exit 2;; esac
    shift 2; dc exec "db-$region" /cockroach/cockroach sql --insecure --host=localhost:26257 "$@"
    ;;
  down) dc down --remove-orphans ;;
  reset)
    [ "${2:-}" = '--confirm-synthetic-lab' ] || { echo 'This deletes all lab DB/telemetry volumes. Use ./lab reset --confirm-synthetic-lab to confirm.' >&2; exit 2; }
    dc down --volumes --remove-orphans
    ;;
  release) dc run --rm --no-deps --user "$(id -u):$(id -g)" tools scripts/release.py ;;
  help|--help|-h)
    cat <<'HELP'
Sovereign Federation Lab — CockroachDB only
  ./lab doctor       Check Docker/Compose and configuration
  ./lab up           Build docs/images, start and wait for SQL + OPA readiness
  ./lab status       Container and dependency health
  ./lab smoke        Gateway, API, SQL identity and policy readiness
  ./lab telemetry    Verify API → Collector → Loki and Grafana provisioning
  ./lab test         Synthetic-data integration, migration, restart and OTel checks
  ./lab generate --count 5 --scenario sg-uk-no-us
  ./lab business --command open_holding --count 2
  ./lab migrate [--reset]       Complete the isolated India movement
  ./lab migration-traffic --kind update --count 20 --interval 0.5
  ./lab sql SG|UK|US|IN [-e 'SELECT ...']
  ./lab logs [service] | down | build | release
  ./lab reset --confirm-synthetic-lab    Delete this project's persistent volumes
HELP
    ;;
  *) echo 'Unknown command. Run ./lab help.' >&2; exit 2 ;;
esac
