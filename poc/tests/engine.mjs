import {webcrypto} from 'node:crypto';import {readFile,writeFile} from 'node:fs/promises';import assert from 'node:assert/strict';
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const code=await readFile(new URL('../../dist/engine.js',import.meta.url),'utf8');
const {DemoEngine,decision,makeRecord,candidates}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const cat=JSON.parse(await readFile(new URL('../../shared/catalog.json',import.meta.url),'utf8'));
const engine=new DemoEngine(cat),s=engine.state,copies=c=>s.stores.flatMap(s=>s.replicas).filter(p=>p.record_id===c.id),drain=()=>{for(let i=0;i<180;i++)engine.tick();};
assert.equal(cat.entities.length,30);assert.deepEqual(['UK','Asia','Americas','MENAT','Europe'].map(g=>cat.entities.filter(e=>e.group===g).length),[3,8,3,5,11]);drain();
const canonical=s.customers.find(c=>c.scenario==='sg-uk-no-us');assert.deepEqual(copies(canonical).map(p=>p.destination_entity_id),['LE-GB-02']);
const shared=s.customers.find(c=>c.scenario==='shared-store-isolation');assert.deepEqual(copies(shared).map(p=>p.destination_entity_id),['LE-GB-02']);
const multi=s.customers.find(c=>c.scenario==='multi-entity');assert.equal(copies(multi).length,3);assert.equal(new Set(copies(multi).map(p=>p.store_id)).size,1);
for(const c of s.customers.filter(c=>c.scenario==='placement-blocked'))assert.equal(copies(c).length,0);
const geo=s.customers.find(c=>c.scenario==='geo-deny');assert(!copies(geo).some(p=>p.destination_entity_id==='LE-CA-01'));
assert.throws(()=>engine.relationship(canonical.id,'LE-US-01'));
const newOwner=engine.relationship(canonical.id,'LE-GB-02');assert.equal(newOwner.global_customer_id,canonical.global_customer_id);assert.deepEqual(newOwner.denied_countries,['US']);assert.deepEqual(newOwner.grants,{});
const before=copies(canonical)[0];assert.deepEqual(Object.keys(before.fields),['name','tier']);
engine.pause('STORE-GB-01',true);engine.policy(canonical.id,{expected_generation:canonical.generation,denied_entities:['LE-GB-02']});drain();assert(copies(canonical).length===1);assert(s.queue.some(q=>q.record_id===canonical.id&&q.reason.includes('purge pending')));assert(!decision(canonical,'LE-GB-02',cat).allow);
engine.pause('STORE-GB-01',false);drain();assert.equal(copies(canonical).length,0);engine.touch(canonical.id);drain();assert.equal(copies(canonical).length,0);
assert.throws(()=>engine.policy(canonical.id,{expected_generation:1,denied_entities:[]}));
const original=s.customers.find(c=>c.owner_entity_id==='LE-GB-01'&&c.scenario==='home-only');const sibling=s.customers.find(c=>c.global_customer_id===original.global_customer_id&&c.id!==original.id);assert(sibling);const version=sibling.version;engine.touch(original.id);drain();assert.equal(sibling.version,version);
const plan=engine.plan('LE-GB-02','STORE-US-01');assert(!plan.approved);assert.equal(plan.applied,false);assert.equal(cat.entities.find(e=>e.id==='LE-GB-02').store_id,'STORE-GB-01');
const expired=makeRecord(cat,999,'short-lived');engine.add(expired);drain();assert(copies(expired).length);expired.grants['LE-GB-02'].expires_at=0;drain();assert.equal(copies(expired).length,0);
console.log('PASS entity engine: directory counts, shared-store isolation, multi-recipient keys, geographic deny, placement blocks, revoke/pause/purge, stale edit, independent ownership, read-only placement plan and expiry');
// Cross-check every scenario and every recipient against actual OPA, including negative candidates.
if(process.env.PARITY_OUTPUT){const cases=[];for(let i=0;i<33;i++){const c=makeRecord(cat,i);for(const e of cat.entities){const input={customer:c,destination_entity:e,destination_store:cat.stores.find(s=>s.id===e.store_id),now:Date.now()/1000};cases.push({input,expected:decision(c,e.id,cat,input.now)});}}await writeFile(process.env.PARITY_OUTPUT,JSON.stringify(cases));console.log('Wrote',cases.length,'OPA parity cases');}
