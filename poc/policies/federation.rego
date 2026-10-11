package federation
import rego.v1
# Trusted harness resolves these directory attributes. Future gateways must verify them.
default allow := false
entity := input.destination_entity
store := input.destination_store
customer := input.customer
allow if {
    entity.id != customer.owner_entity_id
    entity.id in customer.allowed_entities
    not entity.id in customer.denied_entities
    store.id == entity.store_id
    store.country in entity.approved_countries
    entity.accepts_inbound == true
    store.country in customer.allowed_countries
    not store.country in customer.denied_countries
    grant := customer.grants[entity.id]
    grant.active == true
    grant.expires_at > input.now
    grant.purpose == customer.purpose
    grant.profile in {"minimal", "contact"}
}
reason := "entity explicitly excluded" if { entity.id in customer.denied_entities }
else := "physical country excluded" if { store.country in customer.denied_countries }
else := "no approved physical placement" if { not store.country in entity.approved_countries }
else := "store binding mismatch" if { store.id != entity.store_id }
else := "physical country outside customer allowlist" if { not store.country in customer.allowed_countries }
else := "entity outside sharing allowlist" if { not entity.id in customer.allowed_entities }
else := "no active entitlement" if { not customer.grants[entity.id].active }
else := "entitlement expired" if { customer.grants[entity.id].expires_at <= input.now }
else := "purpose mismatch" if { customer.grants[entity.id].purpose != customer.purpose }
else := "permitted" if { allow }
else := "default deny"
fields := ["name", "tier", "email"] if {
    allow
    customer.grants[entity.id].profile == "contact"
} else := ["name", "tier"] if { allow } else := []
decision := {"allow":allow,"reason":reason,"fields":fields,"placement_version":entity.placement_version}
