// DOM-adapter smoke test; no browser layout/rendering claim.
import assert from 'node:assert/strict';
const nodes=new Map();
globalThis.document={querySelector(selector){
 if(!nodes.has(selector))nodes.set(selector,{value:selector==='#rate'?'500':selector==='#burst'?'20000':'12',style:{},handlers:{},addEventListener(type,fn){this.handlers[type]=fn;}});
 return nodes.get(selector);
}};
await import('../dist/isolation/app.mjs');
const n=id=>nodes.get('#'+id);
assert.equal(n('isolated-p99').textContent,'61.4 ms');
assert.equal(n('shared-p99').textContent,'20.85 s');
assert(n('chart').innerHTML.includes('<svg'));
n('stale').handlers.click();
assert(n('stale-result').textContent.includes('CURRENT_POLICY_DENIES'));
n('rate').value='800';n('rate').handlers.change();
assert(n('capacity-note').textContent.includes('exceeds'));
assert(n('isolated-p99').textContent.endsWith(' s'));
n('time').handlers.input({target:{value:'0'}});
assert.equal(n('guard-title').textContent,'Revision 7 active');
assert.equal(n('shared-bulk').textContent,'Not queued');
n('time').handlers.input({target:{value:'6'}});
assert.equal(n('guard-title').textContent,'UK restriction enforced');
n('reset').handlers.click();assert.equal(n('clock').textContent,'0 seconds');
console.log('PASS: model render, workload selection, stale-event check, timeline and reset handlers. Browser visual QA not performed.');
