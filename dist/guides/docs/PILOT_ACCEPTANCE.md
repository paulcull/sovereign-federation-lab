# Customer MDM pilot acceptance — 14 October 2026

This records execution against real containers, synthetic customers and the
existing operational tables. It is single-host integration evidence, not bank
approval, physical residency compliance, production HA or a capacity benchmark.

## Environment and reproduction

The workspace has a four-CPU quota and 16 GiB memory limit, Docker 28.4.0 and
Compose 2.40.3. About 12 GB disk was free initially; repeated builds consumed space.
Four separate CockroachDB v25.4.0 single nodes and real OPA processes were used.
The additive profile has 19 running containers.

```bash
./lab doctor
./lab pilot-up
./lab pilot-test
./lab pilot-faults
LAB_PILOT=1 ./lab test
python3 poc/tests/pilot_browser.py
python3 design/tests/reader_browser.py
LAB_PILOT=1 ./lab faults
python3 poc/tests/browser_acceptance.py
```

The managed package proxy requires its trusted CA during image builds:
`LAB_BUILD_CA=/etc/ssl/certs/ca-certificates.crt ./lab pilot-up`. This uses the
existing build-secret overlay and preserves TLS verification. Ordinary Docker
installations omit that variable. Run mutable suites sequentially: fault tests
deliberately stop dependencies.

## Observed results

| Gate | Result |
|---|---|
| Pilot startup | Passed: real owner/API, three peers and loopback gateway; readiness checks local SQL/OPA. |
| System and experience APIs | Passed: source reference over business.party, atomic audit/outbox/receipt, replay/stale conflicts, owner routing and minimum-version reads. |
| Placement and exclusions | Passed: exact three-field US party minimum; permitted UK relationship/contact; no excluded US relationship payload or customer-linked recipient artefacts; processing-location and cross-store spoof rejection. |
| Consent and admission | Passed: guarded reads, actual UK live-row purge/restore, mTLS/credential checks and current-envelope tamper rejection. |
| Actual pilot outages/restart | Passed: stopped peer, source/recipient OPA and Collector; durable owner audit, pending delivery, affected fail-closed calls, recovery and persistent identity/replay receipts after owner/API/peer restart. |
| Pilot logs | Passed: API-generated response trace ID matches its exported span and payload-free Loki event through Collector. |
| Preserved complete lab | Passed with pilot enabled: SQL placement/exclusions, normalized graphs, India snapshot/catch-up/validation/fencing/cutover/stale writes/live cleanup, restart authority, gateway, Collector span receipt and Grafana/Loki. Original 45-second settlement gate retained. |
| Live MDM browser | Passed: creates a customer and relationship, reads UK contact, executes routed update, reads fresh version, verifies exact US minimum and relationship denial; no page errors/overflow at 375/768/1440 px. |
| Microsite reader browser | Passed: nine-page journey, 28 components, evidence links and mobile navigation/layout; no page errors. |
| Preserved actual outages | Passed with pilot enabled: Collector outage leaves business row/audit/receipt durable; source OPA outage prevents export/read and leaves retryable intents; real dependency restart drains outboxes. |
| Original live browser | Passed: generated monitor record moves SG to UK, US absent; India snapshot, concurrent changes, validation invalidation, source fencing, UK work during fencing, cutover, stale-write rejection and cleanup. |
| Source packaging | Passed: archive integrity, MDM source included, private pilot directories and certificate keys excluded; checked both Git release and mounted-source packaging. |
| Authorization review regressions | Passed against actual APIs, SQL and OPA: resource/table processing exclusions, filtered command/replay metadata, absent/null contact values, source field narrowing without a version bump and recipient field narrowing before storage mutation. Catalogs/rules restored after each probe. |

Assertions live in `poc/tests/pilot_acceptance.py`,
`poc/tests/pilot_fault_acceptance.py` and `poc/tests/pilot_browser.py`.
`poc/tests/pilot_review_acceptance.py` is included in `./lab pilot-test` and
exercises the review findings with temporary real policy changes.
Actions retains the original lab/fault/browser gates, then exercises this profile.
Its `lab-evidence` artifact excludes private identities/certificates.

## Actual failures corrected

- UUID outbox events were not JSON encodable: serialize the wire event explicitly.
- Peer HTTP held the writer lock: deliver outside that lock and SQL transaction;
  actual peer-loss tests verify owner writes and audit remain available.
- Nginx cached replaced container addresses: bounded Docker DNS resolution;
  process-restart tests verify the live route recovers.
- Duplicate current-state intents and monitor round trips delayed settlement:
  coalesce by scope/recipient with cutoffs, retaining business audit/receipts, and
  batch monitor queries by typed table. Keep the original 45-second assertion.
- Optional startup index backfill stalled: removed the optimisation and cancelled
  only that schema-change job; no business rows were deleted.
- Unbounded Loki search timed out: use the last 120 seconds within the same
  required trace-match deadline.
- Root-owned artifacts blocked host browser writes: run tools as the invoking UID/GID.
- Review exposed missing table/resource processing checks, hidden metadata in
  command/replay receipts, incomplete source/recipient field-list enforcement,
  missing contact values and retry starvation. Add layered geography checks,
  scoped response receipts, source read-field fences, recipient import-field
  checks, command validation and attempt-count retry rotation. Complete receipts
  remain in SQL; original settlement and supersession cutoffs remain unchanged.
- The added 15-plus-group peer-loss probe exposed first-contact global metadata
  rewrites and repeated transport timeouts. Scope-only contact/expiry writes and
  one failed transport probe per store/batch remove those delays while preserving
  durable pending intents and the test's 45-second healthy-peer deadline.

A premature browser attempt overlapped a dependency outage and failed. Final
acceptance runs these suites sequentially; that failed attempt is not a pass.

## Entry points and limits

On the **lab host**: `http://localhost:8081/` is the MDM console;
`http://localhost:8081/pilot/api-docs` is its API contract;
`http://localhost:8080/monitor.html` shows movement;
`http://localhost:8080/grafana/d/sovereign-logs` shows logs. Forward both loopback
ports with SSH for a remote host. A static architecture preview does not host
these APIs. Follow [the runbook](PILOT.md) for private role credentials.

Exact source-reference matching is implemented. Fuzzy matching, stewardship,
survivorship and merge/split remain future work. Normalized MDM rows do not migrate
with the separate India fixture. Local test identities, insecure private SQL/OPA
and one coordinator remain development limitations. Bank IdP/delegation, approved
regions, scoped SQL/TLS, policy readiness/fencing contracts, normalized migration,
load/retention/restore evidence and governance sign-off remain required.
