# Architecture decision register

Retrospective decisions recorded on 11 October 2026.

- [ADR-0001: Independent geographic database cells](ADR-0001.md) — Accepted design; single-node lab implemented
- [ADR-0002: Legal entity is separate from physical placement](ADR-0002.md) — Accepted design; static catalog plus isolated migration implemented
- [ADR-0003: Deny overrides grants and geographic eligibility](ADR-0003.md) — Accepted and implemented in fixture policies
- [ADR-0004: Minimal global party identity and scoped relationship graphs](ADR-0004.md) — Accepted; normalized example implemented
- [ADR-0005: One local ACID business boundary](ADR-0005.md) — Accepted; Python harness implemented, Spring Boot consolidation is pilot work
- [ADR-0006: Outbox now, regional CDC and durable bus later](ADR-0006.md) — Accepted; SQL polling/journal implemented, CDC/Kafka proposed
- [ADR-0007: OPA rules with trusted current facts](ADR-0007.md) — Accepted; local OPA calls implemented, signed distribution proposed
- [ADR-0008: Audit evidence and OpenTelemetry are distinct](ADR-0008.md) — Accepted; regional SQL audit and OTel wiring implemented
- [ADR-0009: Separate authority, operational and bulk capacity](ADR-0009.md) — Accepted target design; executable queue model only
- [ADR-0010: Treat capacity results as models and targets](ADR-0010.md) — Accepted analysis method; measured database targets pending
- [ADR-0011: Source-writable copy followed by fenced cutover](ADR-0011.md) — Accepted; isolated migration implemented
- [ADR-0012: Separate denial, live purge and retained-storage disposal](ADR-0012.md) — Accepted; live-copy cleanup implemented
- [ADR-0013: One node per store and one coordinator for the lab](ADR-0013.md) — Accepted lab scope; production HA explicitly excluded
- [ADR-0014: CockroachDB is mandatory for development deployment](ADR-0014.md) — Accepted and enforced at service entry points
- [ADR-0015: One portable repository and verified documentation navigation](ADR-0015.md) — Accepted; consolidated lab implemented
- [ADR-0016: A development gateway with explicit production boundary](ADR-0016.md) — Accepted; local HTTP gateway implemented
