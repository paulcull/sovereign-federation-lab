// Current design-site handlers. Structural test; no rendered-browser claim.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const toggles={};const classes={toggle:(key,value)=>toggles[key]=value};
const menu={attrs:{'aria-expanded':'false'},getAttribute(k){return this.attrs[k]},setAttribute(k,v){this.attrs[k]=v}};
let printed=0,copyHandler,printHandler;const status={textContent:''},details={open:false};
const target={textContent:'Engineering prompt',closest:()=>details};
const copy={dataset:{target:'engineering-prompt'},parentElement:{querySelector:()=>status},addEventListener:(_,fn)=>copyHandler=fn};
const nodes={'menu-toggle':menu,sidebar:{classList:classes},'print-page':{addEventListener:(_,fn)=>printHandler=fn},'engineering-prompt':target};
const document={body:{dataset:{page:'architecture'}},getElementById:id=>nodes[id],querySelectorAll:s=>s==='nav a'?[{dataset:{page:'architecture'},classList:classes}]:s==='.copy-prompt'?[copy]:[]};
const navigator={clipboard:{writeText:async text=>assert.equal(text,'Engineering prompt')}};
vm.runInNewContext(fs.readFileSync(require.resolve('../dist/app.js'),'utf8'),{document,navigator,window:{print:()=>printed++}});
(async()=>{
 assert.equal(toggles.active,true);menu.onclick();assert.equal(menu.attrs['aria-expanded'],'true');assert.equal(toggles.open,true);
 menu.onclick();assert.equal(toggles.open,false);printHandler();assert.equal(printed,1);
 await copyHandler();assert.equal(status.textContent,'Engineering prompt copied.');
 navigator.clipboard.writeText=async()=>{throw Error('clipboard denied')};await copyHandler();assert.equal(details.open,true);assert.match(status.textContent,/Select and copy/);
 console.log('PASS current design navigation, mobile menu, print, clipboard success and manual-copy fallback.');
})().catch(e=>{console.error(e);process.exitCode=1});
