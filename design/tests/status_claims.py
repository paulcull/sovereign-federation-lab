"""Shared status contract for current generated pages and rendered reader checks."""

OBSOLETE_CLAIMS = (
    'database end-to-end execution is not verified',
    'controlled migration execution is deferred',
    'no home migration is implemented',
    'Collector export and real database spans still need local end-to-end verification',
)

# Keep positive scope and limitations together; removing a stale sentence alone is insufficient.
CURRENT_SCOPE = {
    'operations': ('isolated India migration', 'normalized-table migration', 'automatic regional failover'),
    'observability': ('API-generated logs', 'matching trace IDs', 'debug exporter', 'regional telemetry isolation'),
    'service-transactions': ('Proposed pilot design', 'Business services', 'Sovereignty services',
                             'A route does not grant access', 'current authoritative owner',
                             'current permission and placement', 'freshness', 'old writer rejects',
                             'Every writer', 'mandatory audit', 'no offline authority lease',
                             'normalized business tables', 'no nearest-store fallback'),
}


def assert_current_status(text, slug):
    normalized = ' '.join(text.casefold().split())
    for claim in OBSOLETE_CLAIMS:
        assert ' '.join(claim.casefold().split()) not in normalized, (slug, 'obsolete claim', claim)
    for scope in CURRENT_SCOPE.get(slug, ()):
        assert scope.casefold() in normalized, (slug, 'missing scope or limit', scope)
