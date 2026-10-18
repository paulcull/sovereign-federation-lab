# MDM workspace acceptance — 18 October 2026

These are local execution results for the workspace/compact-footprint revision.
The PR's exact commit and GitHub Actions result are separate evidence: this
record does not assert an unexecuted full deployment passed.

## Environment and data preservation

The Docker host exposes 5 CPUs, 17 GiB RAM, Docker 28.4 and Compose 2.40.3.
Its 32 GB filesystem initially had about 509 MB available. With authorization,
US/India and telemetry containers were stopped. The stopped Grafana container
and its rebuildable image were removed without removing its named volume.
This recovered about 9.3 GB before builds. Docker uses VFS, so rebuilds consume
more disk than the initial free-space figure suggests.

All 14 pre-existing volumes remain present. No customer or database volume was
deleted, no location was remapped, and SG/UK are independent single-node
CockroachDB stores. This is not a two-node HA cluster.

## Executed local gates

| Gate | Result and practical limit |
|---|---|
| `./lab pilot-compact-up` | Passed real SQL/OPA/peer startup with only SG/UK active; waits for active startup reconciliation. |
| `./lab pilot-compact-test` | Passed source-qualified SQL directory/search/pagination, authentication/input bounds and other-source nondisclosure; SG/UK relationship/contact delivery, idempotent owner command and mandatory SQL audit. |
| Suspended-destination regression | At least 16 distinct pending US partitions remain durable while UK work completes; this is not US exclusion or purge evidence. |
| Actual coordinator/API restart | Passed unchanged global identity, source-directory presence and updated UK contact after process restart. |
| Live compact browser | Passed real creation, source-directory reload, delayed owner response across identity switch, UK contact rendering/version checks, actual stopped API with no demo fallback, recovery and 375/768/1440px layouts. Post-recovery inventory confirms optional services stayed stopped. |
| Static preview browser | Passed read-only fixtures, zero pilot API calls/storage, 375/768/1440px layout and failed/invalid live configuration without sample-data fallback. This is UI evidence only. |
| Focused unit regressions | All 37 passed, including explicit full/compact/unknown deployment configuration boundaries. |
| Site and syntax | Passed 57 HTML pages, 1,666 local references, 20 ADRs, Python/JavaScript/Bash syntax and diff whitespace checks. The 31 external references are inventoried, not uptime-verified. |
| Full acceptance in compact | Correctly rejected `./lab test`; it does not skip US/India/telemetry assertions. |

Reproducible real restart sequence:

```bash
./lab pilot-compact-up
./lab pilot-compact-test
docker compose -f compose.yaml -f compose.pilot.yaml -f infra/compose.mdm-compact.yaml restart monitor pilot-api
docker compose -f compose.yaml -f compose.pilot.yaml -f infra/compose.mdm-compact.yaml up -d --wait --wait-timeout 240
docker compose -f compose.yaml -f compose.pilot.yaml -f infra/compose.mdm-compact.yaml run --rm --no-deps tools poc/tests/mdm_workspace_acceptance.py --compact --restart
python3 poc/tests/pilot_browser.py --compact
./lab pilot-compact-status
```

The browser setup is described in [container acceptance](CONTAINER_ACCEPTANCE.md).
Ignored evidence is under `artifacts/mdm-workspace/` and
`artifacts/pilot/browser/`; no credentials are recorded in this document.

## Defects found during execution

- The pilot gateway inherited static simulation configuration and omitted the
  JavaScript-module MIME handler. It now serves explicit no-store live pilot
  configuration and the workspace modules correctly.
- Suspended US partitions could occupy the relay's bounded selection. Active
  destinations are now filtered in SQL before ranking/limiting; retained work
  resumes through current admission when the full footprint is restored.
- A retained-data startup replay delayed a new UK relationship beyond the
  existing acceptance deadline. Compact startup now waits for its active startup
  intents to drain, with an explicit bounded failure. The assertion is unchanged.
- A browser outage recovery initially used full Compose and restarted suspended
  dependencies. It now uses the selected compact override; CI checks the actual
  service inventory after recovery and compares volume inventories.
- Review found that a timestamp cutoff could omit renewed receipt-conflict
  intents from startup drain. The wait now counts all active pending work; a real
  SQL regression pauses the actual relay and checks atomic replacement stays
  pending while suspended US work remains untouched.
- Rejected configuration promises are cleared for later retry. Browser checks
  cover transient failure followed by live recovery and minimum 4.5:1 contrast
  for essential profile labels, identifiers and form guidance.

## Complete acceptance and remaining limits

Local full migration/US/telemetry and the all-image security scan are not claimed
for this run: the local Grafana image was deliberately removed to recover disk.
The preserved GitHub Actions full job runs those gates, the new workspace
contracts, full-to-compact switching, restart/browser checks, volume preservation,
full restoration/deferred-US delivery and telemetry. A separate fresh-runner job
checks compact startup without pre-existing data or telemetry images. Inspect
both jobs at the PR commit; artifacts are `lab-evidence` and
`compact-cold-evidence`.

Existing scoped synthetic-lab CVE acceptances are unchanged. Neither a green
workflow nor the modern UI establishes bank-data approval, production identity,
regional isolation, HA, performance at scale, or off-host recovery. See
[production gates](PRODUCTION_READINESS.md) and the [workspace guide](MDM_WORKSPACE.md).
