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
