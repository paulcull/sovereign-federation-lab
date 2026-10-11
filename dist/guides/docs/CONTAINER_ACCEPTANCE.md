# Container acceptance — 11 October 2026

This is actual Docker/CockroachDB/OPA acceptance of the small synthetic lab, starting
from main `05cf77c2d0fb12e71d95c0133fddff66e2e79698` on branch
`fix/container-lab-acceptance`. No SQLite business database or HTTP/policy mocks
were used for these container and browser gates. Historical unit/model results
remain separate in [TESTING.md](../TESTING.md).

## Runtime and isolation

- Linux amd64 managed development workspace; Docker 28.4.0, Compose 2.40.3, vfs storage.
- Effective cgroup limits: 4 CPU cores and 16 GiB RAM. Docker reports 5 CPUs and
  17.59 GiB host memory; these are not the effective task quotas.
- Approximately 30 GB free disk before builds. Repeated vfs image builds consumed
  substantial space; approximately 15 GB remained at the acceptance checkpoint.
- Thirteen running services: four independent single-node CockroachDB stores,
  four OPA services, API, gateway, Collector, Loki and Grafana.
- The pre-existing `sovereign-lab` project was stopped without deleting its volumes.
  Acceptance used newly created `sfl-acceptance` volumes and loopback port 8080.
- Playwright 1.62.0 with installed Chromium 154 was used for rendered UI checks.
  A roughly 1.4 GiB steady-state container memory observation is only a small-fixture
  sample, not a lower recommended budget or capacity measurement.

## Observed failures and fixes

| Failure actually observed | Fix / regression evidence |
|---|---|
| pip HTTPS certificate verification failed behind the managed proxy | Optional `LAB_BUILD_CA` BuildKit secret; TLS verification stays enabled, CA stays out of image layers |
| Pinned CockroachDB image wrapper rejected `--listen-addr=0.0.0.0:26257` | Invoke `/cockroach/cockroach` directly in all four stores; actual SQL identity/readiness and fresh-volume startup passed |
| Private-umask source files denied non-root configuration/static reads | Normalize public gateway assets/live JSON in the image; make only non-sensitive mounted policies/configs readable locally; do not run sinks as root |
| Internal gateway/OTLP requests went through the outbound proxy, returning 403 | Set both uppercase and lowercase proxy bypasses; disable BusyBox wget proxy only for its loopback health request; regression injects conflicting inherited defaults |
| Monitor claimed stores offline and copies absent although UK SQL had the replica | Remove untyped selected SQL placeholder; attach source-store identity in Python; assert real stores online, pending queue identity and replica visibility |
| Browser stayed at Connecting because `.mjs` was `application/octet-stream` | Serve JavaScript module MIME type; assert deployed module headers and execute real browser modules |
| Global party API serialized the broader relationship `display_name` column as null | Use global-field contract for party scopes; exact three-field API assertion and actual US SQL checks |
| Run guide referenced a nonexistent GitHub import/export task and default downloads returned 404 | Use the canonical repository source links; describe optional release generation separately; rebuild and verify portable navigation |

The legacy volume also contained incompatible Loki file ownership. A fresh named
volume started normally; it was not repaired by dropping or replacing business data.

## Acceptance gates

Executed successfully:

1. `./lab doctor`, `./lab up`, `./lab test`: documentation contracts, Node engines/UI
   structure, 24/24 Rego tests, Python OTLP minimization/failure tests, and actual API/SQL
   federation, normalized business commands, migration and restart persistence.
2. SG → UK minimal record projection with US exclusion; same-store entity isolation,
   independent owners, field filtering, geographic/placement/entitlement rejection,
   revocation while paused, eventual live purge and expiry.
3. Direct US SQL checks: a never-authorized record has no master, replica, fence,
   source-task inbox receipt or customer-linked destination audit. Eligible party
   identity has exactly `id`, `global_party_id`, `party_type`; no name value,
   relationship or holding payload accompanies it.
4. India migration: consistent snapshot, source updates/new graphs/tombstones,
   catch-up, validation invalidation after a new write, durable SG fencing,
   unrelated UK work, activation at epoch 2, idempotency handoff, stale SG/epoch/transfer
   rejection, deadline and bounded source cleanup. After the suite: 61 stored India
   envelopes (60 live plus one tombstone), zero SG/US entity payload, no source
   snapshot/journal/receipt rows, retained SG writer fence and only India writable.
5. API restart: persisted record/business-scope/receipt and India-content digests
   match; migration remains COMPLETE/India/epoch 2, receipt replay survives and new
   writes commit to India. This is API restart evidence, not database disaster recovery.
6. Real API-generated request logs reached Loki through the Collector. Request
   header, JSON log and exported API span use the same generated trace ID. The
   Collector reports nonzero span receipt. Grafana health, datasource and dashboard
   APIs respond through the gateway, and its provisioned panel renders real request logs.
7. Live Chromium: generator creates a new record, monitor renders acknowledged movement,
   complete India UI walkthrough including concurrent changes and stale writer denial,
   architecture/ADR/run-guide navigation, 375/768/1440px monitor captures and Grafana logs.
   Page/module errors fail the browser gate. Screenshots were inspected; this is a
   bounded smoke/walkthrough, not a full accessibility or browser-compatibility certification.
8. Actual stopped Collector: readiness and business commands remain available;
   business history, mandatory SQL audit and idempotency receipt commit together.
   Actual stopped source OPA: readiness reports 503, remote reads fail closed,
   no payload/fence crosses, and durable retryable outboxes drain after restart.

Earlier failed startup/test/browser attempts are retained as diagnostic evidence;
none were converted into passes by skipping gates or weakening assertions.

## Reproduce

From the PR checkout on a Docker-capable development host:

```bash
# Optional isolation; use a different loopback port if another lab is running.
export COMPOSE_PROJECT_NAME=sfl-acceptance
export LAB_PORT=8080
./lab doctor
./lab up
./lab test
./lab faults
./lab generate --count 5 --scenario sg-uk-no-us
./lab business --command open_holding --count 2
./lab migrate --reset
./lab telemetry
```

In this managed proxy/private-umask workspace, startup additionally used:

```bash
export LAB_BUILD_CA=/etc/ssl/certs/ca-certificates.crt
find poc/policies infra/grafana -type d -exec chmod a+rx {} +
find poc/policies infra/grafana -type f -exec chmod a+r {} +
chmod a+r poc/otel-collector.yaml infra/loki.yaml
./lab up
```

For the optional browser gate, **after** the suite, without concurrent manual edits:

```bash
python3 -m pip install playwright==1.62.0
python3 -m playwright install --with-deps chromium
# Installed system Chromium may instead be selected with CHROMIUM_PATH.
python3 poc/tests/browser_acceptance.py
```

The browser gate resets only the isolated migration fixture and adds synthetic
records. `./lab faults` briefly stops actual OPA/Collector dependencies and restores
them on exit. Local screenshots/logs go under ignored `artifacts/`. The GitHub
Actions workflow captures startup, complete gate output, faults, browser screenshots
and container diagnostics as `lab-evidence`; inspect the run attached to the exact
PR commit. Workflow configuration alone does not prove it ran or passed.

Working gateway routes:

| URL | Purpose |
|---|---|
| `http://localhost:8080/` | Portal |
| `http://localhost:8080/monitor.html#monitor` | Movement monitor |
| `http://localhost:8080/monitor.html#generator` | Record generator |
| `http://localhost:8080/monitor.html#services` | Business commands |
| `http://localhost:8080/migration.html` | India relocation |
| `http://localhost:8080/design/index.html` | Architecture |
| `http://localhost:8080/design/adr-register.html` | ADRs |
| `http://localhost:8080/api-docs` | API explorer |
| `http://localhost:8080/grafana/d/sovereign-logs` | Provisioned log dashboard |

Only the gateway has a published port, bound to `127.0.0.1`. A remote workstation
must use an SSH tunnel as described in [DEVELOPMENT.md](DEVELOPMENT.md).

## Recorded image identities

Observed pulled image digests (amd64 run):

| Compose pin | Repo digest SHA256 |
|---|---|
| CockroachDB v25.4.0 | `cbc618f33d48a511f2db03e61e9215d17b372e19075b6e97c400b1942fb90146` |
| OPA 1.9.0 | `bd7e1216865884be8095726fb80282ece2f6b531883bc86f9f8917f2fc52de61` |
| Collector 0.140.0 | `6852803128c97a37fd2bafb989a04a10e3af920737d8eee998eefdfcebc698be` |
| Loki 3.5.7 | `0eaee7bf39cc83aaef46914fb58f287d4f4c4be6ec96b86c2ed55719a75e49c8` |
| Grafana 12.2.0 | `74144189b38447facf737dfd0f3906e42e0776212bf575dc3334c3609183adf7` |

The Collector image tagged 0.140.0 reports binary version 0.140.1 in startup logs;
record both tag/digest and observed version. Built API/gateway image IDs depend on
source contents. Python's base tag remains `python:3.12-slim`; these pins do not
establish vulnerability approval or licensing suitability for a bank pilot.

## Before a pilot

- Exercise actual CockroachDB termination, partitions, serialization retries,
  recipient commit/source-ack crash gaps and migration fence/activation crash
  boundaries. Add connection pooling, bounded retries and restore-in-quarantine tests.
- Replace single-process authority with regional authenticated services, durable
  controller ownership and distributed monotonic fences; test competing writers.
- Implement normalized-table migration, pending federation/outbox handoff and a
  resilient lawful directory; the isolated migration control row still depends on SG.
- Establish physical placement, regional HA, backups, TLS, identity/approval roles,
  key custody, lawful telemetry sinks and immutable/complete audit evidence.
- Measure realistic skew, WAN effects, foreground/bulk resource isolation and
  50M-party/100M-relationship workload targets. This fixture is not a scale benchmark.
- Track live purge separately from MVCC/GC, WAL, backups, retained audit and archives;
  resolve retention/hold/deadline exceptions. COMPLETE is not backup erasure.
- Complete keyboard/accessibility, mobile interaction and supported-browser reviews.
