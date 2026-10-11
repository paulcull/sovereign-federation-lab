import assert from 'node:assert/strict';
import {labMode} from '../../dist/lab-mode.mjs';
globalThis.fetch=async()=>({ok:true,json:async()=>({mode:'live',database:'cockroach'})});assert.equal(await labMode(),'live');
globalThis.fetch=async()=>({ok:true,json:async()=>({mode:'simulation'})});assert.equal(await labMode(),'simulation');
globalThis.fetch=async()=>({ok:true,json:async()=>({mode:'live',database:'sqlite'})});await assert.rejects(labMode());
globalThis.fetch=async()=>({ok:false});await assert.rejects(labMode());
globalThis.fetch=async()=>{throw Error('network down');};await assert.rejects(labMode());
console.log('PASS deployment-selected mode; no SQLite or implicit simulation fallback.');
