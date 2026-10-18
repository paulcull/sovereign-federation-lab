// Deployment selects the mode. A failed live service never selects a demo.
let deployment;
export function readDeployment() {
  deployment ??= (async () => {
    const response=await fetch('/lab-config.json',{cache:'no-store',signal:AbortSignal.timeout(6000)});
    if(!response.ok)throw Error('Deployment configuration unavailable');
    const config=await response.json();
    if(!['live','simulation'].includes(config.mode)||(config.mode==='live'&&config.database!=='cockroach'))throw Error('Deployment mode could not be verified');
    return config;
  })();
  return deployment;
}
export function showRuntime(target,state,title,detail) {
  target.dataset.state=state;target.replaceChildren();
  const mark=document.createElement('span');mark.className='runtime-light';mark.setAttribute('aria-hidden','true');
  const text=document.createElement('div'),heading=document.createElement('strong'),description=document.createElement('span');
  heading.textContent=title;description.textContent=detail;text.append(heading,description);target.append(mark,text);
}
async function baseStatus(target) {
  try {
    const config=await readDeployment();
    if(config.mode==='simulation') {
      if(target.dataset.runtimeContext==='cluster')showRuntime(target,'demo','STATIC PREVIEW · no cluster backend','Cluster status and operations require the container API. No real cluster connection is available here.');
      else if(target.dataset.runtimeContext==='portal')showRuntime(target,'demo','BROWSER DEMOS · no backend connection','This site hosts documentation and browser examples. Its pages are not connected to the private container pilot.');
      else showRuntime(target,'demo','BROWSER DEMO · no backend connection','Synthetic data and calculations run in this browser. Changes do not reach CockroachDB or OPA.');return;
    }
    const response=await fetch('/api/health/ready',{cache:'no-store',signal:AbortSignal.timeout(8000)}),status=await response.json();
    if(!response.ok||status.status!=='ready'||status.database!=='cockroach')throw Error('Dependencies unavailable');
    const count=status.stores?.filter(s=>s.database&&s.policy).length;if(!count)throw Error('Database evidence unavailable');
    const compact=status.footprint==='mdm-compact';
    showRuntime(target,'live',compact?'LIVE BACKEND · compact MDM':'LIVE BACKEND · container lab',
      `${count} real CockroachDB stores and OPA checked at ${new Date().toLocaleTimeString()}. `+
      (compact?'SG + UK active. US, India, migration and telemetry suspended.':'Synthetic data on one host. This is not a production deployment.'));
  } catch {showRuntime(target,'offline','LIVE CONNECTION NOT VERIFIED','Backend or deployment configuration unavailable. No automatic switch to a browser demo.');}
}
for(const target of document.querySelectorAll('[data-runtime-status="lab"]')) {
  baseStatus(target);setInterval(()=>{if(!document.hidden)baseStatus(target);},20000);
}
