# Cluster control acceptance — 16 October 2026

The console was exercised on the running synthetic lab using CockroachDB 25.4.17
and all four persistent stores. It is a working development adapter. Regional
deployment, operator authentication and full production lifecycle management are
outside the executed scope. See [scope and commands](CLUSTER_CONTROL.md).

## Observed checks

- Four SQL-reported cluster UUIDs are distinct and match the inventory. Each
  cluster has one live node with its expected country label.
- Native `BACKUP` and `RESTORE` succeed on temporary canary databases. Acceptance
  checks the exact returned native job IDs, compares all three restored rows,
  verifies database cleanup and inspects operational audit. Business databases
  are not replaced or reset.
- Completed operation evidence persists unchanged after API restart. Management
  history is separate from business audit and application logs.
- Pausing actual India SQL gives unreachable inventory and an unavailable
  journal. India work fails closed while UK health checks complete independently.
  The fault runner restores India even when assertions fail.
- Real SQL metadata fixtures check recovery evidence beyond the recent-activity
  window and reconciliation of an uncertain Running state without replay. These
  are separate from native backup/restore evidence.
- Five orchestration units cover stop after backup, lost restore response,
  failed verification with native receipts retained, failed preflight and low
  disk headroom. Their stubs are not CockroachDB integration evidence.
- Chromium completes fleet search, Overview/Nodes, health execution, recovery
  review, incorrect/correct confirmation, results and separate Environment
  navigation. Fleet and Recovery fit 375/768/1440px viewports. A browser transport
  fault clears live cards and displays unavailability.

## Failures found and corrected

An early assertion matched native job descriptions, which RESTORE does not
preserve consistently. Evidence now follows returned native job IDs and still
requires both native jobs to have succeeded.

Repeated image builds exhausted disk headroom. CockroachDB paused a controller
index backfill and restore below its 5% ingest threshold. No assertion was
disabled. Unused images/build cache were removed without deleting volumes.
Journal indexes are now defined with fresh table creation, avoiding startup
backfills of existing journal data. The operator inspected and resumed the
paused native restore, verified exact rows and removed its temporary databases.
A subsequent complete rehearsal passed. Recovery now checks disk headroom before
creating data and fences uncertain outcomes for inspection.

Review found lost native receipts on interruption, stranded Running jobs after
SQL loss and readiness inferred from truncated history. Those paths are fixed
with regressions. The refresh button's accessible name excludes its decoration.

## Evidence and limits

CI executes the original container/pilot gates, cluster recovery/restart/outage
gates and Chromium before its mandatory security audit. The `lab-evidence`
artifact retains logs and `cluster-control/browser/` screenshots. Use the exact
PR commit's workflow for clean-build evidence; an earlier run is not a result for
a changed revision.

The existing vendor CVE gate remains blocked. Functional acceptance is not
security approval, business backup coverage, off-host DR, HA or physical residency
validation.
