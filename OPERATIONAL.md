# Operational federation v3

For physical-home changes, see [Entity relocation](MIGRATION.md). The separate `mig_*` fixture demonstrates moving owner-qualified party, relationship, holding and servicing records under a temporary SG-to-IN transition policy. It preserves business IDs and includes versioned deletes, request-receipt handoff and a durable old-writer fence. It does not yet move these normalized `business.*` tables; the guide specifies parent ordering, complete-aggregate visibility and pending federation handoff extensions.

The business model and sovereignty model are parallel. The local operational service commits both through one transaction hook. Federation keys can be a **party**, a **relationship**, or a resource such as a **product holding**; the table registry supplies a default contract, not unconditional permission.

## Two distribution paths

1. **Party minimum:** `party.id`, `global_party_id`, `party_type`. Aster's explicit identity-resolution grants distribute this minimum to UK entities and the US entity; Singapore holds the authoritative row. Name, contact information and links to relationships are absent from this global scope.
2. **Relationship graph:** independent personal and business relationship scopes share the same party. Personal data is entitled to LE-GB-02 with contact fields; business data to LE-GB-03 with a minimal profile. Both exclude US storage. A party in New York therefore does not imply that any relationship or holding is in New York.

“Global” is a distribution intent, not a bypass. Each recipient needs an entity grant, valid purpose and physical placement. Example Trading has a party-key US exclusion, so even its party minimum stays out of the US. Excluding Aster's party later removes its US party copy and intersects every relationship scope containing that party.

The global minimum remains identifying metadata. Its legal basis, purpose and approved footprint require bank approval; this fixture is synthetic. The current three recipient grants illustrate all three physical stores, not automatic access for all 30 entities.

## Table mapping

Every business primary key is `(owner_entity_id, id)`. The owner column is business custody/tenant identity, not a residency rule. Each recipient key is `(owner_entity_id, scope_id, destination_entity_id, id)`, with foreign keys that include this full prefix. Stable `global_party_id` links identity; it is not the relationship key.

| Business table | Operational relation / major key | Sovereignty integration |
|---|---|---|
| party | Party UUID and global party UUID | Separate party scope for global minimum; resource rule intersects every use in relationship scopes |
| relationship | Relationship UUID | Root of its own scope; entity grants and purpose |
| party_relationship | Party + relationship + role | Many parties per relationship, many relationships per party; both parents required |
| product_holding | Holding UUID → relationship | Inherits relationship scope; holding classification may narrow sharing; balance withheld |
| contact_info | Contact UUID → party | May bind to multiple relationship scopes; contact profile + matching relationship/purpose/channel consent |
| consent | Party + relationship + purpose + channel | Business fact, exported status; changing it advances only affected decision revisions |
| preference | Party + relationship + channel | Contextual preference; shares only with matching contact consent |
| contact_history | Party + relationship | Owner-only narrative; write remains local |
| party_alternate_id | Alternate ID → party | Owner-only sensitive identifier |
| relationship_alternate_id | Alternate ID → relationship | Scoped CRM reference, requires its relationship parent |
| holding_alternate_id | Alternate ID → holding | Owner-only account identifier |
| classification | Exactly one typed party/relationship/holding FK | Assignment with code and sensitivity; restricts target and dependent graph; taxonomy service is an extension |

No business row stores allowed countries, excluded countries, entitlement lists or policy generations. Those live in `sovereignty.table_rule`, `scope`, `resource_rule` and `binding`. The rule bundle owns table names and field allowlists in `poc/policies/operational_catalog.json`. The editable table rules can narrow this contract; a table policy cannot make an owner-only dataset exportable.

## Policy resolution

`ALLOW = entity entitlement ∩ physical placement ∩ scope geography ∩ table restrictions ∩ resource restrictions ∩ classification ∩ consent/context ∩ approved fields`.

There is no last-writer-wins override. A party-key restriction can narrow a global table default, a relationship cannot relax a shared party restriction, and a holding restriction narrows just that holding and its dependants. Consent alone never authorises residency. The servicing consent rule is an illustrative contact-sharing business rule, not a universal lawful basis for bank processing.

The source resolves bindings to authoritative business rows and control facts, sends a batch to local OPA, projects approved columns, and repeatedly removes children without their required parents. If the scope root is withheld, the entire graph is withheld. Global party scopes contain just one party row, so no relationship can leak through an identity link. An unknown dataset or missing binding fails closed.

## Transactions and regional services

The PoC runs a single FastAPI process with a single worker and a process-wide lock. It acts as a modular business service and federation adapter for the three stores. It is not three production service deployments and has no authentication.

Production deployment: regional gateway/BFF → authenticated regional business service modules → local CockroachDB. Resolve owner entity and physical home from trusted context; authorise entity, service action and purpose before routing. A request sent to the wrong home is rejected or forwarded only along an explicitly permitted path. No global gateway should terminate sensitive bodies outside an approved location. Regional service modules include Party, Contact/Consent, Relationship, Holdings and Interaction History. They may share a deployment and local unit of work when business invariants require it. Independently deployed services require an explicit saga or new transaction boundary, not a pretend cross-service ACID transaction.

For `update_contact`, one local transaction writes contact information, the selected relationship preference, owner-only contact history, affected binding/control updates, both relationship data versions, outbox entries, source audit and the request receipt. Global party versions do not change. `open_holding` writes holding, alternate ID, classification and bindings in the same transaction. No WAN request or OPA network evaluation is made inside this business transaction.

After commit, the worker reads current state, evaluates OPA locally and emits only an approved graph. The recipient rechecks the allowed fields with its own OPA instance. One destination transaction deletes the old scoped graph child-first, inserts the new graph parent-first, and writes manifest, inbox and audit. The source acknowledges separately. A crash between recipient commit and source acknowledgement is retried using the inbox event ID. Older data/policy/decision versions are fenced. Never-authorised denied destinations receive neither payload nor customer-linked tombstone; denials remain at source. Previous recipients retain a compact receipt after purge for fencing; this is governed metadata, not a claim of total erasure.

`data_version` tracks business freshness. `decision_revision` advances for consent and classification changes. `policy_generation` advances for table/key rule changes. `placement_version` fixes the physical target. Remote reads require the current decision/policy/placement version, but can serve an older ordinary data version. A paused store may still contain an old copy while reads fail closed. Reads consult the authoritative policy in this harness; no offline read lease is implemented. Production network importer credentials, signed permits and distributed fencing are extension points.

## APIs implemented

| Method / path | Behaviour |
|---|---|
| GET `/api/operational` | Synthetic owner graph, separate control facts, recipient manifests and command receipts |
| POST `/api/operational/scopes/{scope}/commands` | `request_id` UUID + `expected_version` + command; local transaction, 409 stale/conflicting replay |
| GET `/api/operational/scopes/{scope}/preview/{entity}` | Evaluate actual local OPA and dependency closure; does not write |
| GET `/api/operational/scopes/{scope}/read/{entity}` | Current policy and authorisation revision check, then scoped read |
| POST `/api/stores/{store}/pause` | Pause simulated importer ingress, useful for stale-copy tests |

Commands: `update_contact`, `withdraw_consent`, `restore_consent`, `open_holding`, `classify_restricted`, `classify_internal`, `log_contact`, `exclude_party_us`, `restore_party_us`, `table_contact_local`, `table_contact_restore`. Control commands share a harness endpoint for brevity; production must separate business and policy authorisation, approvals and audit roles.

```json
{
  "request_id": "3b82d3ba-072b-431a-b395-89976198f35f",
  "expected_version": 1,
  "command": "update_contact",
  "value": "updated.aster@example.invalid"
}
```

The browser simulation mirrors the same commands, versions, source graph and scoped projections. Its policy evaluator is JavaScript, not an embedded OPA engine. The local runtime calls actual OPA.

## Try it

Open **Business services** and keep Aster's personal relationship selected. Wait for initial receipts.

1. Select LE-US-01: its global party card is present while the selected relationship has zero approved rows. Select the Aster global party scope: the US source/projection comparison shows only the three identity fields.
2. Select Example Trading's party scope and LE-US-01: its resource exclusion blocks even the global minimum.
3. Return to Aster personal / LE-GB-02; update contact. The receipt reports two affected relationship scopes. The business relationship minimal projection still has no contact.
4. Pause London, withdraw consent and test the business read. The old contact is visibly stored, but the read is blocked. Resume London: contact and preference rows disappear; the owner's data remains.
5. Restore consent. Open a holding and restrict one holding. Inspect product holdings and classification; no child refers to a withheld parent. The balance and core account alternate ID never appear remotely.
6. Expand **Test table defaults and major-key overrides**. Keep the contact table at owner, then restore table federation. Exclude this party from US, then restore eligibility. The explicit relationship US exclusion remains intact.
7. Replay the last request ID: the same receipt returns, with no duplicate write. Click **Watch global monitor** immediately after a command to see source commits, blocked decisions and acknowledged movement.

Generate operational records through the service hook:

```bash
python3 poc/scripts/business_commands.py --command open_holding --count 5 --interval 2
python3 poc/scripts/business_commands.py --command update_contact --count 5 --interval 2
python3 poc/tests/operational_integration.py
```

The generator adds holdings/alternate IDs/classifications or changes contacts; it does not yet create arbitrary new parties and relationships. The original record generator remains in the record sandbox.

## Performance and extension points

- Prototype: small full-scope graph replacement, polling every 800 ms, at most 15 operational deliveries per pass, indexed typed primary/foreign keys. This favours understandable consistency over throughput. No performance benchmark is claimed.
- Keep the owner transaction bounded. A shared-party update can fan out to many scopes; production should version the party resource and durably mark dependent scopes dirty, then batch/coalesce materialisation. Require a current resource authorisation epoch on reads so asynchronous dependency discovery cannot extend revoked access.
- Replace full model scans with indexed binding queries and selective `AS OF`/snapshot reads after pinned-version validation. Bound rows/bytes per manifest. Partition workers and bus topics by `(owner, scope, destination)`. Avoid putting global locks or unbounded party fanout on the latency path.
- Retain the transactional outbox. Later use CockroachDB CDC on **outbox intents** to regional Kafka, not raw multi-table CDC directly into another geography. Changefeeds provide at-least-once delivery and do not preserve transaction-wide ordering; manifests and inbox deduplication remain necessary. A local polling adapter keeps the PoC small.
- `operational_core.py`: command planning and dependency closure. `operational.py`: storage/UoW, OPA transport, relay, importer, receipt and read adapter. `operational_schema.sql`: typed tables. `operational.rego`: dataset decisions. `operational_catalog.json`: verified field contract. `operational-engine.js`: hosted simulator. Replace adapters rather than duplicating sovereignty logic in every business handler.
- Every writer must invoke the hook or be blocked by credentials. The polymorphic resource binding is application-validated; SQL alone does not ensure its UUID exists in the named table. Production needs writer restrictions, registry integrity checks and fail-closed handling of unregistered changes. Bulk loads, deletes, migrations and legacy direct SQL are not solved by a sidecar alone.
- Real transaction retry/backoff for CockroachDB serialization failures, tombstone lifecycles, identity merging, taxonomy service, large-party fanout and legal-entity rehoming need dedicated implementation. Do not run multiple harness workers.

## Observability and audit

Actual runtime spans include `operational.command`, `operational.dataset_gate`, `operational.import`; the existing OTel setup exports locally and optionally via the Collector. Use command kind, source/destination store and row counts as attributes. Keep party IDs, contact values, business payloads and auth headers out of general telemetry/baggage. Regional audit receipts may be customer-linked and must stay within their approved footprint. Source receipts distinguish business commit, denial and destination acknowledgement; no completed deletion is inferred from a denied read. Durable WORM evidence export, retention policy and regional metric dashboards are production extensions.

## Acceptance and limits

Executed: actual OPA v1.9.0, 840 browser/OPA cases (7,290 row decisions), Python business commands/graph closure, Node workflow tests, original 12 Rego tests and 990 entity parity cases. The subsequent [container acceptance](docs/CONTAINER_ACCEPTANCE.md) passed actual CockroachDB business commands, typed SQL projection checks, API restart persistence, OTLP log delivery and the live Chromium walkthrough. Database crash/partition/serialization-retry tests and a full accessibility review remain pilot gates.

```bash
docker compose exec db-us ./cockroach sql --insecure --execute 'SELECT owner_entity_id, scope_id, destination_entity_id, global_party_id, party_type, display_name FROM projection.party'
docker compose exec db-us ./cockroach sql --insecure --execute 'SELECT count(*) FROM projection.relationship'
docker compose exec db-sg ./cockroach sql --insecure --execute 'SELECT root_type, root_id, data_version, decision_revision FROM sovereignty.scope'
```

Use a fresh v3 fixture; existing v2 `fe_*` tables are retained as a separate record sandbox. The new `business.*`, `sovereignty.*` and `projection.*` schemas are additive. The single-node topology has no local HA, and a laptop does not establish physical residency.

Primary references: [OPA/Rego](https://www.openpolicyagent.org/docs/policy-language), [CockroachDB changefeed guarantees](https://docs.cockroachlabs.com/docs/stable/changefeed-messages), [OpenTelemetry sensitive data](https://opentelemetry.io/docs/security/handling-sensitive-data/).
