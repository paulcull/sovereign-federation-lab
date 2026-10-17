package servicing
import rego.v1

# A separate service contract, evaluated using server-registered identities and
# server-fixed placement. Caller headers cannot assert owner or country.
default allow := false

allow if {
    input.service_id == "servicing-cases"
    input.owner_entity_id == "LE-SG-01"
    input.store_country == "SG"
    input.principal.entity_id == input.owner_entity_id
    input.principal.processing_country == "SG"
    input.action in input.principal.actions
    input.action in {"case.create", "case.read", "case.close", "case.reopen", "case.export"}
}

allow if {
    input.service_id == "servicing-cases"
    input.owner_entity_id == "LE-SG-01"
    input.store_country == "SG"
    input.principal.entity_id == "LE-GB-02"
    input.principal.processing_country == "GB"
    input.action == "case.export"
    input.action in input.principal.actions
}

allow if {
    input.service_id == "servicing-cases"
    input.owner_entity_id == "LE-SG-01"
    input.store_country == "GB"
    input.principal.entity_id == "LE-GB-02"
    input.principal.processing_country == "GB"
    input.action == "case.import"
    input.action in input.principal.actions
}

decision := {"allow": allow, "revision": 1, "fields": fields}
fields := ["case_id", "status", "category", "data_version"] if {
    allow
    input.action in {"case.export", "case.import"}
} else := []
