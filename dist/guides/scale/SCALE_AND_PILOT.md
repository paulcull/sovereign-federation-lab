# Scale assessment and PoC-to-pilot plan

11 October 2026. Model version 1, seed family 20261011–20261013.

## Recommendation

The architecture can be engineered for 50M parties / 100M relationships, but the current PoC cannot be extrapolated to that scale. First remove full-owner scans, the global process lock, unbounded snapshots and per-recipient full-graph replacement. Keep the regional ACID boundary, explicit sovereignty rules and transactional outbox. The dominant risks are hot keys, fanout, insufficient recovery capacity, synchronous WAN authorisation and unbounded retention.

The proposed service targets are engineering acceptance goals under the workload envelope below, not measured database guarantees. There is no CockroachDB benchmark or loaded 100M-row database in this assessment.

## Proposed latency targets

| Operation | p95 | p99 | Boundary |
|---|---:|---:|---|
| Regional party lookup | 30 ms | 75 ms | Regional gateway ingress to response; approved indexed ID lookup; no WAN authority call |
| Bounded relationship view | 75 ms | 150 ms | Regional gateway to response; at most 50 rows / 32 KiB; keyset page history/holdings |
| Local business commit + outbox | 100 ms | 250 ms | Regional gateway to durable local success; bounded transaction; does not wait for remote projection |
| Approved federation visibility | 2000 ms | 5000 ms | Owner commit to recipient query visibility; healthy WAN/cells; eligible destinations only |
| Revocation enforced at recipient | 1000 ms | 5000 ms | Owner restriction commit to denied reads; priority epoch channel plus max 5s authority lease incl. clock budget; proposed design |
| Live projection purge acknowledgement | 5000 ms | 30000 ms | Healthy recipient; retained audit/backups excluded; outage purge reported as pending |

Measure each operation separately per region and legal entity at gateway ingress to completion. Do not blend reads and writes or hide slow operations in a global aggregate. Search, exports, full party portfolios, history scans and cross-home writes need separate budgets. Responses larger than 50 rows/32 KiB must be paged. Report error/timeouts alongside percentiles, using attempted requests as the denominator; the target success error rate is <0.1% excluding expected policy denials. Instrument revocation and purge with source commit and recipient receipt timestamps, with a measured clock-error bound.

A strict remote read which consults an overseas authority cannot meet the same local-read target. In the illustrative 180 ms WAN RTT case, relationship-read p99 rises to 309 ms. Choose either strict source-authorised reads with a WAN budget or locally enforced, versioned facts with a bank-approved bounded revocation window. This assessment proposes a maximum 5 seconds including clock tolerance; it does not implement or approve that trade-off.

## Workload and method

- Population: 50M parties, 100M relationships and 125M party participation edges. Average two primary relationships per party, with secondary signatory/owner roles bringing participation to 2.5 links per party.
- Normal traffic: 10,000 reads/s and 1,000 business writes/s globally. Design peak: 30,000 reads/s and 5,000 writes/s. These are planning assumptions, not inferred from population size. Regions receive 45% SG / 40% UK / 15% US traffic; the skew scenario changes this to 70% / 20% / 10%.
- Relationship sharing averages 0.8 remote recipient copies. Global party minimums add two remote physical copies, only where policy permits. No automatic grant to all 30 legal entities is assumed.
- 16 scenarios, three deterministic seeds each. Open Poisson arrivals pass through gateway, OPA and shared database service queues; independent lognormal service demands, cache misses and retries create tails. Background delta imports share DB capacity. A hot-key case adds a single serialized resource.
- 17,280,000 foreground events and 2,218,221 background events were simulated. Every run has 360,000 foreground events; its duration therefore depends on rate. At the full design peak this is roughly ten seconds, including 20,000 warm-up arrivals. Stable-case quantiles have substantial samples; overload results describe a finite growing backlog, not a long-run steady state. A 60-minute/24-hour physical load test remains necessary.
- Four cardinalities (1M/10M/50M/100M relationships) change row counts, assumed cache/depth cost and proportionately scaled traffic. They reuse the same full-scale synthetic capacity; they do not benchmark four differently sized clusters.
- The reported p95/p99 are medians of three run-specific percentiles; minimum/maximum p99 across seeds shows random variation, not a statistical confidence interval or calibration uncertainty.
- No measured DB, storage, TLS, compaction or cross-region network times calibrate this model. Database service medians are 3/10/14 ms for party/relationship/write, with explicit cold/retry terms in assumptions.json. Effective DB admission slots are 192/192/96; these are queue-model parameters, not CPU counts or a claim about specific hardware.
- Assumed local OPA request median 1.1 ms uses a small fact-based read decision; full resource-batch policy evaluation is asynchronous. The observed microbenchmark below gives context but is not a throughput calibration.

## Results

| Scenario | SG relationship p99 | Maximum DB demand / capacity | Interpretation |
|---|---:|---:|---|
| 100M / normal workload | 60 ms | 0.27× | Stable under stated assumptions |
| 100M / design peak | 61 ms | 0.88× | Stable under stated assumptions |
| 100M / 1.25× peak | 796 ms | 1.10× | Finite overloaded queue; not a sustainable p99 |
| 100M / 1.5× peak | 2151 ms | 1.32× | Finite overloaded queue; not a sustainable p99 |
| 100M / 2× peak | 3852 ms | 1.55× | Finite overloaded queue; not a sustainable p99 |
| 100M / cold cache + slower DB | 5707 ms | 1.57× | Finite overloaded queue; not a sustainable p99 |
| 100M / 70% Singapore traffic | 3491 ms | 1.35× | Finite overloaded queue; not a sustainable p99 |
| 100M / one AZ capacity lost | 3220 ms | 1.33× | Finite overloaded queue; not a sustainable p99 |
| 100M / 50% extra DB capacity | 61 ms | 0.59× | Stable under stated assumptions |
| 100M / inline high-degree fanout | 61 ms | 0.91× | Stable under stated assumptions |
| 100M / 5% of writes hit one party | 33259 ms | 0.90× | Finite overloaded queue; not a sustainable p99 |
| 100M / extra capacity then AZ loss | 61 ms | 0.88× | Stable under stated assumptions |
| 100M / synchronous remote authorisation | 309 ms | 0.88× | Stable under stated assumptions |

At normal peak the busiest DB pool reaches 88% modeled demand. That is too close to saturation for a bank pilot exit. A 25% traffic increase pushes the same capacity above 100%. Adding 50% effective capacity reduces modeled peak demand to about 59%; losing one-third of that enlarged capacity returns it to roughly 88%. Plan to run at **≤60% of measured limiting capacity** during design peak if the same peak must survive an AZ loss. CPU, disk, network, locks and policy workers each need their own headroom measurement. This is a capacity reserve requirement, not proof that 50% more nodes produces 50% more throughput.

The hot-key scenario can be unstable even if aggregate DB demand is below one. A repeatedly updated party/resource epoch is still a serial resource: coalesce allowed updates, bound concurrency, isolate the hot key, and reject or queue excess work without blocking unrelated customers. Inspect p99.9 and per-key rates, not only fleet p99.

## Storage and bandwidth

The central model has **2.40 billion source business rows**, **1.75 TB logical data** including projections, controls and seven days of audit, **15.0 TB used after overhead and replication**, and **25.0 TB provisioned at 60% fill** across the three regions. Decimal TB is used throughout. This includes 90 days of contact history, assuming 10% of normal writes create history rows.

Overhead assumptions are explicit multipliers: secondary indexes 1.7×, key/encoding/storage overhead 1.35×, MVCC allowance 1.25×, RF=3 within each regional cluster; provisioned = used / 0.60. They need calibration from real schemas and update churn. No compression saving is assumed. The nine storage sensitivity cases vary history retention (30/90/365 days) and remote copies (0.3/0.8/1.5). Backup retention, audit archive, bus disks, replicas outside this three-region design, disaster recovery and future growth are additional.

At 1,000 normal business writes/s, two 512-byte audit events per write generate **88.5 GB/day** and **32.3 TB/year** before archive compression/redundancy. If 5,000 writes/s becomes the sustained rate, audit/history growth is five times larger. Do not treat peak as the daily average or retain the full audit stream in the hot OLTP cluster indefinitely.

The synthetic degree distribution puts 24.4% of participation edges on 0.1% of parties. With 20% of change events sampled in proportion to degree, the average changed party touches 33.9 relationships and p99 touches 610. A serial hook costing an assumed 0.6 ms per scope adds 366 ms at p99 of **party changes**, even though all-write p99 can conceal that low-frequency path.

Whole-graph, repeated-recipient propagation produces about **17,160 jobs/s** and **103.0 MB/s** at design peak. A proposed canonical resource-delta model reduces this to **4,600 jobs/s / 4.1 MB/s**. This approximately 25× payload reduction combines assumed payload sizes (6,000 → 900 bytes) and fanout deduplication. It is not a measured network saving. Delta messages alone do not remove per-relationship fanout; the physical shared-resource and recipient-authorisation design must change too.

A 24-hour outage retaining the optimized 4,600 events/s at 900 bytes needs about 358 GB of payload before bus indexes, broker replication, protocol overhead or safety margin. Regional retention must remain policy-compliant. Throughput also needs source/recipient OPA and DB capacity, not just WAN bandwidth.

## Recovery

A 30-minute UK receiver outage accumulates about 4.97 million jobs at the modeled peak route rate. Recovery while continuing new work takes:

| Available service after return | Drain time |
|---|---:|
| 1.1× incoming rate | 300 minutes |
| 1.5× incoming rate | 60 minutes |
| 2.0× incoming rate | 30 minutes |

These are fluid queue calculations with constant arrivals/capacity and no coalescing. Keep priority revocation/epoch traffic separate from data backfill so revocation does not sit behind millions of history updates. When a recipient is unavailable, live purge has no finite completion guarantee; reads must fail closed according to the approved authority contract and the UI must show purge pending.

## Observed OPA microbenchmark

OPA 1.9.0 ran locally, warmed with 100 requests and then measured for 1,200 sequential HTTP calls per batch size, with built-in telemetry disabled. The shared environment has an 8-vCPU quota / 8 GiB RAM, not dedicated benchmark hosts. HTTP timing includes JSON encode/decode and loopback response reading. No bank data was used.

| Resource rows | HTTP p95 | HTTP p99 | Evaluation p99 |
|---|---:|---:|---:|
| 1 | 1.68 ms | 2.45 ms | 1.10 ms |
| 16 | 5.43 ms | 6.76 ms | 3.83 ms |
| 64 | 8.06 ms | 9.68 ms | 5.20 ms |
| 256 | 18.24 ms | 24.36 ms | 8.65 ms |

These are actual local component observations, unlike the simulated end-to-end numbers. They do not establish concurrent throughput, production tail latency or the p99 of a sum of stages. Batch and index OPA inputs; do not pass every policy or every relationship to every decision.

## Improvements, in priority order

1. **Bound the database work.** Remove load-all/snapshot-all from request paths. Index owner/root/resource bindings, use selective joins and capped keyset pages, pool connections and keep SQL plans stable. Replace the UI's raw global snapshot with regional materialized summaries and drill-down queries.
2. **Keep local ACID, remove process serialization.** Modular services share a local UoW; use per-resource versions, idempotency and bounded serialization retry. Every writer must call the sovereignty hook or be denied direct database access.
3. **Separate authority from materialization.** Use resource/scope/table epochs so one restriction becomes authoritative without rewriting hundreds of scope rows in the caller transaction. Dirty-scope work is asynchronous. For a table policy, advance the table epoch rather than rewriting 100M records.
4. **Replace full-graph delivery with versioned deltas.** Include parent requirements and content version, permit only legal recipient views, atomically apply changes and update inbox/manifest. Deduplicate party/contact payload physically only when all applicable recipient and purpose checks remain enforced; never share rights because two recipients share a store.
5. **Use regional queues and partitioned workers.** Retain the transactional outbox; move to local CDC/polling relay into regional Kafka or an equivalent durable bus. Partition by owner + resource/scope + recipient, quarantine bad events and implement jittered retry, backpressure, compaction/coalescing and priority revocation.
6. **Resolve remote-read semantics explicitly.** Local cached facts require bounded leases, epochs and freshness. A partition-level authority lease must be tied to a contiguous applied revocation watermark; a keepalive alone cannot certify no missing revocations. Batch lease refresh by authorized partition, not a 5-second refresh for every one of 100M scopes. Strict source reauthorisation remains available with a separate WAN latency target.
7. **Build real regional HA and operations.** Use 3 AZs per region, local RF=3, TLS, least-privilege credentials, regional keys and restore drills. Start the limited pilot with 3 nodes/region. A full-scale load-test candidate is SG 9 / UK 9 / US 6 nodes with 16 vCPU, 64 GiB RAM and 2 TB block storage each. This is a benchmark starting envelope, not a purchase recommendation or a mapping from the synthetic slots; measure and tune or scale it to satisfy capacity and failure headroom. Additional country-local stores may be required by actual entity policies.
8. **Make tails and custody visible.** OTel traces/metrics for queue wait, DB transaction, policy gate, retries and end-to-end projection freshness; govern audit separately. Avoid party IDs and payloads in general telemetry. Track oldest revocation and purge age alongside p95/p99; sample traces but keep required audit events complete.

## PoC to pilot

The backlog below is a gated plan, not work already implemented. An indicative 12–14 week path assumes an experienced team (backend/federation engineers, platform/DB, QA/performance, and dedicated business/security owners) plus timely infrastructure and data approvals. Legal review, procurement and unavailable environments can extend it. Start with approved 100k parties / 200k relationships in a limited pilot; run the 50M/100M scale rehearsal separately with synthetic data.

| ID | Priority / phase | Owner | Action | Exit evidence | Depends on |
|---|---|---|---|---|---|
| P01 | P0 / Decide | Business owner + data governance | Approve pilot scope, legal entities, data classes, allowed processing locations and global party minimum. | Signed field-by-field purpose/recipient/physical-store matrix; no implicit right from a global ID. | None |
| P02 | P0 / Decide | Product + SRE + security | Approve API boundaries, workload envelope and the remote revocation contract. | Choose strict source-authorised reads or a bounded maximum 5s stale-authorisation window; record outage behavior and clock budget. | P01 |
| P03 | P0 / Decide | Data architecture | Profile real row sizes, indexes, retention, sharing density, skew and party degree without exporting restricted records. | Replace every synthetic assumption with measured local aggregates; classify unknowns and agree forecast growth. | P01 |
| P04 | P0 / Foundation | Platform + database engineering | Create three isolated regional clusters with three AZs each, TLS, regional keys, backups and infrastructure as code. | At least 3 nodes per region on independent hosts; local AZ failure and permitted restore drills pass. Country-local cases remain blocked until proper stores exist. | P01 |
| P05 | P0 / Foundation | Security + API platform | Introduce regional gateway authentication, workload identity, entity/purpose authorisation and database service credentials. | Cross-entity reads and direct unauthorised writes denied; customer payloads never routed through excluded cells. | P01,P04 |
| P06 | P0 / Foundation | Backend + database engineering | Replace full-owner scans with bounded indexed repositories, connection pools and keyset pagination. | Read plans touch only requested keys; one scope cannot trigger a full party/history scan; max 50 rows / 32KiB page enforced. | P03 |
| P07 | P0 / Foundation | Backend | Create a shared local unit of work and sovereignty hook, removing the global process lock. | Business rows, controls, versions, outbox, audit and request receipt commit or roll back together; serialization retries and concurrent writers tested. | P06 |
| P08 | P0 / Foundation | Policy engineering | Version and sign generic Rego bundles; persist scoped facts separately; add decision cache keys and policy rollout fencing. | Missing/stale bundle or facts fail closed; bundle revision, entity placement and resource epochs covered by tests. | P05,P07 |
| P09 | P0 / Correctness | Federation engineering | Implement resource epochs, dependency indexes and bounded fanout work queues. | A 10,000-relationship party change has bounded owner commit; authorisation revocation does not wait for graph rewrites; no stale epoch read. | P07,P08 |
| P10 | P0 / Correctness | Federation + platform | Introduce regional outbox relay/CDC, partitioned workers and a regional durable message bus. | At-least-once delivery, per-key order, deduplication, bounded retries, quarantined errors and backpressure tested; raw excluded rows never enter a foreign bus. | P04,P07 |
| P11 | P0 / Correctness | Federation + database engineering | Build versioned delta import, graph closure and shared-resource deduplication under recipient controls. | No dangling parent, cross-scope overwrite or replay resurrection; change only affected rows; deduplicated storage does not broaden any entity's rights. | P08,P09,P10 |
| P12 | P0 / Correctness | Security + federation | Implement the selected remote-read and revocation design with priority control traffic. | Strict mode pays measured WAN latency; lease mode binds a contiguous applied revocation watermark, expires fail-closed and stays within approved skew-inclusive bound. | P02,P08,P09,P11 |
| P13 | P0 / Correctness | Security + audit | Separate append-only evidence from ordinary telemetry; mask sensitive attributes and archive regionally. | Denied routes leave source-only evidence; sampled traces contain no contact payloads; retention, holds and purge statuses are explicit. | P01,P04,P10 |
| P14 | P0 / Correctness | Data governance + platform | Implement live purge, tombstones, backup retention and restore-in-quarantine procedures. | Purge acknowledgement means live rows only; restored expired data cannot be served; audit/backup residuals documented per policy. | P11,P13 |
| P15 | P0 / Performance | Performance engineering | Build an open-arrival-rate test harness and deterministic full-scale synthetic data loader. | 1M, 10M, 50M and 100M relationships with corresponding parties, children, indexes and policy skew; no small-dataset cache illusion. | P03,P06,P07 |
| P16 | P0 / Performance | Performance + SRE | Measure workload-specific p95/p99, errors and saturation per operation, cell and entity. | Target peak 30k reads/s + 5k writes/s global for 60 minutes; 24h normal-load soak; dropped test iterations count as failure. | P10,P11,P12,P15 |
| P17 | P0 / Performance | Performance + database engineering | Run cold-cache, hot-key, compaction, backup and retry storms with controlled overload. | No OOM or unbounded queue; admission control and foreground priority operate; record actual capacity knee and scale-out trigger. | P16 |
| P18 | P0 / Performance | SRE + database engineering | Test node/AZ loss, WAN isolation, authority loss and a 30-minute recipient outage. | No foreign failover or unsafe read; at least 1.5× recovery service capacity drains a 30-minute peak backlog in 60 minutes while new traffic continues. | P04,P12,P16 |
| P19 | P0 / Rehearsal | Data migration | Promote the isolated India relocation slice into a normalized-table migration with distributed writer fencing, gateway route epochs and pending federation handoff. | Four-store CockroachDB test passes under controller/DB/OPA failures; source-writable copy, target-applied checkpoints, graph closure, idempotent handoff, no dual writer, deadline handling and separate live/backup disposal evidence. Measure cutover pause and foreground p99 under bulk load. | P11,P14,P15 |
| P20 | P0 / Rehearsal | SRE | Create alerts, capacity dashboards, runbooks, ownership and on-call training. | Lag age, oldest revocation, queue bytes, retry rate, lease expiry, DB resource use and error-budget burn alert correctly; operator drill passes. | P13,P16,P18 |
| P21 | P0 / Rehearsal | Security assurance + independent QA | Run adversarial entitlement, leakage and failure-injection tests before bank-data access. | Zero unauthorised payloads or metadata observed in forbidden stores/buses/logs; controls verified at infrastructure and API boundaries. | P05,P08,P12,P14,P19 |
| P22 | P0 / Pilot | Business sponsor + operations | Approve a limited pilot, starting with read-only shadow operation and explicit rollback authority. | Named acceptance sign-offs; approved initial cap 100k parties / 200k relationships across selected entities; synthetic full-scale test passed separately. | P16,P18,P19,P20,P21 |
| P23 | P0 / Pilot | Release manager + business service owner | Canary a single contact/consent workflow, then holdings, with a controlled traffic ramp. | 1% → 5% → 25% of pilot traffic with a 24h hold at each stage; rollback on leakage, epoch mismatch or sustained SLO breach. | P22 |
| P24 | P1 / Pilot | Product + finance + SRE | Review operating cost, user experience, performance and residency evidence before expanding entities. | Two-week stable pilot readout, measured capacity forecast and explicit go/no-go; approve new country cells before expanding their data footprint. | P23 |

## Reproduce and replace assumptions

```bash
python3 -m pip install -r scale/requirements.txt
python3 scale/simulate.py
# Optional actual local component benchmark, with telemetry disabled:
python3 scale/opa_microbench.py --opa /path/to/opa --samples 1200
python3 scale/render_results.py
python3 scale/validate.py
```

The local runtime remains the v3 PoC; this delivery adds modeling and a pilot plan, not the optimized production data path. Raw scenarios, per-seed summaries, latency CSV, assumptions, benchmark script and action CSV are packaged. No external load test or infrastructure deployment was performed. Full CockroachDB integration, 100M-row data loading, multi-AZ fault tests, OTLP end-to-end collection and browser visual QA remain unverified.

Primary references used for the engineering guidance (none supplies the modeled latency numbers):

- CockroachDB production checklist: https://docs.cockroachlabs.com/docs/stable/recommended-production-settings
- CockroachDB SQL performance: https://docs.cockroachlabs.com/docs/stable/performance-best-practices-overview
- Connection pooling: https://docs.cockroachlabs.com/docs/stable/connection-pooling
- Changefeed ordering and at-least-once delivery: https://docs.cockroachlabs.com/docs/stable/changefeed-messages
- OPA performance: https://www.openpolicyagent.org/docs/policy-performance
- k6 open workload model: https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/open-vs-closed/
- k6 dropped iterations: https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/dropped-iterations/

## Operational isolation amendment · edition 07

Policy changes now have three separate design lanes: bounded authority guard, reserved operational delivery and capped bulk reconciliation. A policy transaction creates one cursor rather than enumerating records; source effectiveness, remote enforcement and physical convergence are separate statuses. Old events must reauthorise against current facts; stale backfills and obsolete purges cannot overwrite newer state. See [the full ADR](/isolation/work-isolation.md) and [interactive model](/isolation.html). This is a proposed pilot design and executable scheduling specification; the v3 runtime retains its serial worker.

The live P01–P24 backlog supersedes the earlier table for P09, P10, P12, P16, P17 and P20 with explicit lane isolation, campaign-load comparison and cross-lane race gates. The original sixteen-scenario model and its numbers are unchanged. The isolation model uses a distinct deterministic service-budget illustration; it is not a new CockroachDB benchmark.
