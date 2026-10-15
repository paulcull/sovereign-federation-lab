# Production foundation acceptance

This change addresses the challenger review with bounded implementation work in
the synthetic single-host lab. It does not approve bank data, independent regional
availability, production identity, distributed writer election or backup erasure.

## Reproduce

```bash
./lab doctor
./lab pilot-up
./lab pilot-test
./lab pilot-faults
LAB_PILOT=1 ./lab test
LAB_PILOT=1 ./lab faults
python3 poc/tests/pilot_browser.py
python3 poc/tests/browser_acceptance.py
python3 design/tests/reader_browser.py
```

Run mutable and fault suites sequentially. `pilot-faults` includes the new
`pilot-isolation` gate, which pauses actual UK peer and SG OPA processes and
restores them with shell traps. The new source service uses its own CockroachDB
schema and SQL role; the original insecure SQL transport remains a development
limitation, not effective authentication against a hostile internal client.

On an HTTPS-intercepting build host, use the existing trusted-CA build secret:
`LAB_BUILD_CA=/etc/ssl/certs/ca-certificates.crt ./lab pilot-up`.

## Execution status

The full local suite below passed for foundation revision `8cd6c5c` on
14–15 October 2026 (UTC), using the existing synthetic volumes from the wired
pilot. Subsequent clean-CI and review findings are recorded below; the earlier
run is not evidence for an untested follow-up. Host limits: 4 CPU, 16 GiB RAM and a
31.5 GiB filesystem. Docker 28.4.0 / Compose 2.40.3 were available. Repeated image
builds required reclaiming unused build cache and dangling project images;
no database or telemetry volume was removed. The documented 15 GiB disk budget
is initial free space, not a promise that repeated builds consume no extra disk.

| Gate | Result |
|---|---|
| `./lab doctor`; `./lab pilot-up` | Passed after the startup fixes below; all 20 containers running, upgrade retains existing data |
| `./lab pilot-test` | Passed: original pilot/review checks, 8 credential unit checks, 16 scoped/full OPA plan comparisons, actual indexed query plans, protocol races, live credential lifecycle and independent servicing SQL/OPA integration |
| `./lab pilot-faults` | Passed: actual peer/source OPA/recipient OPA/Collector outages, retry fairness, restart persistence, trace/log correlation, paused-dependency isolation and recovery |
| `LAB_PILOT=1 ./lab test` | Passed: source-side exclusions, minimal party and relationship policies, generator/monitor, complete India migration, SQL authority after restart, Collector span receipt and Loki/Grafana |
| `LAB_PILOT=1 ./lab faults` | Passed: real source OPA and Collector failures, mandatory business audit/receipt durability, fail-closed reads/exports and recovery |
| Three Chromium walkthroughs | Passed: MDM create/read/update/exclusion; generator and acknowledged movement; full India migration; reader navigation and 375/768/1440 px layouts, with no page errors |
| Offline build/navigation/ADRs | Passed: 55 HTML pages, 1,608 local links/assets/fragments and 19 ADRs; 26 external references inventoried, not uptime-verified |
| Loopback gateway UI/API documentation | HTTP 200: portal, monitor, Grafana dashboard, pilot console and servicing OpenAPI/Swagger |

The common API/peer/servicing image for that initial full local run was
`sha256:145f96facbce9061fc99abf390bf99b09a389e18c40dc30f4dbf5dbde6b8729d`.
Stores use CockroachDB v25.4.0, policy processes OPA 1.9.0. CI must execute the
same gates from a clean checkout; consult the PR's exact-commit workflow and
`lab-evidence` artifact rather than assuming a prior commit's result applies.

### Observed failures and corrections

- A populated-volume index upgrade stalled even with only 71 party rows. The
  CockroachDB BulkAdder requested another 32 MiB while roughly 32 MiB was
  allocated under `--max-sql-memory=64MiB`. Raising each store to 256 MiB allowed
  the durable backfill to complete. Required indexes and data were preserved.
- A newly added SQL comment contained a semicolon, which the existing schema
  loader split as a statement boundary. Corrected the comment and rebuilt;
  startup now completes with the complete additive schema.
- The new multi-subject query-plan assertion initially expected textual UUIDs.
  CockroachDB renders typed UUID-array spans as quoted bytes. The regression now
  decodes complete UUID spans, requires both subject keys and the intended
  subject index, and still rejects a full scan. Production query inputs and
  resource limits were unchanged.

- The first clean [CI run](https://github.com/paulcull/sovereign-federation-lab/actions/runs/38688642015)
  failed the query-plan gate on a fresh three-row classification table. The
  optimiser selected an owner-wide primary-key scan; populated-volume acceptance
  had selected the subject index. A forced index alone also allowed a full scan
  of an empty subject index. Runtime policy-fact queries now use whitelisted
  `FORCE_INDEX` plus `NO_FULL_SCAN`, with the exact same SQL builder exercised by
  the regression. Seven actual query shapes must execute with constrained subject
  spans on populated SG and sparse UK/US. India uses the separate migration
  fixture and has no operational classification schema; this check makes no
  claim about that schema in India.
- Copilot identified a case-content fence bypass when a policy revision increased
  without increasing the business data version. The recipient now rejects a
  changed payload hash whenever the business version matches, independently of
  policy revision. The regression advances both real source and recipient OPA
  policy revisions, requires the specific conflict response, and checks complete
  projection, inbox and import-audit rows remain unchanged. Policies and the
  deliberately altered synthetic source row restore afterward.

The first CI run stopped at its failing gate; later pilot fault/browser stages
were skipped by the workflow and are not passes for that run. No assertion was
weakened, no failing gate disabled, and no business store replaced with a mock.

### First review follow-up execution

After both corrections, the shared application image was rebuilt as
`sha256:2252114e3b1c83ae6326d0ea32e6f3609009387e1d1876e04ec1b31629d6891b`.
The complete `./lab pilot-test` and `./lab pilot-isolation` passed again on that
image. This includes actual execution and plans for seven query shapes on each
of SG/UK/US and the cross-policy-revision content-conflict regression. The final
isolation rerun measured approximately 0.05/0.06-second owner reads against
5.06/2.04-second stalled peer/OPA requests. The PR workflow reruns the entire
original and expanded acceptance sequence from a fresh checkout after this
follow-up; its exact-commit result is the final CI evidence.

### Reconciliation review follow-up

The complete clean [CI run at `e0131f1`](https://github.com/paulcull/sovereign-federation-lab/actions/runs/38689983709)
passed every gate and uploaded `lab-evidence`. Copilot confirmed the case-content
finding resolved, then identified a separate performance warning: each
reconciliation pending-intent lookup could scan retained outbox history.

The follow-up adds the partial `outbox_pending_scope_destination` index for
`queued`/`retry` intents. Runtime and regression share the exact pending SELECT
and enclosing INSERT, using `FORCE_INDEX`, `NO_FULL_SCAN` and `LIMIT 1`. Real
CockroachDB plans must constrain both scope and destination. A single synthetic
row tests queued/retry/completed states and an absent destination; it is rolled
back and verified absent afterward, without changing statistics or inflating
fixtures.

Normal `./lab pilot-up` applied the index to the existing volumes, started all
20 containers and reconciled 144 scopes (338 fresh intents queued). The complete
`./lab pilot-test` passed on the rebuilt image
`sha256:c4ee60df347ce7910830b8ddbefb46d7f66433cc93d1137436ad8f212f42f6ac`,
including the exact lookup/insert plans and rollback check. The final PR commit
must also pass the complete clean CI sequence; use its run and artifact rather
than transferring the earlier green result to this change.

### Read isolation measurements

One sequential fault run measured a healthy owner baseline of 0.077 seconds.
With the actual UK peer paused, its read failed closed after 5.067 seconds while
an unrelated owner read completed in 0.049 seconds (gate: below 2 seconds and
before the dependency timeout). With SG OPA paused, the affected command failed
closed after 2.039 seconds, created no command receipt, and the owner read
completed in 0.048 seconds (gate: below 1.5 seconds). Both dependencies recovered.
These are regression samples, not p99, throughput or regional availability
claims.

## Scope and remaining gates

- [Foundation requirements and production release gates](PRODUCTION_READINESS.md)
- [Independent business service integration](SERVICE_INTEGRATION.md)
- [Authority, partition and recovery contract](AUTHORITY_RECOVERY.md)
- [Startup, identities and API contracts](PILOT.md)

The earlier challenger probe showed a stalled UK read delaying an owner read to
5.10 seconds, versus a 0.53-second baseline. Both UK and US projections failed
closed after approximately 15 seconds when the owner was paused. Those were
single diagnostic samples, not a load benchmark. The new isolation gate requires
a concurrent owner read to complete before the real stalled dependency returns.
