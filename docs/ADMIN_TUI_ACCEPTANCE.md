# Logical admin acceptance — 18 October 2026

Scope: optional host-side terminal for persisted logical configuration and
read-only health. Physical targets and runtime reconciliation are deferred.
See [A1–A12](ADMIN_TUI_SPEC.md) and [the walkthrough](ADMIN_TUI.md).

## Executed locally

- Python 3.12, Textual 8.2.8; all **23** registry, health-boundary, Textual and
  terminal PTY tests passed. The JSON CLI also ran with Python site packages
  disabled, proving it does not require Textual. Real HTTP fixtures trickled headers
  and bodies beyond the probe deadline: the probe was killed/reaped, its connection
  closed, and the TUI released polling and recovered on its next refresh.
- Real temporary files and separate processes exercised concurrent writers,
  revision conflicts, UUID replay, corruption rejection and atomic replacement.
  A configure form reloads current defaults after an external count change, so
  changing only state cannot silently undo another operator’s node increase.
  Injected pre-replace failure preserved the old state; an uncertain directory
  fsync after replacement recovered the original receipt by UUID.
- Real Textual driver exercised Germany registration, review/cancel/save,
  retained logical node IDs, observability intent, tabs, filtering, stale review,
  background health during review, shutdown callbacks, restart and 140×42/80×24 layouts. A Unix PTY
  launched `./lab admin`, opened help, quit and restored terminal modes/screen.
- **37** existing audit-orchestration tests passed. Coverage now includes the
  admin dependency lock alongside the existing three locks.
- `pip-audit --require-hashes -r requirements-admin.txt`: **9 dependencies, zero
  known advisories**. A combined audit of all four Python locks also passed: **68 packages, zero known advisories**. These are Python dependency results, not container scans.

## Actual running lab evidence

The existing compact lab ran in project `sfl-acceptance`: separate CockroachDB
SG/UK, SG/UK OPA, foundation API, synthetic pilot services and loopback gateways.
No business database was substituted. US, Mumbai and the telemetry services
remained suspended; their named volumes were retained.

Executed from this worktree:

```bash
.venv-admin/bin/python -m unittest discover -s admin/tests -p 'test_*.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
python3 admin/tests/live_health_acceptance.py --compact
COMPOSE_PROJECT_NAME=sfl-acceptance LAB_PILOT=1 LAB_COMPACT=1 bash scripts/admin_health_faults.sh
```

All five sequential health phases passed: healthy, actual UK OPA stopped
(UK degraded / SG healthy), OPA restored, actual gateway stopped (no current
healthy claim), gateway restored (SG/UK healthy again). The script restored
services with an EXIT trap. New Germany stayed **Backend unassigned** throughout;
all placement-ready flags stayed false. Expired observations lost current status.

These checks establish gateway SQL/OPA observation and presentation, not native
node health, capacity, physical geography, MDM migration or placement readiness.
Full four-store acceptance is delegated to the preserved GitHub Actions container
job; its exact-commit result must be recorded separately, never inferred here.

## Review evidence and limits

Run `.venv-admin/bin/python admin/tests/capture_screens.py` against the actual
local gateway for SVG captures of Stores, Health, Environment, Activity and the
80×24 layout under ignored `artifacts/admin-screens/`. Captures create no new
configuration. The separate terminal CI job and full/compact live-health gates
are included in `.github/workflows/lab.yml`.

The initial container security blocker was **CVE-2026-100349** in Grafana 13.2.4
(`github.com/getkin/kin-openapi` v0.144.0; library fix 0.146.0). On 18 October
the user approved [SFL-RA-0058](security/grafana-risk-acceptance-2026-10-18.json)
for this exact image/finding in the synthetic lab through 15 November 2026 at
00:00 UTC. The vulnerable code remains; strict mode still blocks it. Fresh CI
must establish the resulting audit outcome. The previous 57 records are unchanged.
A production controller,
automatic scaling/provisioning, target assignment and monitoring service switches
are not implemented by saving desired intent.
