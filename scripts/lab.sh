#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
dc() {
  local files=(-f "$ROOT/compose.yaml")
  if [ -n "${LAB_BUILD_CA:-}" ]; then files+=(-f "$ROOT/infra/compose.build-ca.yaml"); fi
  if [ "${LAB_PILOT:-0}" = 1 ] || [ "${LAB_COMPACT:-0}" = 1 ]; then files+=(-f "$ROOT/compose.pilot.yaml"); fi
  if [ "${LAB_COMPACT:-0}" = 1 ]; then files+=(-f "$ROOT/infra/compose.mdm-compact.yaml"); fi
  docker compose --project-directory "$ROOT" "${files[@]}" "$@"
}
doctor() {
  command -v docker >/dev/null || { echo 'Docker is required. Install Docker Desktop or Docker Engine with Compose v2. No SQLite fallback.' >&2; return 1; }
  docker info >/dev/null || { echo 'Docker daemon is unavailable.' >&2; return 1; }
  dc version
  dc up --help | grep -q -- '--wait-timeout' || { echo 'Update Compose v2: --wait and --wait-timeout are required.' >&2; return 1; }
  dc config --quiet
  echo 'Docker/Compose and configuration checks passed. Allow 10 GB Docker memory and 15 GB free disk (unmeasured starting budget).'
}
build() {
  dc build tools node-tools
  dc run --rm --no-deps --user "$(id -u):$(id -g)" tools scripts/build.py
  dc run --rm --no-deps --user "$(id -u):$(id -g)" tools scripts/verify.py
}
ready() { dc exec -T monitor python health_probe.py; }
require_full() {
  dc exec -T monitor python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/health/ready")); assert d.get("footprint","full")=="full", "Full acceptance requires ./lab pilot-up; the compact footprint is not a substitute."'
}
compact_services() {
  local running service
  running=$(LAB_COMPACT=0 dc ps --services --status running)
  for service in db-sg db-uk; do
    [[ $'\n'"$running"$'\n' == *$'\n'"$service"$'\n'* ]] || { echo "Required compact store $service is not running." >&2; return 1; }
  done
  for service in db-us db-in opa-us opa-in pilot-peer-us grafana loki otel-collector; do
    [[ $'\n'"$running"$'\n' != *$'\n'"$service"$'\n'* ]] || { echo "Suspended service $service is unexpectedly running in compact mode." >&2; return 1; }
  done
}
faults() (
  # Restore actual dependencies even when a fault assertion fails.
  trap 'dc start opa-sg otel-collector >/dev/null' EXIT
  dc stop otel-collector
  dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/fault_acceptance.py telemetry
  dc start otel-collector
  dc stop opa-sg
  dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/fault_acceptance.py policy
  dc start opa-sg
  dc exec -T monitor python health_probe.py --wait 45
  dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/fault_acceptance.py recovered
  dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/logging_integration.py
)
read_isolation() (
  trap 'dc unpause pilot-peer-uk >/dev/null 2>&1 || :; dc unpause opa-sg >/dev/null 2>&1 || :' EXIT
  dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_read_isolation.py setup
  dc pause pilot-peer-uk
  dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_read_isolation.py paused
  dc unpause pilot-peer-uk
  dc pause opa-sg
  dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_read_isolation.py policy-paused
  dc unpause opa-sg
  dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_read_isolation.py recovered
)
case "${1:-help}" in
  pilot-up|pilot-compact-up)
    compact=0
    if [ "$1" = pilot-compact-up ]; then
      compact=1
      LAB_PILOT=1 LAB_COMPACT=0 dc stop grafana loki otel-collector pilot-peer-us opa-us opa-in db-us db-in
    fi
    python3 "$ROOT/scripts/pilot_setup.py"
    export LAB_PILOT=1
    export LAB_COMPACT="$compact"
    doctor; build
    stores=(db-sg db-uk opa-sg opa-uk)
    policies=(opa-sg opa-uk)
    if [ "$compact" = 0 ]; then stores+=(db-us db-in opa-us opa-in); policies+=(opa-us opa-in); fi
    dc up -d --wait --wait-timeout 240 "${stores[@]}"
    # OPA loads mounted bundles at process start; include new service policy on upgrades.
    dc restart "${policies[@]}"
    dc run --rm --no-deps --user "$(id -u):$(id -g)" -e SERVICING_ADMIN_DSN=postgresql://root@db-sg:26257/defaultdb?sslmode=disable tools poc/servicing_bootstrap.py source
    dc run --rm --no-deps --user "$(id -u):$(id -g)" -e SERVICING_ADMIN_DSN=postgresql://root@db-uk:26257/defaultdb?sslmode=disable tools poc/servicing_bootstrap.py recipient
    dc up --build -d --wait --wait-timeout 240
    ready
    reconcile_options=()
    if [ "$compact" = 1 ]; then reconcile_options+=(--wait-active 240); fi
    dc exec -T monitor python pilot_reconcile.py --dsn-env DB_SG "${reconcile_options[@]}"
    if [ "$compact" = 1 ]; then echo 'COMPACT MDM: two independent stores (SG + UK). US, India, migration and monitoring stack suspended. All data volumes retained. Restore the full lab with ./lab pilot-up.'; fi
    echo 'Synthetic pilot: http://localhost:8081 (PILOT_PORT overrides). Get a test credential with ./lab pilot-token crm-sg or uk-servicing.'
    ;;
  pilot-test)
    export LAB_PILOT=1
    require_full
    ready
    dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_acceptance.py
    dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_review_acceptance.py
    dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/mdm_workspace_acceptance.py
    for test in security_test.py pilot_scope_query_acceptance.py pilot_protocol_acceptance.py pilot_security_acceptance.py service_integration.py; do
      dc run --rm --no-deps --user "$(id -u):$(id -g)" tools "poc/tests/$test"
    done
    ;;
  pilot-isolation)
    export LAB_PILOT=1
    require_full
    ready
    read_isolation
    ;;
  pilot-faults)
    export LAB_PILOT=1
    require_full
    (
      trap 'dc start pilot-peer-uk opa-sg opa-uk otel-collector >/dev/null' EXIT
      dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_fault_acceptance.py setup
      dc stop pilot-peer-uk
      dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_fault_acceptance.py peer
      dc start pilot-peer-uk
      dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_fault_acceptance.py recovered
      dc stop opa-uk
      dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_fault_acceptance.py recipient-policy
      dc start opa-uk
      dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_fault_acceptance.py recovered
      dc stop opa-sg
      dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_fault_acceptance.py source-policy
      dc start opa-sg
      dc stop otel-collector
      dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_fault_acceptance.py telemetry
      dc start otel-collector
      dc restart monitor pilot-api pilot-peer-uk pilot-peer-us
      dc up -d --wait --wait-timeout 240 monitor pilot-api pilot-peer-uk pilot-peer-us pilot-gateway
      dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_fault_acceptance.py restart
      dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/pilot_fault_acceptance.py logs
      read_isolation
    )
    ;;
  pilot-reconcile)
    export LAB_PILOT=1
    shift
    dc exec -T monitor python pilot_reconcile.py --dsn-env DB_SG "$@"
    ;;
  pilot-compact-test)
    export LAB_PILOT=1 LAB_COMPACT=1
    ready
    compact_services
    dc run --rm --no-deps --user "$(id -u):$(id -g)" tools poc/tests/mdm_workspace_acceptance.py --compact
    dc run --rm --no-deps --user "$(id -u):$(id -g)" -e LAB_FOOTPRINT=mdm-compact tools poc/tests/pilot_reconcile_wait.py --drain
    (
      trap 'dc unpause monitor >/dev/null 2>&1 || :' EXIT
      dc pause monitor
      dc run --rm --no-deps --user "$(id -u):$(id -g)" -e LAB_FOOTPRINT=mdm-compact tools poc/tests/pilot_reconcile_wait.py
    )
    ready
    ;;
  pilot-compact-status)
    export LAB_PILOT=1 LAB_COMPACT=1
    compact_services
    dc ps
    ready
    echo 'Verified compact footprint: SG and UK active; US/India and monitoring suspended.'
    ;;
  pilot-identity)
    shift
    python3 "$ROOT/scripts/pilot_setup.py" "$@"
    ;;
  pilot-token)
    python3 "$ROOT/scripts/pilot_setup.py" token "${2:-}"
    ;;
  pilot-down)
    export LAB_PILOT=1
    dc down --remove-orphans
    ;;
  cluster-test)
    require_full
    ready
    dc exec -T monitor python -m unittest discover -s tests -p cluster_control_unit.py
    dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/cluster_control_acceptance.py
    dc restart monitor
    dc up -d --wait --wait-timeout 240 monitor gateway
    dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/cluster_control_acceptance.py --phase restart
    ;;
  cluster-faults)
    require_full
    ready
    (
      trap 'dc unpause db-in >/dev/null 2>&1 || :' EXIT
      dc pause db-in
      dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/cluster_control_acceptance.py --phase paused
      dc unpause db-in
      dc exec -T monitor python health_probe.py --wait 45
    )
    ;;
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
  smoke) require_full; dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/lab_acceptance.py --smoke ;;
  telemetry) require_full; dc exec -T -e POC_URL=http://gateway:8080 monitor python tests/logging_integration.py ;;
  faults) require_full; ready; faults ;;
  test)
    require_full
    ready
    dc run --rm --no-deps --user "$(id -u):$(id -g)" tools scripts/verify.py
    dc run --rm --no-deps tools design/tests/check_links.py
    dc run --rm --no-deps tools poc/tests/deployment_test.py
    for file in engine.mjs operational_engine.mjs migration_engine.mjs migration_ui.mjs lab_mode.mjs; do
      dc run --rm --no-deps node-tools "poc/tests/$file"
    done
    dc run --rm --no-deps node-tools design/tests/check.js
    dc exec -T monitor python tests/observability_test.py
    dc exec -T monitor python tests/health_probe_test.py
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
  ./lab pilot-compact-up   Two-store MDM: SG/UK; US/India and telemetry suspended
  ./lab pilot-compact-test Verify the compact MDM footprint against real SQL/OPA
  ./lab pilot-compact-status Check actual running and suspended services
  ./lab doctor       Check Docker/Compose and configuration
  ./lab up           Build docs/images, start and wait for SQL + OPA readiness
  ./lab status       Container and dependency health
  ./lab cluster-test Real cluster inventory, native canary backup/restore and restart evidence
  ./lab cluster-faults Pause India SQL and verify independent cluster controls
  ./lab smoke        Gateway, API, SQL identity and policy readiness
  ./lab telemetry    Verify API → Collector → Loki and Grafana provisioning
  ./lab faults       Stop real OPA/Collector; verify fail-closed exports and SQL audit isolation
  ./lab test         Synthetic-data integration, migration, restart and OTel checks
  ./lab pilot-up     Wire synthetic customer MDM, system/experience APIs and mTLS peers
  ./lab pilot-test   Actual SQL/OPA/API pilot acceptance
  ./lab pilot-faults Stop real peers/OPA/Collector and verify recovery and persistence
  ./lab pilot-isolation Pause peer/OPA; verify unrelated owner reads remain available
  ./lab pilot-reconcile [--batch-size 10]   Requeue current-state intents for protocol upgrade
  ./lab pilot-identity revoke|rotate IDENTITY   Revoke/rotate a synthetic credential
  ./lab pilot-token crm-sg|uk-servicing|us-reader   Print one local test credential
  ./lab pilot-down   Stop the pilot and lab; preserve volumes
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
