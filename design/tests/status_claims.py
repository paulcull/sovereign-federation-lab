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
                             'Executive summary: govern data by relationship',
                             'without combining their access rights', 'bank-approved policy',
                             'enterprise customer master data management',
                             'country labels do not prove physical residency',
                             'A route does not grant access', 'current authoritative owner',
                             'current permission and placement', 'freshness', 'old writer rejects',
                             'Every writer', 'mandatory audit', 'no offline authority lease',
                             'normalized business tables', 'no nearest-store fallback',
                             'Run the customer MDM integration pilot',
                             'system and experience APIs', 'single-host synthetic integration pilot',
                             'not bank deployment approval'),
}


def assert_current_status(text, slug):
    normalized = ' '.join(text.casefold().split())
    for claim in OBSOLETE_CLAIMS:
        assert ' '.join(claim.casefold().split()) not in normalized, (slug, 'obsolete claim', claim)
    for scope in CURRENT_SCOPE.get(slug, ()):
        assert scope.casefold() in normalized, (slug, 'missing scope or limit', scope)
