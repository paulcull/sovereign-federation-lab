# Component design source

This directory contains the editable generators and shared assets for **28 component design pages**. The root lab build adds the portal, deployment guide, 16 ADR pages and ADR register.

Run `python3 scripts/build.py` from the repository root, or use `./lab build` with Docker. `design/src/build.py` builds the component pages; the root builder makes links portable, adds the implementation-status banner and assembles `dist/design/`.

The component pages contain production design proposals and static UX specifications. The actual CockroachDB/OPA API harness lives in `poc/`. Regional identity/gateways, HA, CDC/Kafka and distributed resource isolation remain pilot work. Every component page includes an engineering prompt. Do not interpret its skeleton as a deployed component.

Run root `scripts/verify.py` for the assembled lab, `design/tests/check_links.py` for component output, and `design/tests/check.js` for navigation, menu, print and prompt-copy handlers. Browser-rendered visual/accessibility QA remains outstanding. Historical design-site notes are retained under `docs/history/`.
