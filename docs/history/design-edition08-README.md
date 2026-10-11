> Historical design-site source. Current deployment: ../DEVELOPMENT.md

# Customer Data Federation — design site

Static, private design deliverable with 19 real HTML pages. No bank backend or production code is implemented. Customer, policy, approval, revocation and telemetry displays are synthetic browser-local simulations.

## Build

`python3 src/build.py` generates HTML from the content definitions. Shared CSS and JavaScript live in `dist/style.css` and `dist/app.js` and are source-controlled directly. No package install or build framework is required.

## Main pages

- `index.html`: architecture decisions and navigation
- `control-plane.html`, `policy-lab.html`, `operations.html`: interactive UX wireframes
- `architecture.html`, `gateways.html`, `opa.html`, `transactions.html`, `federation.html`, `lifecycle.html`, `observability.html`, `audit.html`, `apis.html`: component specifications
- `engineering.html`, `references.html`: implementation plan and source trail

Each page includes a focused copyable engineering prompt. Real OPA evaluation, APIs, databases, identity and audit persistence are extension points, not active functionality.

## Verification performed

- Python generator executed successfully for all 19 pages.
- HTML internal links, local asset references, unique element IDs and engineering prompt presence checked.
- JavaScript syntax checked with Node.
- Policy simulator boundary checks: explicit US deny, missing storage/processing/entitlement, expired facts, denied fields.
- Revocation simulation checks: unreachable destination cannot advance to receiver acknowledgement, completion is bounded.

Browser-based visual QA was unavailable in the authoring environment. No preview server or alternate browser tool was used. Responsive layout rules are included, but rendering across real browsers remains to be verified. Technical configuration samples and Rego are explicitly labelled skeletons and have not been executed against the real platforms.

## Edition 03 — original discussion incorporated

Read both user-supplied transcript parts in full. Added origin/requirements, on-premises platform control, three-way replication comparison (including LDR), and consistency/outage decision pages. Singapore is the authoritative example home and UK the projection throughout diagrams, policy input, wireframes and prompts. Five-second replication lag and 30-second leases are explicitly provisional. Added a separate 120-second pre-authorised offline-read simulation; it never permits authoritative UK writes or exports with expired facts. Product claims used for Operator, RoachMgr and LDR were checked against the linked primary sources.

Run `python3 src/build.py`, `node --check dist/app.js`, `node tests/check.js`, and `python3 tests/check_links.py`. These checks passed for edition 03. Browser visual QA remains unavailable and has not been claimed. No actual OPA, CockroachDB or Kafka integration was executed.

Edition 07 adds work-isolation.html: separate authority guard, operational placement and bulk reconciliation; explicit activation/visibility/physical-convergence milestones, race rules and engineering gates. The linked monitor includes a deterministic equal-capacity comparison.
