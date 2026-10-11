package federation_test
import rego.v1
base := {"owner_entity_id":"LE-SG-01","allowed_entities":["LE-GB-02","LE-CA-01"],"denied_entities":[],"allowed_countries":["SG","GB","US"],"denied_countries":[],"purpose":"servicing","grants":{"LE-GB-02":{"active":true,"expires_at":2000,"profile":"minimal","purpose":"servicing"},"LE-CA-01":{"active":true,"expires_at":2000,"profile":"contact","purpose":"servicing"}}}
e := {"id":"LE-GB-02","store_id":"STORE-GB-01","approved_countries":["GB"],"accepts_inbound":true,"placement_version":1}
s := {"id":"STORE-GB-01","country":"GB"}
fixture := {"customer":base,"destination_entity":e,"destination_store":s,"now":1000}
test_minimal if { d:=data.federation.decision with input as fixture; d.allow; d.fields==["name","tier"] }
test_entity_deny_overrides if { c:=object.union(base,{"denied_entities":["LE-GB-02"]}); not data.federation.allow with input as object.union(object.remove(fixture,["customer"]),{"customer":c}) }
test_physical_country_deny if { c:=object.union(base,{"denied_countries":["GB"]}); d:=data.federation.decision with input as object.union(object.remove(fixture,["customer"]),{"customer":c}); not d.allow; d.reason=="physical country excluded" }
test_entity_local_placement if { local:=object.union(e,{"approved_countries":["DE"]}); d:=data.federation.decision with input as object.union(fixture,{"destination_entity":local}); not d.allow; d.reason=="no approved physical placement" }
test_expiry_boundary if { d:=data.federation.decision with input as object.union(fixture,{"now":2000}); not d.allow; d.reason=="entitlement expired" }
test_no_grant if { c:=object.union(object.remove(base,["grants"]),{"grants":{}}); not data.federation.allow with input as object.union(object.remove(fixture,["customer"]),{"customer":c}) }
test_country_allowlist if { c:=object.union(base,{"allowed_countries":["SG"]}); not data.federation.allow with input as object.union(object.remove(fixture,["customer"]),{"customer":c}) }
test_same_store_no_implicit_access if { other:=object.union(e,{"id":"LE-GB-03"}); not data.federation.allow with input as object.union(fixture,{"destination_entity":other}) }
test_store_binding_mismatch if { other:=object.union(s,{"id":"STORE-US-01"}); not data.federation.allow with input as object.union(fixture,{"destination_store":other}) }
test_purpose_mismatch if { c:=object.union(base,{"purpose":"marketing"}); not data.federation.allow with input as object.union(object.remove(fixture,["customer"]),{"customer":c}) }
test_contact if { ca:={"id":"LE-CA-01","store_id":"STORE-US-01","approved_countries":["US"],"accepts_inbound":true,"placement_version":2}; us:={"id":"STORE-US-01","country":"US"}; d:=data.federation.decision with input as {"customer":base,"destination_entity":ca,"destination_store":us,"now":1000};d.allow;d.fields==["name","tier","email"];d.placement_version==2 }
test_canadian_entity_us_store_blocked if { c:=object.union(base,{"denied_countries":["US"]});ca:={"id":"LE-CA-01","store_id":"STORE-US-01","approved_countries":["US"],"accepts_inbound":true,"placement_version":1};d:=data.federation.decision with input as {"customer":c,"destination_entity":ca,"destination_store":{"id":"STORE-US-01","country":"US"},"now":1000};not d.allow;d.reason=="physical country excluded" }
