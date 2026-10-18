#!/usr/bin/env bash
# Sequential, reversible fault acceptance; never part of the admin application.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
files=(-f compose.yaml)
options=()
if [ "${LAB_PILOT:-0}" = 1 ]; then files+=(-f compose.pilot.yaml); fi
if [ "${LAB_COMPACT:-0}" = 1 ]; then
  files=(-f compose.yaml -f compose.pilot.yaml -f infra/compose.mdm-compact.yaml)
  options+=(--compact)
fi
dc() { docker compose "${files[@]}" "$@"; }
trap 'dc start opa-uk gateway >/dev/null' EXIT
python3 admin/tests/live_health_acceptance.py "${options[@]}"
dc stop opa-uk
python3 admin/tests/live_health_acceptance.py "${options[@]}" --phase degraded
dc start opa-uk
python3 admin/tests/live_health_acceptance.py "${options[@]}"
dc stop gateway
python3 admin/tests/live_health_acceptance.py "${options[@]}" --phase unavailable
dc start gateway
python3 admin/tests/live_health_acceptance.py "${options[@]}"
