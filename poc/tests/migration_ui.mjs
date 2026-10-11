// Structural UI/handler test. This is not browser rendering or accessibility QA.
import fs from 'node:fs/promises';import assert from 'node:assert/strict';
const root=new URL('../../dist/',import.meta.url),nodes=new Map(),timers=new Map();let timerID=0;
function node(key){if(!nodes.has(key))nodes.set(key,{innerHTML:'',textContent:'',dataset:{}});return nodes.get(key);}
const buttons=['update','create','delete'].map(kind=>({dataset:{write:kind}}));
globalThis.document={querySelector:node,querySelectorAll:selector=>selector==='[data-write]'?buttons:[]};
globalThis.location={hostname:'hosted-demo.example'};
globalThis.setInterval=fn=>{timers.set(++timerID,fn);return timerID;};globalThis.clearInterval=id=>timers.delete(id);
globalThis.fetch=async path=>({ok:true,json:async()=>path==='/lab-config.json'?{mode:'simulation'}:JSON.parse(await fs.readFile(new URL(path,root),'utf8'))});
await import('../../dist/migration/app.mjs');
assert.match(node('#main').innerHTML,/49/);assert.equal(node('#connection').textContent,'Browser simulation');
// Drive actual event handlers, including traffic, until validation.
await node('#next').onclick();await node('#next').onclick();await node('#next').onclick();
await buttons[1].onclick();await buttons[0].onclick();
node('#auto').onclick();
for(let i=0;i<40&&timers.size;i++)for(const fn of [...timers.values()])await fn();
assert.match(node('#main').innerHTML,/VALIDATED/);assert.equal(timers.size,0);
await node('#next').onclick();assert.match(node('#main').innerHTML,/FENCED/);
await node('#other').onclick();await node('#next').onclick();
assert.match(node('#main').innerHTML,/WRITER EPOCH 2/);
await node('#oldwrite').onclick();assert.match(node('#main').innerHTML,/Stale route/);
for(let i=0;i<12&&!node('#main').innerHTML.includes('Live migration complete');i++)await node('#next').onclick();
assert.match(node('#main').innerHTML,/Live migration complete/);
console.log('PASS relocation UI markup and click handlers through copy, validation, fence, activation, stale route denial and cleanup. Structural test only.');
