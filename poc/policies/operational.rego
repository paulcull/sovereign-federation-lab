package operational
import rego.v1
# Dataset contract is part of the verified policy bundle, not caller-chosen fields.
row_allow(r) := true if {
    data.federation.allow
    cfg := data.operational_catalog[r.table]
    scope_dataset_ok(r)
    cfg.owner_only == false
    r.table_rule.mode != "owner_only"
    input.destination_store.country in r.table_rule.allowed_countries
    not input.destination_store.country in r.table_rule.denied_countries
    r.sensitivity in {"PUBLIC", "INTERNAL"}
    input.destination_store.country in r.rule.allowed_countries
    not input.destination_store.country in r.rule.denied_countries
    input.customer.grants[input.destination_entity.id].profile in r.rule.allowed_profiles
    contact_ok(r, cfg)
} else := false
scope_dataset_ok(r) if { r.scope_kind == "relationship" }
scope_dataset_ok(r) if { r.scope_kind == "party"; r.table == "party" }
contact_ok(r,cfg) if { cfg.needs_contact_consent == false }
contact_ok(r,cfg) if {
    cfg.needs_contact_consent == true
    input.customer.grants[input.destination_entity.id].profile == "contact"
    r.contact_consent == true
}
row_reason(r) := data.federation.reason if { not data.federation.allow }
else := "unregistered dataset" if { not data.operational_catalog[r.table] }
else := "dataset outside scope kind" if { not scope_dataset_ok(r) }
else := "owner-only dataset" if { data.operational_catalog[r.table].owner_only }
else := "table restricted to owner" if { r.table_rule.mode == "owner_only" }
else := "table country exclusion" if { input.destination_store.country in r.table_rule.denied_countries }
else := "table country outside allowlist" if { not input.destination_store.country in r.table_rule.allowed_countries }
else := "restricted classification" if { not r.sensitivity in {"PUBLIC", "INTERNAL"} }
else := "resource country exclusion" if { input.destination_store.country in r.rule.denied_countries }
else := "resource country outside allowlist" if { not input.destination_store.country in r.rule.allowed_countries }
else := "resource profile restriction" if { not input.customer.grants[input.destination_entity.id].profile in r.rule.allowed_profiles }
else := "contact profile required" if {
    data.operational_catalog[r.table].needs_contact_consent
    input.customer.grants[input.destination_entity.id].profile != "contact"
}
else := "no matching servicing contact consent" if {
    data.operational_catalog[r.table].needs_contact_consent
    r.contact_consent == false
}
else := "approved dataset fields" if { row_allow(r) }
else := "default deny"
row_fields(r) := data.operational_catalog[r.table].global_fields if { row_allow(r); r.scope_kind == "party" }
else := data.operational_catalog[r.table].export_fields if { row_allow(r) } else := []
decisions := [{"table":r.table,"resource_id":r.row.id,"allow":row_allow(r),"reason":row_reason(r),"fields":row_fields(r)} | r:=input.resources[_]]
