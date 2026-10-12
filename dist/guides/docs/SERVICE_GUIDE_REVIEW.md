# Existing-service guide review — 12 October 2026

Branch: `docs/existing-services-routing`, starting from main
`69cff2a` after PR #2 merged. This change explains an existing-service adoption
model; it does not implement independent regional peers or automatic routing.

## Changes reviewed

- Business services retain banking interactions, APIs, ownership and data models.
- Sovereignty peers govern approved placement, authority and policy-scoped movement.
- Integration depends on participation: guarded shared reads, atomic governed
  mutations, and coverage of bulk/direct writers. Raw CDC is insufficient by itself.
- Writes target the current authoritative owner. Reads require current permission
  and explicit freshness; owner reads require a lawful processing path.
- Cached routes cannot bypass migration fences. Copies do not become new masters.
- Nine reader steps introduce responsibilities before schema detail. Technical
  transaction/API examples remain available in an expandable reference.
- ADR-0005 clarifies the local transaction boundary without requiring consolidation;
  ADR-0017 records the proposed peer integration and routing contract.

## Executed checks

`python3 scripts/build.py`, `python3 scripts/verify.py`,
`python3 design/tests/check_links.py` and `node design/tests/check.js` passed:
52 generated HTML pages, 1,528 local links/assets/fragments, all 28 component
pages, 17 complete ADRs, navigation/menu/print/copy controls and the existing
CockroachDB-only, loopback deployment contracts.

The running real Docker gateway was rebuilt from the generated site.
`python3 design/tests/reader_browser.py` passed the nine-page previous/next
journey, glossary/evidence links, all 28 routes, mobile navigation and the service
explanation at 375/768/1440 pixels. The technical reference opens and remains
closed initially; there were no page errors or document-width overflow.
Screenshots are under ignored `artifacts/reader-guide/`, including
`services-375.png`, `services-768.png` and `services-1440.png`.

`./lab doctor` and the complete unmodified `./lab test` passed against the
existing `sfl-acceptance` Docker project: source exclusions, SQL placement,
minimal party versus relationship projections, guarded reads, migration
snapshot/catch-up/validation/fencing/cutover/stale writes/live cleanup,
API restart persistence, Collector span receipt, API-generated trace-correlated
logs through Collector to Loki, and the provisioned Grafana gateway.

These are real CockroachDB/OPA container checks. Historical SQLite unit tests
and hosted browser models are separate evidence. The acceptance run used only
synthetic data and did not run a new load or regional failover benchmark.

## Reproduce

```bash
./lab up
./lab test
# With Playwright and Chromium installed as documented in CONTAINER_ACCEPTANCE.md:
python3 design/tests/reader_browser.py
```

Open `http://localhost:8080/design/service-transactions.html` for the service
explanation and its read/write routing section. Start the full reader journey
at `http://localhost:8080/design/index.html`.

## Limits

Automated rendering and navigation do not certify first-reader comprehension.
Independent authenticated peers, integrations into an existing bank estate,
freshness negotiation, distributed authority and normalized-table migration
remain pilot work. The single-host lab does not prove HA, physical residency,
100M-record performance or erasure from retained history/backups.
