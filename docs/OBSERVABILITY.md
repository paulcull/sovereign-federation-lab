# Application logging and observability

[Lab README](../README.md) · [Development guide](DEVELOPMENT.md) · [ADR-0008](adr/ADR-0008.md)

## Run and view

Run `./lab up`, then open `http://localhost:8080/grafana/d/sovereign-logs`.
Use the **Sovereign Lab · Application Logs** dashboard or Grafana Explore with the
**Sovereign Lab Logs** data source. Generate traffic in the monitor or use
`./lab generate --count 5 --scenario sg-uk-no-us`. Refresh the dashboard after a few seconds.
For a changed LAB_PORT, use that port in the URL. Remote development uses the same
SSH tunnel as the portal. Grafana is a local anonymous Viewer; Loki and the
Collector have no published host ports. This is not production authentication.

`./lab telemetry` makes a real API request, obtains its generated `X-Trace-ID`,
queries Loki for that exact request, and checks Grafana through the gateway.
Both `./lab up` and `./lab test` run this gate. Ordinary API health checks do not
depend on telemetry delivery. A telemetry gate failure requires investigation;
it must not be reported as a successful logging deployment.

## Pinned releases and upgrades

The 16 October 2026 release check selects Grafana **13.2.4**, Loki **3.7.8**
and OpenTelemetry Collector **0.163.1**, with immutable manifest digests in
`compose.yaml`. Loki 3.6.18 has a later publication date but is a patch on the
older 3.6 line; this upgrade retains the latest stable 3.7 release.

Grafana 13 is a major-version upgrade. Before starting it against an existing
Grafana volume, stop the Grafana service and copy its complete persisted state
into a private rollback directory. The local validation keeps that stopped-service
copy under ignored artifacts. Rolling back requires the previous image together
with its pre-upgrade state, rather than opening a migrated database with the old
binary. Grafana UI metadata is separate from CockroachDB business and audit data.

The gateway resolves Docker service names again when their addresses change.
`python3 poc/tests/gateway_dns_acceptance.py` moves the real Grafana container to
a different address, verifies access through the unchanged gateway process, and
restores its original address. Run it after startup and separately from mutable
fault suites. This protects image replacements from stale upstream-address 502s.

A newer version does not establish a security pass. The Collector candidate scan
removes its four previously blocking findings, while Grafana 13 includes bundled
plugin binaries with additional findings. The complete image audit and
[dependency-security disposition](DEPENDENCY_SECURITY.md) govern the remaining
exceptions; no additional acceptance follows from an image upgrade.

Allow additional disk headroom for a major image upgrade with Docker's VFS
driver. The recorded workspace pull first failed with insufficient extraction
space, then succeeded after superseded images were removed. Its final roughly
2.10 GB free remains below the native recovery rehearsal's 2.70 GB requirement;
that local gate remains blocked rather than lowering the existing 8% guard.
The complete native recovery gate remains mandatory in GitHub Actions. See the
[upgrade evidence](security/observability-upgrade-2026-10-16.json).

## Signal paths

| Signal | Implemented path | Storage / limits |
|---|---|---|
| Application logs | API/worker → OTel Python logs SDK → OTLP HTTP Collector → Loki → Grafana | Loki named volume; 7-day asynchronous retention |
| Traces | API → OTLP HTTP Collector → debug exporter; main harness also writes local JSONL | No searchable trace backend yet |
| Business audit | Local business/control transaction → CockroachDB | Separate from diagnostics; no audit replacement or WORM claim |
| Container diagnostics | Docker stdout/stderr | `./lab logs`; not collected into Loki |
| Metrics | No metrics backend added in this change | Prometheus/alerts remain pilot work |

Only the dedicated application logger is exported. It emits JSON request-completion,
worker-retry and service-lifecycle events. Request events contain a route template,
a bounded HTTP method, status, duration, timestamp and locally generated trace/span IDs.
Neither bodies, headers, query strings, raw paths, party/entity keys nor exception
messages are included. Unknown routes are recorded as `unmatched`.
Incoming trace headers and baggage are not propagated. Existing detailed policy
spans are unchanged; this log-minimisation test is not a review of every trace attribute.
Uvicorn raw access logging is disabled in the container. Runtime exceptions can
still appear in diagnostic stderr, which is outside this Loki pipeline.

## Search examples

The optional customer MDM pilot exports the API adapter and recipient-peer
events through the same Collector/Loki pipeline. Query
`{service_name="sovereign-pilot-api"}` for system and experience calls or
`{service_name="sovereign-pilot-peer"}` for recipient events. Each process
generates its own trace context; caller headers/baggage are not trusted or
propagated. Payload-free local trace evidence remains diagnostic, and mandatory
MDM/business audit stays in the owner's SQL transaction.
`./lab pilot-faults` verifies Collector-outage isolation and log recovery.


```logql
{service_name="sovereign-poc-harness"}
{service_name="sovereign-poc-harness"} | json | level="ERROR"
{service_name="sovereign-poc-harness"} | json | route="/api/health/live"
{service_name="sovereign-poc-harness"} | json | trace_id="COPY_X_TRACE_ID_HERE"
```

The standalone migration entry point uses `service_name="sovereign-migration-poc"`.
Trace IDs are correlation fields, not index labels. No Tempo/Jaeger link is implied.
The two dashboard panels show all application events and server failures/retries.

## Failure, performance and retention

The SDK batches up to 256 records from a bounded 2,048-record in-memory queue.
The Collector uses a 128 MiB memory limiter, one-second batching, a bounded export
queue and finite retries. Loki downtime does not synchronously block business
writes; saturation, process crashes or prolonged outages can lose diagnostic logs.
There is no disk-backed Collector spool or exactly-once delivery guarantee.
The OTel SDK still uses a small synchronous enqueue/format step on each request.

Loki uses single-process TSDB v13 storage on a named volume. The Compactor performs
7-day retention asynchronously; it is not an exact expiry-time deletion guarantee
or disk-capacity cap. Monitor disk consumption. `./lab down` preserves the data;
`./lab reset --confirm-synthetic-lab` also deletes Loki and Grafana volumes.

Grafana's own UI metadata uses its default internal database on the Grafana volume;
it does not hold or substitute for CockroachDB business data.

One local stack contains synthetic examples from all simulated stores. This does
not demonstrate sovereign regional telemetry isolation. A pilot must deploy sinks
inside each approved residency boundary, introduce authentication/TLS, harden and
scan image pins, set quotas and retention, review correlation identifiers, and
separately prove audit completeness. No Docker socket is mounted for log scraping.

## Production measurements and alert acceptance

The following signals and alerts are release requirements, not dashboards already
provisioned by this lab. Agree the numerical thresholds with each service owner
before a regional load/failure run; the small fixture supplies no production SLO.

| Signal | Separate measurements | Required failure drill |
|---|---|---|
| Request service | Attempted requests, success/error counts and p50/p95/p99 by bounded operation and cell; rejected/time-out requests remain in the denominator | Pause a peer while issuing unrelated owner traffic; demonstrate bounded impact and recovery |
| Authority | Dependency availability, revision/fence age and time from accepted restriction to enforced recipient guard | Partition authority; verify scoped fail-closed behaviour and alert before the agreed deadline |
| Delivery | Oldest pending age, bytes, attempts, quarantines and recipient acknowledgements | Stall one destination, exceed one worker batch, and verify healthy destinations progress |
| Reconciliation/purge | Checkpoint age, work remaining, deadline and actual physical-row confirmation | Stop/restart reconciliation; read denial must not report physical deletion complete |
| SQL/audit | Transaction retries, contention, commit failures, audit reconciliation gaps and disk headroom | Exhaust a bounded dependency budget; mandatory audit failure must prevent its business commit |
| Infrastructure/identity | Certificate expiry, identity revocation failures, policy/schema incompatibility, node health and storage | Rotate keys, introduce incompatible versions and fail a node; exercise the responsible runbook |
| Diagnostic pipeline | Queue saturation, dropped/export-failed logs and sink capacity | Stop Collector/Loki; business/audit durability remains independent and lost diagnostics are reported |

Keep metric labels bounded: operation, cell, work class and outcome. Customer,
party, relationship, request-reference and raw URL values do not belong in metric
labels. Customer-linked audit and protocol receipts require approved regional
storage and retention even when payload fields have been removed. Hashing such
identifiers does not establish anonymity or an unrestricted export right.

An alert is accepted only after an injected fault reaches its assigned on-call
route and the operator executes a reviewed recovery procedure. Record the
acknowledgement and recovery time, not merely a screenshot of a firing rule.
Measure recovery headroom while foreground traffic continues; a draining backlog
after all business traffic stops does not establish a sustainable operating point.
See the [production release matrix](PRODUCTION_READINESS.md) for required inputs
and [work isolation](../WORK_ISOLATION.md) for the proposed capacity boundaries.

Retain SQL audit independently from diagnostic logs. Production needs protected
regional retention and an independent reconciliation of accepted requests,
committed mutations, delivery/fence receipts and applicable disposal evidence.
The same database account being able to alter both business and audit tables is
not tamper-resistant evidence. None of Loki retention, sampled traces or an
application success counter substitutes for that reconciliation.

## Verification and cloud development handoff

The authoring checks exercised the pinned Python SDK against a real local OTLP HTTP
receiver, protobuf decoding, trace correlation, sensitive-data canaries, unmatched
routes, server failures and exporter failure isolation. The subsequent Docker run
passed API → Collector → Loki delivery with matching request-header/log/span trace IDs,
Grafana provisioning and rendered dashboard access. A real Collector outage also
preserved business commits, mandatory CockroachDB audit and request receipts.
See [container acceptance](CONTAINER_ACCEPTANCE.md) for commands, images and limits.
The GitHub Actions workflow repeats the container and browser gates.

A cloud Codex session can work from this private repository once repository access
is enabled. It is useful for ongoing implementation and reviews. It only resolves
the outstanding acceptance gap if that environment supports a Docker daemon and
Compose; otherwise use a development VM or the GitHub Actions workflow. Start with:

```text
Read README.md, docs/OBSERVABILITY.md, TESTING.md and docs/adr/README.md.
Run ./lab doctor, ./lab up and ./lab test on a Docker-enabled host.
Fix observed failures without bypassing CockroachDB, OPA, Loki or test assertions.
Record container/image versions and evidence. Do not claim HA, residency compliance,
load capacity or retained-data erasure from this single-host synthetic lab.
```

## Configuration references

- [Loki native OTLP ingestion](https://grafana.com/docs/loki/latest/send-data/otel/)
- [Loki HTTP API](https://grafana.com/docs/loki/latest/reference/loki-http-api/)
- [Loki retention](https://grafana.com/docs/loki/latest/operations/storage/retention/)
- [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [OTel Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/)

The pinned SDK is 1.36.0 and uses its `sdk._logs.LoggingHandler`; newer documentation
may use the separate logging-instrumentation package. Image pins are reproducible
lab choices, not a claim that they are the latest security-approved releases.
