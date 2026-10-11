# Documentation accuracy and navigation review

Edition 09, 11 October 2026. Scope: the consolidated lab repository and generated portal; previous standalone Sites remain historical publications.

## Corrections made

| Finding | Resolution |
|---|---|
| Separate monitor and design projects with absolute links | Both sources are included; the lab build converts internal project links to portable same-origin paths |
| Three-store base examples confused with four-store migration | Registry/data scope stays three-store; unified deployment provisions India as the fourth store |
| Hostname determines simulation vs live API | Gateway supplies explicit live configuration; live errors do not enable simulation |
| SQLite launch instructions alongside CockroachDB deployment | Current service entry points reject SQLite; instructions use only the unified CockroachDB Compose lab |
| Optional overlay and multiple port conventions | One compose.yaml and ./lab entry point; published gateway port 8080; internal API 8000 |
| Migration planner-only text mixed with executable migration | Read-only original directory planner and isolated executable migration are distinguished |
| Full-copy write freeze in an older sequence | Source-writable copy/catch-up; brief entity fence before authority activation |
| Pilot design could be mistaken for implemented infrastructure | Implementation-status banner and matrix on supporting design pages |
| Design rationale spread through conversation | Sixteen ADRs with status, context, decision, alternatives, consequences, evidence and acceptance gate |
| Previous test results implied database execution | TESTING.md separates historical unit/model evidence from unexecuted CockroachDB container gates |
| Obsolete design-site test called removed wireframe exports | Replaced with tests of the current navigation, menu, print and copy-prompt handlers; historical test retained as source |
| Unclear Git hosting | Private Sites Git source plus portable Git bundle; optional GitHub creation helper and explicit connector limit |

## Automated coverage

`python3 scripts/build.py` rebuilds the monitor, portal, 28 component pages, ADR register, 16 ADR pages and deployment guide. `python3 scripts/verify.py` checks HTML IDs, local navigation and fragments, styles/scripts/imports, current Markdown links, policy/fixture consistency, ADR evidence paths, Python parsing, live-mode configuration and four-store Compose contracts.

The checker permits only enumerated runtime routes and release assets; `--release` additionally requires the source ZIP and Git bundle. The release script checks archive CRC and produces SHA-256 checksums. Node tests exercise UI handlers and deployment-mode failure semantics. These are structural checks, not browser visual/accessibility validation.

External source URLs are inventoried rather than claimed continuously reachable. Primary Docker guidance for Compose readiness/startup ordering was checked during this review. Platform references and old scale results retain their dated scope; they are not assurances of current production suitability.

## Remaining execution gates

Docker is absent in the authoring environment. The actual SQL/OPA/gateway/Collector and restart suite must run on the development host or GitHub Actions before acceptance. No mock, SQLite run or schema inspection is counted as passing that gate. Browser-rendered visual/accessibility QA and real regional infrastructure checks remain outstanding.

Retained historical documents are clearly marked and excluded from current deployment instructions. Their archived source is evidence of earlier iterations, not a second supported installation path.

## Primary deployment references

- [Docker Compose startup ordering](https://docs.docker.com/compose/how-tos/startup-order/)
- [Docker Compose up and wait](https://docs.docker.com/reference/cli/docker/compose/up/)
- [CockroachDB local development clusters](https://www.cockroachlabs.com/docs/stable/start-a-local-cluster.html)

Run guides: [Development](DEVELOPMENT.md), [testing status](../TESTING.md), [ADRs](adr/README.md).
