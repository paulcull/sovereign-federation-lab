# ADR: isolate operational placement from policy reconciliation

Status: proposed production design; executable browser service-budget model and admission specification. The v3 CockroachDB/OPA harness still has its original serial worker and process lock. This change does not implement distributed scheduling or production policy fences.

Decision: a bulk policy change cannot be placed ahead of operational events in the same FIFO. Separate three work classes at source relay, transport, workers, recipient admission and database connection/concurrency budgets. Queue priority alone does not reserve CPU, disk or locks.

| Lane | Work | Resource contract |
|---|---|---|
| Authority guard | Scoped policy epoch, deny overlay, grant activation, lease/watermark, durable fence receipt | Small bounded transactions and reserved workers/connections; control-rate admission and scope isolation. No record scans or payload backfills. |
| Operational | New or changed eligible business records; dependency-safe approved deltas | Reserved throughput, per-entity fairness and bounded aggregate transactions; fresh authority at export/import/read. |
| Reconciliation | Historical grant backfill, physical purge, reindex/rebuild, reconciliation and migration | Rate-limited resumable batches; separate pools, byte/IOPS budget and checkpointed cursors. Pause or throttle bulk work under foreground pressure; meet separate deletion deadlines. |

## Transactions and status

The local business transaction commits bounded business changes, relevant resource versions, operational outbox intent, audit intent and idempotency receipt. OPA evaluation happens on verified facts before the transaction; the transaction validates the relevant versions/expiry and re-evaluates after a conflict. No WAN or broker call belongs in the retry closure.

The policy transaction writes desired policy, monotonically increasing scoped authority revision, guard-outbox intent, one reconciliation cursor/job and audit intent. It does not scan affected rows or enqueue millions of record jobs. Applicable restrictions take effect at the source immediately on commit. The destination receives a separate durable fence; remote enforcement requires a fence acknowledgement or expiration of its approved authority lease. Policy publication alone cannot prove instantaneous remote enforcement.

For ordinary grants, prepare the compatible rules and destination facts, activate authority, then allow fresh operational records with parent closure before historical backfill finishes. Until activation, new rights are unavailable. Historical completeness remains an explicit readiness attribute. A business workflow that requires a complete portfolio may wait for its own readiness barrier; unrelated operations continue.

For restrictions, stop new exports at source and invalidate affected cached decisions. Send small guard events to permitted existing holders. Recipient reads/imports must validate current facts and fences even while physical copies remain. Any already-in-flight exposure is governed by the stated acknowledgement/lease contract; do not describe source commit as simultaneous worldwide enforcement. A generic rule change requires compatible bundle readiness or targeted denial. Large arbitrary per-record exception sets must be staged as verified immutable regional facts before a scoped revision pointer is activated; a cheap epoch does not make distributing millions of facts free. Never roll authority revisions back with a code rollback.

Return `202 Accepted` with `policyRevision`, `sourceEffectiveAt`, per-destination `guardStatus`, `readiness`, and a separate `reconciliation`/`purge` status. Accepted, enforced and physically converged are different milestones. An offline receiver remains pending; retained backups/audit are outside live purge acknowledgement.

## Cross-lane race rules

Independent queues have no total order. Carry event UUID, owner/entity/resource key, data version, authority revision, home epoch, placement version, schema version and destination-bound payload/field-set digests. Every export is constructed using current authoritative facts, not just the policy snapshot captured when it was queued.

The recipient validates trusted identity, compatible rule bundle, current authority freshness, contiguous applied revocation watermark and placement before making a payload visible. Validation and projection/inbox/manifest update share a local transaction or an equivalent proven atomic fence. Missing/newer facts park only affected work; no spin-retry loop or global FIFO blockage. Never treat a client-provided revision as evidence of current authority.

Resource `data_version` orders data independently of policy authority. A historical snapshot cannot replace a newer operational record. Re-evaluate or rebuild obsolete jobs from current source state. A purge transaction compares its authority and manifest versions, preventing an old purge from deleting a newly regranted projection. Coalesce superseded desired-state jobs while preserving audit evidence and mandatory revocation obligations. Do not coalesce business events that require every transition to be observed.

Partition ordering by owner + aggregate/resource + destination, with per-entity quotas and independent destinations. Large entities get many partitions. Grant parent closure may need a bounded point read or small manifest; never send the operational record to the end of a historical scan. Highly contended records still serialize. Shared disk and lock contention require measured admission control; separate queues are not physical isolation by themselves.

## Capacity and observability

Illustration: total 1,000 work units/s, 50 guard, 700 operational and 250 bulk; 500 operational arrivals/s; a 20,000-unit policy batch at t=5s. The comparator shares 950 units/s between operational and bulk FIFO work while reserving the same 50 for guard work. Both have identical total capacity. Each job costs one unit; transport adds an assumed fixed 60ms. Guard transmission assumes 180ms plus 20ms reserved service. Reservations are explanatory assumptions, not node sizing or recommended production percentages.

This deterministic model excludes contention, retries, bytes, bursty arrival, cache behaviour and real OPA/SQL costs. Foreground arrivals stop at 60s, but their calculated completions may extend beyond it. p95/p99 cover all operations issued from t=5s to 60s and include their eventual completion times. Backfill remains pending when it exceeds the displayed horizon. At 800 operational arrivals/s, the 700-unit operational lane overloads: isolation does not create capacity. No idle-capacity borrowing is modeled; a production scheduler may lend spare capacity through bounded interruptible batches while preserving reservations.

Monitor each lane separately: incoming work/bytes, oldest age, completion rate, retry/quarantine rate, reserved capacity use and affected-scope authority lag. Display operational delivery p95/p99 independently of policy convergence and physical purge. Add regional OTel span attributes `work.class`, `operation`, `cell` and bounded outcomes; keep customer identifiers out of metrics. Reserve audit capacity and archive regionally. Alert on revocation deadline separately from bulk lag. Use scopes sufficiently small that one stalled authority partition does not close an entire store.

## Extension points and engineering tasks

1. `PolicyAuthority.activate(change, expectedRevision)` atomically commits facts, guard intent and a reconciliation cursor. Activation is scoped; source fencing and destination readiness are explicit.
2. `OperationalOutbox.append(tx, aggregate, version)` stays inside the local business unit of work. Use distinct outbox tables/changefeeds or independently claimable lanes so a bulk FIFO cannot block relay.
3. `GuardRelay` / `OperationalRelay` / `ReconciliationScanner` use separately budgeted pools. Regional Kafka topics are per work class/partition family, not per customer. Raw outbox payloads remain in their home region.
4. `AdmissionGate` validates current facts and persists a monotonic fence; exporters, importers and query services share the contract. Stale queued events must reauthorise.
5. `Reconciler.step(cursor, budget)` issues bounded latest-state deltas with dependency closure, CAS manifest validation and resumable checkpoints. Purge gets a deadline budget without bypassing current authorisation.
6. `CapacityGovernor` reserves guard/operational capacity, limits bulk bytes/concurrency/transaction duration and exposes per-destination/entity fairness. Begin with explicit caps; tune only using measured contention and IOPS.

## Acceptance scenarios

- Sustain agreed operational peak while granting/narrowing a table over 100M relationships; request-path work must be independent of rows affected. Check attempted-request errors and p95/p99 by cell.
- Compare baseline versus bulk-policy-load performance under equal physical capacity. Initial engineering gate: both meet existing SLOs and operational p99 increases no more than 10%; this is a target requiring calibration, not an achieved result.
- Pause reconciliation: new eligible records still arrive; existing UK contacts are denied after the guard contract while purge is pending.
- Pause guard transport: scoped leases expire fail-closed; unaffected entities/destinations continue. Confirm policy API never reports remote enforcement early.
- Reorder/duplicate queues, replay an old grant after revoke, deliver old backfill after a fresh update, and deliver an old purge after a new grant. No resurrection, rollback or deletion of a newer grant.
- Flood policy submissions, kill a lane worker and saturate disk. Verify admission limits, fairness, separate quarantine and bounded control writes. Under true resource exhaustion, report backpressure rather than promise zero impact.
- Test grants that need missing parents, bundle incompatibility, schema changes, source/receiver crash around commits, and restores in quarantine with current fences.

Run the small deterministic specification with `node scale/isolation_test.mjs`. It does not replace OPA parity tests, CockroachDB integration or a concurrency/fault benchmark.

Primary references: [OPA bundle distribution](https://www.openpolicyagent.org/docs/management-bundles) is eventually consistent; [CockroachDB changefeeds](https://docs.cockroachlabs.com/docs/stable/changefeed-messages) are at-least-once and do not supply transaction-wide ordering.
