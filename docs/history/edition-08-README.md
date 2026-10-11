> Historical edition-08 source, retained for provenance. Commands and deployment claims here are superseded by [the current lab guide](../DEVELOPMENT.md).

# Sovereign — legal entity federation PoC v3

## New: add a store and relocate an entity

Open the [Entity relocation workspace](https://sovereign-data-monitor.paulcull.chatgpt.site/migration.html). Add Mumbai, generate source updates during copy, catch up, validate, fence Singapore, activate India and remove old live copies. The original three-store catalog remains available alongside this isolated scenario.

The [migration guide](../../MIGRATION.md) covers the synthetic transition policy, failure controls, OPA, gateway/service routing, transaction boundaries, API/generator commands and pilot extension points. SQLite persistence and real OPA are tested; the optional fourth CockroachDB-node profile still needs execution on a capable host.

```bash
docker compose -f compose.yaml -f compose.migration.yaml up --build
# Open http://localhost:8000/migration.html
```

Without Docker, use the four-file SQLite instructions in MIGRATION.md. The hosted page is an explicitly labelled browser simulation.

**30 synthetic legal entities. Three independent CockroachDB single-node stores. OPA/Rego policy, an entity-aware generator and an animated global monitor.**

- Interactive hosted simulation: https://sovereign-data-monitor.paulcull.chatgpt.site
- Updated component design pages: https://customer-federation-design.paulcull.chatgpt.site

The hosted monitor is an in-memory simulation, explicitly labelled; reload resets it. The downloadable runtime runs real CockroachDB and OPA locally. It has not completed database integration testing here: the execution environment could not start CockroachDB because its process CPU probe failed. See TESTING.md.

## Scale assessment and pilot plan

The current runtime remains v3. The new [scale assessment](../../scale/SCALE_AND_PILOT.md) models 50M parties / 100M relationships, p95/p99 goals, storage, skew, recovery and a 24-action pilot backlog. It simulates sampled workloads; no 100M-row database is loaded or benchmarked. An actual local OPA component benchmark is reported separately.

- Capacity lab: https://sovereign-data-monitor.paulcull.chatgpt.site/scale.html
- Reproduce: `python3 -m pip install -r scale/requirements.txt`, then `python3 scale/simulate.py`.
- Validate: `python3 scale/validate.py`.
- Inputs: `scale/assumptions.json`; outputs: `scale/results/`; pilot actions: `scale/pilot_actions.json`.
- The proposed indexed repositories, epochs, delta import and regional service deployment are pilot work, not completed features of this PoC.

## New: the operational business model

Open **Business data model** or **Business services**. Twelve normalized business tables sit beside a sovereignty control schema. Party identity has a separate global-minimum scope; relationship graphs follow independent policies. Table defaults and party/relationship/holding restrictions intersect with explicit denials.

See [OPERATIONAL.md](../../OPERATIONAL.md) for the table mapping, service transactions, API outlines, generator and acceptance walkthrough. The source now includes typed SQL, actual OPA dataset rules and a browser service lab. Existing record sandbox features below remain available.

- Model: https://sovereign-data-monitor.paulcull.chatgpt.site/#business
- Service lab: https://sovereign-data-monitor.paulcull.chatgpt.site/#services
- Run `python3 poc/scripts/business_commands.py --command open_holding --count 5` against the local runtime.
- Run `node poc/tests/operational_engine.mjs` and `python3 poc/tests/operational_integration.py` for the new workflows.

## Run locally

Prerequisites: Docker with Compose v2, internet access to pull images, about 4 GB available memory and port 8000 free. Python 3.10+ runs the dependency-free CLI and integration tests.

```bash
unzip sovereign-data-poc.zip
cd sovereign-data-poc
docker compose up --build
```

Open http://localhost:8000 after startup; OpenAPI at http://localhost:8000/docs. Only port 8000 is published, bound to loopback. SQL, OPA and Collector ports remain internal. This is a synthetic PoC with no authentication or TLS. One API worker only.

```bash
python3 poc/scripts/generate.py --count 10 --scenario world-tour
python3 poc/scripts/generate.py --count 3 --batches 10 --interval 2 --scenario mixed
python3 poc/tests/integration.py
node poc/tests/engine.mjs
docker compose run --rm opa-sg test /policies -v
```

Stop with `docker compose down`; named volumes preserve data. The v2 schema uses `fe_*` tables and leaves any v1 tables untouched. Upgrade by rebuilding the image; do not run old and new harness workers together. A catalog fingerprint prevents restarting existing data against a silently changed entity/store mapping. A controlled migration or a separate empty demo environment is required to change those mappings.

## See the movement

1. Click **Run showcase**. This starts a synthetic record stream; stop it with the same button.
2. Large map hubs are physical store models. Small dots are legal-entity locations, not data-storage claims. Green trails illustrate recent acknowledged projection events, not packet capture.
3. Select a customer and focus its routes. Dashed red candidate paths never animate as successful transfers.
4. Inspect **Legal entities**: 25 valid assignments and five deliberately blocked placements.
5. Generate **Shared store, separate rights**: UK Markets receives a copy; UK Private Bank is denied despite sharing the London node.
6. Generate **Entity allowed, geography denied**: the Canadian entity is permitted but its US-hosted copy is blocked by a US exclusion.
7. Pause London ingress, revoke an existing recipient in **Policy studio**, and observe pending purge. The business read test denies access while the live copy still exists. Resume to reconcile.
8. In **Record sandbox**, inspect two records sharing a global customer ID. Owner versions and grants remain independent.
9. In the placement inspector, propose New York for a UK entity. The planner returns conflicts without changing the binding.

## Entity and store model

| Group | Count | Illustrative countries |
|---|---:|---|
| UK | 3 | GB: Retail, Markets, Private Bank |
| Asia | 8 | SG, IN, JP, ID, MY, TH, VN, PH |
| Americas | 3 | US, CA, MX |
| MENAT | 5 | AE, SA, EG, TR, QA |
| Rest of Europe | 11 | DE, FR, IE, ES, IT, NL, CH, BE, SE, PL, LU |

Asia assumes one entity per country. Names, locations and policies are synthetic—not claims about banking law or the bank’s actual legal entities. `shared/catalog.json` is the source directory; its frontend copy is `dist/catalog.json`.

The physical store models are `STORE-SG-01` (Singapore), `STORE-GB-01` (London) and `STORE-US-01` (New York). All run on one Docker host: no real geographic separation or HA. India, Indonesia, Saudi Arabia, Germany and Switzerland have deliberately country-local rules in the fixtures, so their candidate SG/GB placements are blocked. Their entity dots do not imply data exists there.

```text
global_customer_id                          identity
(owner_entity_id, global_customer_id)       authoritative relationship key
(owner_entity_id, global_customer_id,
 destination_entity_id)                     projection / fence key
entity_id → store_id + placement_version     physical binding
```

Sharing a store does not grant access. Sharing a global ID does not merge ownership or rights. The API can create a fresh synthetic owner relationship with the same ID only when the existing relationship permits disclosure to that entity. It preserves geographic restrictions for the shared ID, generates fresh synthetic business fields and does not inherit source grants or notes. A production identity-resolution service and provenance model are still required.

## OPA decision

All must hold:

1. Recipient is allowed and not explicitly excluded.
2. Entitlement is active, unexpired, purpose-matched and has an approved profile.
3. Resolved physical store matches the recipient entity binding.
4. Actual store country satisfies the entity’s approved countries.
5. Actual store country satisfies customer allowlist and exclusions.
6. Recipient accepts inbound sharing and is not the authoritative owner itself.

`minimal`: name + tier. `contact`: also email. Notes always stay with the owner. Negative decisions do not contact never-authorised recipients. Existing contacted copies can receive purge commands. The global synthetic admin snapshot is intentionally not a production authorization model.

## Transaction and performance choices

- Owner transaction: relationship mutation, outbox and audit commit together.
- Outbox resolves **recipient entity**, not only geography. It reads latest state and coalesces intermediate versions; it is not a lossless history stream.
- Source OPA evaluates before any recipient contact. Destination OPA rechecks before its transaction.
- Recipient transaction: inbox idempotency, generation fence, recipient-keyed projection replacement/delete and audit. Source acknowledgement follows commit.
- Same-store transfers still enforce recipient identity and use scoped rows. Physical co-location confers no rights.
- One process-wide lock serializes modifications and delivery. This substitutes for distributed fencing only in the single-process PoC. Do not run multiple workers.
- Polling every 800 ms with up to 30 tasks per source per pass. No SLA or throughput claim; no exponential backoff/DLQ yet.
- Remote business reads consult current owner policy, generation and placement version. No offline-read lease or automatic promotion.
- Grant expiry triggers reconciliation without another business mutation. Live purge does not erase MVCC, backups, inbox, fences or audit history.
- Placements are immutable during runtime. The planner is read-only; changing catalog mappings against existing data causes startup refusal. Migration execution is not implemented.

## API outline

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/state` | Synthetic global snapshot |
| GET | `/api/catalog` | Entity/store registry |
| POST | `/api/records` | Create entity-owned relationship |
| PATCH | `/api/records/{id}/policy` | Expected generation plus entity/country rules and grants |
| POST | `/api/records/{id}/touch` | Change synthetic tier and increment owner version |
| POST | `/api/records/{id}/relationship` | New synthetic owner relationship; authorised shared global ID |
| GET | `/api/records/{id}/read/{entity}` | Reauthorized entity business read |
| POST | `/api/entities/{entity}/placement-plan` | Proposed `store_id`; read-only impact plan |
| POST | `/api/stores/{store}/pause` | `{paused: true}` ingress simulation |
| POST | `/api/generate` | `{count: 1..100, scenario: "mixed"}` |

Policies use `allowed_entities`, `denied_entities`, `allowed_countries`, `denied_countries`, and `grants[entity] = {active, expires_at, purpose, profile}`. The backend, not the client, resolves physical placement. Source ownership is immutable in this PoC.

## Generator and fixtures

35 initial owner records, including two independent owners sharing a global ID. Eleven scenarios: `sg-uk-no-us`, `shared-store-isolation`, `multi-entity`, `geo-deny`, `placement-blocked`, `no-entitlement`, `expired`, `contact`, `short-lived`, `home-only`, `world-tour`.

Extend `poc/seed.py::make_record` and update the matched browser factory in `dist/engine.js`. The generator only creates owners with valid placement. Placement-blocked entities remain visible as potential recipients and directory conflicts, not illegal home records.

## Observability and audit

OpenTelemetry SDK emits policy/transfer spans with bounded entity/store attributes, not customer IDs or payload. JSONL exporter writes locally; optional OTLP HTTP export sends to the Compose Collector. View `docker compose logs otel-collector`. End-to-end export is unverified here.

Each store has `fe_audit`, separate from telemetry. Source denials stay source-side. Recipient audit records no owner payload. SQL audit is not tamper-evident or retention-complete. Production requires regional collectors, redaction, immutable audit export and governed retention.

## Production extension points

Split physical store adapters into authenticated regional business services. Gateways must validate entity identity and permitted processing geography before forwarding payload. Add mTLS, signed permits bound to recipient and placement generation, serializable transaction retries, bounded pools, per-owner ordering, regional transport, immutable audit and controlled migration barriers. A composite key prevents collisions; it does not replace authorization.

Component prompts, sequence diagrams and decisions: see DESIGN.md and the updated design companion. Verification limitations and required local gates: TESTING.md.

Map data: Natural Earth 1:110m land, public domain. Bundled vector geometry; no runtime map service or location tracking. https://www.naturalearthdata.com/about/terms-of-use/

## Work isolation design (edition 07)

[Interactive model](https://sovereign-data-monitor.paulcull.chatgpt.site/isolation.html) and [design decision](../../WORK_ISOLATION.md) separate authority guard, operational placement and bulk reconciliation. Run `node scale/isolation_test.mjs` for deterministic scheduling and admission invariants. The model does not change the v3 runtime worker or establish measured resource isolation.
