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
- Nine orchestration units cover stop after backup, lost restore response,
  failed verification with native receipts retained, failed preflight and low
  disk headroom; both post-step and terminal journal writes failing after a
  native receipt, reconnect persistence without replay; lost enqueue COMMIT
  acknowledgement; and observed health values without premature verification.
  Their stubs are not CockroachDB integration evidence.
- Chromium completes fleet search, Overview/Nodes, health execution, recovery
  review, incorrect/correct confirmation, results and separate Environment
  navigation. Fleet and Recovery fit 375/768/1440px viewports. A browser transport
  fault clears live cards and displays unavailability. A new lost-acknowledgement
  browser check first commits a real API/SQL health operation, replaces only its
  HTTP response with a 503, and confirms a retry reuses its UUID and original job.
  All-journal transport failure shows unknown history instead of an empty success;
  all four mobile sidebar controls retain accessible names. Transport simulation
  tests presentation and retry behavior; the separate actual India pause gate
  supplies database-outage evidence.

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

PR review also found that losing both post-step and terminal journal writes could
discard a known native receipt. A per-region pending update now retries the full
result before another task without replaying native SQL. This survives a SQL
reconnect while the process remains alive; simultaneous process loss still needs
native-job/artifact inspection. Enqueue errors now report uncertain acceptance,
and page retries retain the request UUID per cluster/operation. Health checks
record actual node/locality observations and add a verification summary only
after the final check passes. Unavailable aggregate history and mobile accessible
names are corrected in source and generated assets.

The final browser retry regression waits for the specific committed job receipt
before checking success; matching a previous completed card had made an early
test assertion race the response. It verifies both HTTP 503 acknowledgement loss
and a browser AbortError after a real commit, retaining every UUID/receipt
assertion. AbortError's read-only message is handled without mutating it.

## Evidence and limits

CI executes the original container/pilot gates, cluster recovery/restart/outage
gates and Chromium before its mandatory security audit. The `lab-evidence`
artifact retains logs and `cluster-control/browser/` screenshots. Use the exact
PR commit's workflow for clean-build evidence; an earlier run is not a result for
a changed revision.

The strict vendor CVE gate remains blocked. The user has approved exact, expiring
CockroachDB, Grafana and Loki exceptions for the explicit synthetic development
context; see [dependency security](DEPENDENCY_SECURITY.md). Functional acceptance
and development risk acceptance provide no production security approval,
business backup coverage, off-host DR, HA or physical residency validation.

The merge follow-up passed nine controller units, 30 security-audit regressions,
native cluster recovery/restart, actual India SQL pause with independent UK work,
the complete base federation/operational/migration/telemetry suite, MDM/servicing
SQL/OPA acceptance and all four Chromium walkthroughs. Documentation verification
passed 57 HTML pages, 1,637 local links and 20 ADRs. Logs remain under ignored
`artifacts/pr7-followup/` and `artifacts/pr7-security-final-2026-10-16/` locally.
Before the observability upgrade and subsequent user approval, the real
dependency audit completed all 11 image scans without errors, with zero
Python advisories/skips, 34 accepted CockroachDB finding instances and 13 other
vendor finding instances still blocking. That historical scan was a completed
failed security gate. The current pinned images and approved scope are recorded
in [dependency security](DEPENDENCY_SECURITY.md); use the latest exact-commit CI
result for the current revision.
