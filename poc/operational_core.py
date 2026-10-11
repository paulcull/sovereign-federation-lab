"""Pure business commands and graph planning, independent from storage and policy transport."""
import copy,json,time,uuid,hashlib
from pathlib import Path
SPEC=json.loads((Path(__file__).resolve().parents[1]/'shared/operational.json').read_text())
TABLES=SPEC['tables'];ORDER=list(TABLES)
COMMANDS={'update_contact','withdraw_consent','restore_consent','open_holding','classify_restricted','classify_internal','log_contact','exclude_party_us','restore_party_us','table_contact_local','table_contact_restore'}
def seed():return copy.deepcopy(SPEC)
def resources(model,scope):
    index={(t,r['id']):r for t,rows in model['rows'].items() for r in rows}
    rules={(r['resource_type'],r['resource_id']):r for r in model['rules']}
    out=[]
    for b in model['bindings']:
        if b['scope_id']!=scope['id']:continue
        key=(b['resource_type'],b['resource_id'])
        if key not in index or key not in rules:raise ValueError('Unresolved sovereignty binding; fail closed')
        row=index[key];rule=rules[key];sensitivity=rule['sensitivity']
        for a in model['rows']['classification']:
            field={'party':'party_id','relationship':'relationship_id','product_holding':'holding_id'}.get(key[0])
            if field and a.get(field)==row['id'] and a['level'] not in ['PUBLIC','INTERNAL']:sensitivity='RESTRICTED'
        if key[0]=='classification' and row['level'] not in ['PUBLIC','INTERNAL']:sensitivity='RESTRICTED'
        consent=any(c['party_id']==row.get('party_id') and c['relationship_id']==scope['relationship_id'] and c['purpose']==scope['policy']['purpose'] and c['channel']==row.get('channel') and c['status']=='GRANTED' for c in model['rows']['consent'])
        out.append(dict(table=key[0],row=copy.deepcopy(row),rule=copy.deepcopy(rule),table_rule=copy.deepcopy(model['table_rules'][key[0]]),scope_kind=scope['scope_kind'],sensitivity=sensitivity,contact_consent=consent))
    return out
def manifest(model,scope,decisions):
    rows={(t,r['id']):r for t,rs in model['rows'].items() for r in rs};out=[];explain=copy.deepcopy(decisions)
    for d in explain:
        if d['allow']:
            row=rows[(d['table'],d['resource_id'])]
            out.append(dict(table=d['table'],row={k:row.get(k) for k in d['fields']}))
    # No child, alternate identifier or assignment can point to a withheld parent.
    while True:
        keys={(r['table'],r['row']['id']) for r in out}
        drop={(r['table'],r['row']['id']) for r in out if any(r['row'].get(p['field']) and (p['table'],r['row'][p['field']]) not in keys for p in TABLES[r['table']]['parents'])}
        if (scope['root_type'],scope['root_id']) not in keys:drop=keys
        if not drop:break
        out=[r for r in out if (r['table'],r['row']['id']) not in drop]
        for d in explain:
            if (d['table'],d['resource_id']) in drop:d.update(allow=False,reason='dependency withheld; no dangling reference',fields=[])
    return dict(rows=out,decisions=explain,row_counts={t:sum(r['table']==t for r in out) for t in ORDER})
def command(model,scope_id,body):
    command=body.get('command')
    if command not in COMMANDS:raise ValueError('Unknown business command')
    updated=copy.deepcopy(model);scope=next_scope(updated,scope_id)
    if body.get('expected_version')!=scope['data_version']:raise ValueError('Stale business version; refresh')
    changed=[];primary=scope['primary_party_id'];rid=scope['relationship_id'];auth=command in ['withdraw_consent','restore_consent','classify_restricted','classify_internal','exclude_party_us','restore_party_us','table_contact_local','table_contact_restore']
    def change(t,row):changed.append((t,row['id']))
    def add(t,row,scope_ids):
        updated['rows'][t].append(row);change(t,row)
        rule=dict(resource_type=t,resource_id=row['id'],allowed_countries=['SG','GB'],denied_countries=['US'],allowed_profiles=['minimal','contact'],sensitivity='INTERNAL')
        updated['rules'].append(rule)
        for sid in scope_ids:updated['bindings'].append(dict(scope_id=sid,resource_type=t,resource_id=row['id']))
    def history(text):add('contact_history',dict(id=str(uuid.uuid4()),party_id=primary,relationship_id=rid,channel='EMAIL',occurred_at=time.time(),summary=text,agent_id='DEMO-AGENT-01'),[scope_id])
    if scope['scope_kind']=='party' and command not in ['exclude_party_us','restore_party_us','table_contact_local','table_contact_restore']:raise ValueError('Choose a relationship scope for business commands')
    if command in ['exclude_party_us','restore_party_us']:
        rule=next(r for r in updated['rules'] if r['resource_type']=='party' and r['resource_id']==primary)
        rule['denied_countries']=['US'] if command=='exclude_party_us' else [];changed.append(('party',primary))
    elif command in ['table_contact_local','table_contact_restore']:
        updated['table_rules']['contact_info']['mode']='owner_only' if command=='table_contact_local' else 'relationship_policy'
        changed.extend(('contact_info',r['id']) for r in updated['rows']['contact_info'])
    elif command=='update_contact':
        value=body.get('value','updated.aster@example.invalid')
        if not isinstance(value,str) or len(value)>254 or not value.endswith('@example.invalid'):raise ValueError('Use a synthetic @example.invalid email')
        row=next(r for r in updated['rows']['contact_info'] if r['party_id']==primary and r['channel']=='EMAIL')
        row['value']=value;change('contact_info',row)
        pref=next(r for r in updated['rows']['preference'] if r['relationship_id']==rid)
        pref['contact_window']='10:00–16:00';change('preference',pref);history('Synthetic contact detail updated')
    elif command in ['withdraw_consent','restore_consent']:
        row=next(r for r in updated['rows']['consent'] if r['relationship_id']==rid and r['party_id']==primary and r['channel']=='EMAIL')
        row['status']='WITHDRAWN' if command=='withdraw_consent' else 'GRANTED';change('consent',row);history('Synthetic servicing consent '+row['status'].lower())
    elif command=='open_holding':
        typ=body.get('product_type','DEPOSIT')
        if typ not in ['DEPOSIT','CARD','LOAN']:raise ValueError('Unsupported demo product type')
        h=dict(id=str(uuid.uuid4()),relationship_id=rid,product_type=typ,status='ACTIVE',currency='SGD',balance='0.00');add('product_holding',h,[scope_id])
        add('holding_alternate_id',dict(id=str(uuid.uuid4()),holding_id=h['id'],scheme='CORE_ACCOUNT',value='DEMO-'+h['id'][:8]),[scope_id])
        add('classification',dict(id=str(uuid.uuid4()),subject_type='holding',party_id=None,relationship_id=None,holding_id=h['id'],code='STANDARD_PRODUCT',level='INTERNAL'),[scope_id])
    elif command in ['classify_restricted','classify_internal','exclude_party_us','restore_party_us','table_contact_local','table_contact_restore']:
        holdings=[r['id'] for r in updated['rows']['product_holding'] if r['relationship_id']==rid]
        row=next((r for r in updated['rows']['classification'] if r.get('holding_id') in holdings),None)
        if row is None:
            row=dict(id=str(uuid.uuid4()),subject_type='holding',party_id=None,relationship_id=None,holding_id=holdings[0],code='STANDARD_PRODUCT',level='INTERNAL');add('classification',row,[scope_id])
        row['level']='RESTRICTED' if command=='classify_restricted' else 'INTERNAL';change('classification',row)
        # Classification is a business fact that narrows the target resource decision.
        changed.append(('product_holding',row['holding_id']))
    else:history('Synthetic contact history entry; owner-only narrative')
    affected=sorted({b['scope_id'] for b in updated['bindings'] if (b['resource_type'],b['resource_id']) in changed})
    for s in updated['scopes']:
        if s['id'] in affected:
            s['data_version']+=1;s['decision_revision']+=int(auth)
            s['policy_generation']+=int(command in ['exclude_party_us','restore_party_us','table_contact_local','table_contact_restore'])
    return updated,dict(command=command,changed=[{'table':t,'id':i} for t,i in sorted(set(changed))],affected_scope_ids=affected,authorization_changed=auth,source_transaction='committed',replication='queued')
def next_scope(model,id):return next(s for s in model['scopes'] if s['id']==id)
