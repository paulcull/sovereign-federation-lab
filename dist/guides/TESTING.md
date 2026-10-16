# Unified lab verification — edition 09

## CockroachDB cluster control

`LAB_PILOT=1 ./lab cluster-test` verifies live cluster identities, guarded
operations, native synthetic BACKUP/RESTORE, exact canary rows, audit and API
restart persistence. `LAB_PILOT=1 ./lab cluster-faults` pauses the actual India
database and checks independent UK operations. Run
`python3 poc/tests/cluster_control_browser.py` for cluster-first navigation,
separate Environment context, reviewed recovery and responsive layouts.
See [cluster control scope](docs/CLUSTER_CONTROL.md). Browser transport faults
check presentation only; database evidence comes from actual CockroachDB.

## Customer MDM integration pilot

The optional profile has real SQL/OPA and mTLS system/experience API gates:
`./lab pilot-test`, `./lab pilot-faults`, and
`python3 poc/tests/pilot_browser.py`. See [the pilot runbook](docs/PILOT.md) and
[executed pilot evidence](docs/PILOT_ACCEPTANCE.md).
These gates check owner-qualified source references, exact eligible identity
fields, scoped relationship views, processing-country exclusions, stale/replay
and freshness handling, actual peer/source/recipient OPA/Collector loss and
process restart. The preserved complete suite runs with `LAB_PILOT=1 ./lab test`.
The CI workflow executes the original lab and browser gates before adding the
pilot, then runs pilot acceptance, real outages and the live operator console.
No bank identity, physical residency, scale, HA, distributed lease or
normalized-table migration is inferred from a successful single-host run.


The microsite reader journey has a read-only real-gateway Chromium check:
`python3 design/tests/reader_browser.py`, using the Playwright setup described in
[container acceptance](docs/CONTAINER_ACCEPTANCE.md). It follows the portal entry,
nine-page previous/next sequence, glossary and evidence links, checks all 28
component pages for obsolete acceptance claims, exercises the mobile menu and
captures 375/768/1440px layouts. CI includes it after the live lab walkthrough.
The service explanation also checks responsive rendering and keeps its routing
and integration proposal visible before the expandable technical reference.
The executive summary leads the overview while retaining the worked example;
the service page checks include relationship risk, MDM scope and pilot labels.
See [the executed existing-service guide review](docs/SERVICE_GUIDE_REVIEW.md)
for the 12 October 2026 documentation, browser and complete container rerun.
Offline and browser checks share `design/tests/status_claims.py`: known obsolete
claims are rejected, and the operations/observability pages must state both the
validated scope and its remaining migration/telemetry limits.
This verifies navigation and bounded rendering; comprehension still needs feedback
from first-time readers. Screenshots are saved under ignored `artifacts/reader-guide/`.

The complete Docker lab passed `./lab doctor`, `./lab up` and `./lab test` on 11 October 2026, followed by the live Chromium generator/migration walkthrough. Actual source OPA and Collector outage probes passed fail-closed export and SQL-audit isolation checks. See [container acceptance evidence](docs/CONTAINER_ACCEPTANCE.md) for the environment, failures fixed, exact commands and limits. Service entry points require CockroachDB and there is no SQLite fallback.

Execution-limit statements under the historical editions below describe their original authoring runs. They do not describe this subsequent container acceptance. A PR workflow result must be checked separately at its exact commit.

Source authoring verification is recorded below; historical tests retain their original scope. `scripts/verify.py` checks generated documentation, navigation, ADRs and deployment contracts. `poc/tests/lab_acceptance.py` checks actual CockroachDB identity, gateway/API routes, OPA, migration SQL, source fencing and restart-persistent authority. The shell gate also requires OTel Collector span receipt. These checks cannot be substituted by SQLite evidence.

## Source authoring checks before container acceptance

- 51 generated HTML pages; 1,498 local links/assets/fragments; 28 component-page links and engineering prompts; 16 complete ADR records; canonical fixtures and four-store deployment contracts.
- Node: original federation engine, normalized business engine, migration engine, migration click handlers, deployment-mode fail-closed cases and current design navigation/menu/print/prompt-copy handlers.
- OPA 1.9.0: 24/24 Rego tests. Python core and browser/OPA parity: 840 cases, 7,290 row decisions, all 30 entities and 11 business commands.
- Existing scale conservation, storage arithmetic, queue-accounting and pilot-dependency validator passed. No new performance benchmark was run.
- Python syntax, shell syntax and JavaScript entry-point syntax checks passed. Doctor correctly rejects missing Docker. No browser-rendered QA is claimed.

## Historical evidence from prior editions

# Entity relocation verification — 11 October 2026

Executed for edition 08:

- Browser engine: movement, record conservation, updates/deletes during copy, catch-up, validation invalidation, source fencing, receipt handoff, deadlines, stale events and blocked reversal.
- Real four-file SQLite repositories: durable transactions, copy checkpoint restart, independent UK command while the entity lock is held, final source cleanup and retained authority fence. Full scenario repeated against real OPA 1.9.0 with telemetry disabled.
- FastAPI HTTP contracts: staging/retired read guards, invalid batch rejection, idempotency conflicts and targeted reset. Injected crashes after source fence and after ACTIVATING checkpoint leave no dual writer and recover forward.
- OpenTelemetry SDK spans captured in memory with explicit test sampling; bounded work.class attributes checked. This does not test OTLP export.
- Live uvicorn/HTTP generator walkthrough passed in SQLite mode, including source commit, India commit and final cleanup. UI click handlers passed a Node structural test; this is not browser-rendered QA.
- Actual OPA Rego suite: **24/24** (12 existing rules tests + 12 migration tests).

Run `node poc/tests/migration_engine.mjs`, `python3 poc/tests/migration_test.py`, `python3 poc/tests/migration_api_test.py`, and `opa test poc/policies`. For the full live API walkthrough use `poc/scripts/migration_commands.py --walkthrough` against a fresh DRAFT scenario. See [MIGRATION.md](MIGRATION.md).

The new adapter uses isolated typed row envelopes, not the normalized v3 tables. Single-coordinator safety does not prove distributed fencing or foreground performance isolation. CockroachDB execution remains unverified: Docker is unavailable and the native binary's process CPU probe previously prevented startup. Browser-rendered visual QA, physical residency/HA, OTLP export and retained-storage erasure are not claimed.

# Capacity modeling verification — 11 October 2026

- Executed 16 × 3 seeded queue scenarios: **17,280,000** foreground requests and **2,218,221** background jobs. Full-scale cardinality is analytic, not instantiated in a database.
- Validated population/edge conservation, storage arithmetic, recovery drain, separate regional queues, hot-key serialization, percentile/sample accounting and pilot dependencies with `scale/validate.py`.
- Observed actual OPA 1.9.0 sequential loopback timings: 1/16/64/256-resource batches, 1,200 measured requests each after 100 warmups, with telemetry disabled. See the recorded environment and limits.
- Inspected the generated capacity chart image; JavaScript syntax and site link/asset checks pass. Interactive browser visual QA remains unavailable.
- No new CockroachDB performance, HA, WAN, migration or full-volume integration claim is made. Targets need the gated pilot benchmark.

# Verification — operational edition v3

Verified 11 October 2026:

- Actual OPA v1.9.0 and browser mirror: **840 scope/recipient cases, 7,290 row decisions**. Global party fields, US exclusions, table defaults, resource restrictions, classification and contextual consent match.
- Python core: all 11 command types, shared-row fanout, typed source references and filtered graph closure. Node workflow tests: idempotency, stale expected version, paused-store read fencing, table/key narrowing, restoration and expiry.
- UI functions render business-model and service-lab markup in Node; JavaScript syntax and Python compilation pass. This is structural verification, not browser visual QA.
- Original Rego **12/12** and **990** entity policy comparisons pass again.

Database execution remains unverified for the environment reason recorded below. The new typed SQL, atomic replacement and persistent receipt behaviour must pass the local suite before adoption. No browser visual QA or OTLP end-to-end verification was possible here.

```bash
node poc/tests/operational_engine.mjs
python3 poc/tests/operational_core_test.py --opa /path/to/opa
# With the local Docker stack running:
python3 poc/tests/operational_integration.py
```

The integration suite changes only synthetic examples, restores consent/table/party restrictions afterwards, and leaves generated holdings/history in place. Inspect global party vs relationship rows using the SQL in OPERATIONAL.md. Additional required gates: failed owner transaction must roll back outbox and business rows together; recipient crash must retain the previous complete graph or new complete graph, never a partial graph; duplicate deliveries must not duplicate effects; cross-owner/scope foreign keys must reject contamination. Exercise malformed scope IDs, an unavailable source authority, multiple retry attempts and control changes during a backlog.

The source graph and browser/OPA checks do not prove database atomicity or physical residency.

## Previous entity edition checks

Verified 10 October 2026:

- **Actual OPA v1.9.0:** 12/12 Rego tests passed. Entity deny, physical deny, local-placement mismatch, store-binding mismatch, same-store isolation, missing grant, expiry, purpose and field profiles are covered.
- **Policy parity:** 990 browser/actual-OPA comparisons passed (33 generated records × 30 recipient entities), comparing allow, reason and fields.
- **Executable browser engine tests:** catalog grouping 3/8/3/5/11; SG→UK/US exclusion; shared-store isolation; three recipient projections in one physical store; geographic and placement deny; pause/revoke/purge; stale policy edits; independent owner versions; read-only migration planning; grant expiry.
- **Structural checks:** JS syntax, Python compilation/imports, catalog consistency, design-page links and package contents are checked during delivery.

Not claimed:

- Full CockroachDB integration. Native v25.4.0 startup previously failed because this execution environment cannot satisfy its process CPU probe (`unable to get proc cpu time: no such process`). Docker is unavailable here. v2 integration tests are supplied for a capable local Docker host.
- Browser-rendered visual/accessibility QA. No supported browser control is available in this environment. The responsive interface and reduced-motion support require manual browser inspection.
- OTLP Collector end-to-end export, production authentication, physical residency, HA, distributed fencing, regulatory deletion or throughput measurements.

## Local acceptance

```bash
./lab doctor
./lab up
./lab test
# Optional browser gate, after the suite; requires Playwright and Chromium:
python3 poc/tests/browser_acceptance.py
```

The integration suite adds synthetic records. It verifies database-backed entity projections, denied reads, identity-disclosure restrictions, independent owner relationships, pause/revoke/resume, geography deny, placement conflicts and expiry.

Direct SQL example:

```bash
docker compose exec db-us ./cockroach sql --insecure --execute 'SELECT owner, customer, destination, doc FROM fe_replicas'
```

For a canonical Singapore/UK-only customer UUID, inspect `fe_replicas`, `fe_fences` and `fe_audit` at the US store. No customer-specific destination artefact should exist. A source-side denied-candidate audit is allowed and expected.

## Additional gates before distributing the harness

1. Crash after recipient commit before source acknowledgement: exactly one final projection and idempotent receipt.
2. Kill recipient DB and OPA separately: retries and unknown states must be honest.
3. Revoke while stale work is queued; replay stale permits against the future network importer.
4. Expire separate destination grants at different times and narrow contact profile to minimal.
5. Restart with persistent outbox work. Pause toggle intentionally resets.
6. Change catalog mapping against existing data: startup must refuse, not silently redirect ownership.
7. Test failed migration stages and restore in quarantine once execution exists.
8. Inspect 375/768/1440px layouts, keyboard operation, map fullscreen, reduced motion, generator start/stop, dirty policy forms and copy-versus-permission semantics.

## Application logging extension

See [observability setup and evidence](docs/OBSERVABILITY.md). `./lab telemetry` verifies API → OTel Collector → Loki, trace correlation and Grafana provisioning. `./lab up` and `./lab test` include this gate. Python OTLP tests passed during authoring. The full Docker/Loki/Grafana path subsequently passed; see [container acceptance](docs/CONTAINER_ACCEPTANCE.md). The starting Docker budget with this extension is 10 GB RAM and 15 GB disk, not measured.

## Production foundation regressions

`./lab pilot-test` retains the original pilot assertions and adds real CockroachDB
scoped-query/OPA parity and query-plan checks, import protocol/placement/replay
and rollback/race checks, live credential/delegation checks, and independent
servicing-service transaction/UK projection conformance. The isolated credential
helper tests use synthetic certificates; they are not database evidence.

`./lab pilot-isolation` pauses actual UK peer and SG OPA processes, requires an
authorized owner read to finish before the stalled operation times out, and
checks recovery. It is included in `./lab pilot-faults`. Run these mutable suites
sequentially. See [foundation acceptance](docs/FOUNDATIONS_ACCEPTANCE.md) for
executed results and [production gates](docs/PRODUCTION_READINESS.md) for work
that remains unproven.
