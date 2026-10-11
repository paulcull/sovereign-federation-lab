"""Synthetic legal-entity federation fixtures; no real bank policy or customer data."""
import json,time,uuid
from pathlib import Path
CATALOG=json.loads((Path(__file__).resolve().parents[1]/'shared/catalog.json').read_text())
ENTITIES={e['id']:e for e in CATALOG['entities']}
STORE_INFO={s['id']:s for s in CATALOG['stores']}
REGIONS=['SG','UK','US']
SCENARIOS=['sg-uk-no-us','shared-store-isolation','multi-entity','geo-deny','placement-blocked','no-entitlement','expired','contact','short-lived','home-only','world-tour']
def placement(e):
    return STORE_INFO[e['store_id']]['country'] in e['approved_countries']
def make_record(index=0,scenario=None,owner=None):
    scenario=scenario or SCENARIOS[index%len(SCENARIOS)]
    valid=[e['id'] for e in CATALOG['entities'] if placement(e)]
    owner=owner or valid[index%len(valid)]
    candidates=['LE-GB-01','LE-SG-01','LE-US-01']
    denied=[];denied_countries=[];profile='minimal';expiry=time.time()+86400
    if scenario=='sg-uk-no-us':owner='LE-SG-01';candidates=['LE-GB-02','LE-US-01'];denied_countries=['US']
    elif scenario=='shared-store-isolation':owner='LE-GB-01';candidates=['LE-GB-02','LE-GB-03'];denied=['LE-GB-03']
    elif scenario=='multi-entity':owner='LE-SG-01';candidates=['LE-GB-01','LE-GB-02','LE-FR-01']
    elif scenario=='geo-deny':owner='LE-SG-01';candidates=['LE-GB-02','LE-CA-01'];denied_countries=['US']
    elif scenario=='placement-blocked':owner='LE-SG-01';candidates=['LE-IN-01','LE-DE-01','LE-SA-01']
    elif scenario=='contact':candidates=['LE-GB-02' if owner!='LE-GB-02' else 'LE-SG-01'];profile='contact'
    elif scenario=='short-lived':owner='LE-SG-01';candidates=['LE-GB-02'];expiry=time.time()+20
    elif scenario=='home-only':candidates=[]
    elif scenario=='world-tour':candidates=valid[index%len(valid):]+valid[:index%len(valid)];candidates=candidates[:5]
    if scenario=='expired':expiry=time.time()-60
    candidates=[d for d in candidates if d!=owner]
    allowed=[d for d in candidates if d not in denied]
    # Deliberate contradiction: deny must win even when entity is also allowed.
    if scenario=='shared-store-isolation':allowed=candidates[:]
    return dict(id=str(uuid.uuid4()),global_customer_id=str(uuid.uuid4()),owner_entity_id=owner,name=f'Example Customer {index+1:03}',email=f'customer{index+1}@example.invalid',tier=['Retail','Premier','Business'][index%3],notes='SYNTHETIC · owner-only notes',scenario=scenario,allowed_entities=allowed,denied_entities=denied,allowed_countries=['SG','GB','US'],denied_countries=denied_countries,grants={d:dict(active=scenario!='no-entitlement',expires_at=expiry,profile=profile,purpose='servicing') for d in candidates},purpose='servicing')
