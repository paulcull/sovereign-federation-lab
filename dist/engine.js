export const SCENARIOS=['sg-uk-no-us','shared-store-isolation','multi-entity','geo-deny','placement-blocked','no-entitlement','expired','contact','short-lived','home-only','world-tour'];
const now=()=>Date.now()/1000,uid=()=>crypto.randomUUID();
export const entity=(cat,id)=>cat.entities.find(e=>e.id===id);
export const store=(cat,id)=>cat.stores.find(s=>s.id===id);
export const placed=(cat,e)=>e.approved_countries.includes(store(cat,e.store_id).country);
export function decision(c,dest,cat,t=now()){
 const e=entity(cat,dest),s=e&&store(cat,e.store_id),deny=reason=>({allow:false,reason,fields:[]});
 if(!e||!s)return deny('unknown entity or store');
 if(c.denied_entities.includes(dest))return deny('entity explicitly excluded');
 if(c.denied_countries.includes(s.country))return deny('physical country excluded');
 if(!placed(cat,e))return deny('no approved physical placement');
 if(!c.allowed_countries.includes(s.country))return deny('physical country outside customer allowlist');
 if(!c.allowed_entities.includes(dest))return deny('entity outside sharing allowlist');
 const g=c.grants[dest];if(!g?.active)return deny('no active entitlement');
 if(g.expires_at<=t)return deny('entitlement expired');if(g.purpose!==c.purpose)return deny('purpose mismatch');
 if(dest===c.owner_entity_id||!e.accepts_inbound||!['minimal','contact'].includes(g.profile))return deny('default deny');
 return {allow:true,reason:'permitted',fields:g.profile==='contact'?['name','tier','email']:['name','tier'],placement_version:e.placement_version};
}
export function makeRecord(cat,index=0,scenario=SCENARIOS[index%SCENARIOS.length],owner){
 const valid=cat.entities.filter(e=>placed(cat,e)).map(e=>e.id);owner=owner||valid[index%valid.length];
 let targets=['LE-GB-01','LE-SG-01','LE-US-01'],denied=[],countries=[],profile='minimal',expiry=now()+86400;
 if(scenario==='sg-uk-no-us'){owner='LE-SG-01';targets=['LE-GB-02','LE-US-01'];countries=['US'];}
 if(scenario==='shared-store-isolation'){owner='LE-GB-01';targets=['LE-GB-02','LE-GB-03'];denied=['LE-GB-03'];}
 if(scenario==='multi-entity'){owner='LE-SG-01';targets=['LE-GB-01','LE-GB-02','LE-FR-01'];}
 if(scenario==='geo-deny'){owner='LE-SG-01';targets=['LE-GB-02','LE-CA-01'];countries=['US'];}
 if(scenario==='placement-blocked'){owner='LE-SG-01';targets=['LE-IN-01','LE-DE-01','LE-SA-01'];}
 if(scenario==='contact'){targets=[owner!=='LE-GB-02'?'LE-GB-02':'LE-SG-01'];profile='contact';}
 if(scenario==='short-lived'){owner='LE-SG-01';targets=['LE-GB-02'];expiry=now()+20;}
 if(scenario==='home-only')targets=[];
 if(scenario==='world-tour')targets=[...valid.slice(index%valid.length),...valid.slice(0,index%valid.length)].slice(0,5);
 if(scenario==='expired')expiry=now()-60;
 targets=targets.filter(e=>e!==owner);
 return {id:uid(),global_customer_id:uid(),owner_entity_id:owner,name:`Example Customer ${String(index+1).padStart(3,'0')}`,email:`customer${index+1}@example.invalid`,tier:['Retail','Premier','Business'][index%3],notes:'SYNTHETIC · owner-only notes',scenario,allowed_entities:[...targets],denied_entities:denied,allowed_countries:['SG','GB','US'],denied_countries:countries,grants:Object.fromEntries(targets.map(e=>[e,{active:scenario!=='no-entitlement',expires_at:expiry,profile,purpose:'servicing'}])),purpose:'servicing',version:1,generation:1,contacted:[],expired_seen:[],created_at:now()};
}
export const candidates=c=>[...new Set([...c.allowed_entities,...c.denied_entities,...Object.keys(c.grants),...c.contacted])].filter(e=>e!==c.owner_entity_id).sort();
export class DemoEngine{
 constructor(cat){this.cat=cat;this.counter=0;this.state={schema_version:2,mode:'demo',entities:cat.entities,stores:cat.stores.map(s=>({...s,online:true,paused:false,masters:0,replicas:[]})),customers:[],events:[],queue:[],now:now()};for(let i=0;i<33;i++)this.add(makeRecord(cat,this.counter++));const a=makeRecord(cat,101,'home-only','LE-GB-01');this.add(a);this.add({...makeRecord(cat,102,'home-only','LE-GB-02'),global_customer_id:a.global_customer_id,name:a.name,email:a.email,tier:'Business'});}
 event(c,dest,status,reason){this.state.events.unshift({id:uid(),time:now(),record_id:c.id,global_customer_id:c.global_customer_id,name:c.name,owner_entity_id:c.owner_entity_id,destination_entity_id:dest,source_store:entity(this.cat,c.owner_entity_id).store_id,destination_store:entity(this.cat,dest).store_id,status,reason,generation:c.generation,placement_version:entity(this.cat,dest).placement_version});this.state.events=this.state.events.slice(0,180);}
 enqueue(c){for(const dest of candidates(c))this.state.queue.push({id:uid(),record_id:c.id,source_store:entity(this.cat,c.owner_entity_id).store_id,destination_entity_id:dest,status:'queued',attempts:0,reason:''});}
 add(c){const e=entity(this.cat,c.owner_entity_id);if(!placed(this.cat,e))throw Error('Owner has no approved physical placement');const country=store(this.cat,e.store_id).country;if(c.denied_countries.includes(country)||!c.allowed_countries.includes(country))throw Error('Policy excludes the authoritative store');if(this.state.customers.some(d=>d.owner_entity_id===c.owner_entity_id&&d.global_customer_id===c.global_customer_id))throw Error('Relationship already exists');this.state.customers.unshift(c);this.state.stores.find(s=>s.id===e.store_id).masters++;this.enqueue(c);this.event(c,c.owner_entity_id,'committed','Entity-owned record + durable outbox');return c;}
 generate(count,scenario){return Array.from({length:count},()=>this.add(makeRecord(this.cat,this.counter++,scenario==='mixed'?undefined:scenario)));}
 policy(id,body){const c=this.state.customers.find(c=>c.id===id);if(body.expected_generation!==c.generation)throw Error('Policy changed; refresh');const next={...c,...body};const country=store(this.cat,entity(this.cat,c.owner_entity_id).store_id).country;if(next.denied_countries.includes(country)||!next.allowed_countries.includes(country)||next.denied_entities.includes(c.owner_entity_id))throw Error('Cannot exclude the authoritative owner or store');for(const k of ['allowed_entities','denied_entities','allowed_countries','denied_countries','grants'])if(body[k])c[k]=body[k];c.generation++;this.enqueue(c);this.event(c,c.owner_entity_id,'policy','Entity / geography policy changed');return c;}
 touch(id){const c=this.state.customers.find(c=>c.id===id);c.version++;c.tier=c.tier==='Premier'?'Retail':'Premier';this.enqueue(c);return c;}
 relationship(id,owner){const c=this.state.customers.find(c=>c.id===id),permit=decision(c,owner,this.cat);if(!permit.allow)throw Error('Cannot disclose the shared global ID: '+permit.reason);const d=makeRecord(this.cat,this.counter++,'home-only',owner);Object.assign(d,{global_customer_id:c.global_customer_id,allowed_countries:[...c.allowed_countries],denied_countries:[...c.denied_countries]});return this.add(d);}
 pause(id,paused){this.state.stores.find(s=>s.id===id).paused=paused;}
 plan(id,sid){const e=entity(this.cat,id),s=store(this.cat,sid),affected=this.state.customers.filter(c=>c.owner_entity_id===id||candidates(c).includes(id)),conflicts=affected.filter(c=>c.denied_countries.includes(s.country)||!c.allowed_countries.includes(s.country));return {entity_id:id,current_store:e.store_id,proposed_store:sid,approved:e.approved_countries.includes(s.country)&&!conflicts.length,entity_country_allowed:e.approved_countries.includes(s.country),affected_records:affected.length,conflicting_records:conflicts.map(c=>c.id),placement_version:e.placement_version,applied:false,stages:['Validate residency','Fence old writer','Copy & reconcile','Verify destination','Switch versioned routing','Reconcile old copies']};}
 tick(){this.state.now=now();for(const c of this.state.customers){const expired=Object.entries(c.grants).filter(([e,g])=>g.expires_at<=now()).map(([e,g])=>e+':'+g.expires_at).sort();if(JSON.stringify(expired)!==JSON.stringify(c.expired_seen)){c.expired_seen=expired;c.generation++;this.enqueue(c);}}
 let budget=3;for(const q of [...this.state.queue]){if(!budget--)break;const c=this.state.customers.find(c=>c.id===q.record_id),dest=q.destination_entity_id,s=this.state.stores.find(s=>s.id===entity(this.cat,dest).store_id),d=decision(c,dest,this.cat);q.attempts++;
 if(!d.allow&&!c.contacted.includes(dest)){this.event(c,dest,d.reason.includes('placement')?'placement_blocked':'blocked',d.reason+' · never sent');}else{if(s.paused){q.status='retry';q.reason='Store ingress paused'+(!d.allow?'; purge pending':'');this.state.queue.push(this.state.queue.splice(this.state.queue.indexOf(q),1)[0]);continue;}
 s.replicas=s.replicas.filter(p=>!(p.record_id===c.id&&p.destination_entity_id===dest));if(d.allow){if(!c.contacted.includes(dest))c.contacted.push(dest);s.replicas.push({record_id:c.id,global_customer_id:c.global_customer_id,owner_entity_id:c.owner_entity_id,destination_entity_id:dest,store_id:s.id,version:c.version,generation:c.generation,placement_version:d.placement_version,fields:Object.fromEntries(d.fields.map(k=>[k,c[k]])),replicated_at:now()});this.event(c,dest,'replicated','permitted');}else this.event(c,dest,'purged',d.reason);}
 this.state.queue=this.state.queue.filter(t=>t.id!==q.id);
 }}
}
