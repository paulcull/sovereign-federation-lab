// SPDX-License-Identifier: MIT
const $ = (s) => document.querySelector(s);
const main = $('#main');
const escape = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const e = escape;
let fleet = null, histories = {}, environment = null, route = {}, filter = 'all', search = '', selectedJob = '', refreshing = false, actionCluster = '', requestId = '';
const labels = {healthy:'Healthy', attention:'Needs attention', partial:'Partial visibility', unreachable:'Unreachable', succeeded:'Succeeded', running:'Running', queued:'Queued', failed:'Failed', interrupted:'Needs inspection', unavailable:'Unavailable'};
const kinds = {health_check:'Cluster health check', recovery_rehearsal:'Recovery rehearsal'};
const date = (ts) => ts ? new Date(ts * 1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : 'Not run yet';
const bytes = v => v == null ? '—' : v >= 1073741824 ? (v / 1073741824).toFixed(1) + ' GiB' : Math.round(v / 1048576) + ' MiB';
const badge = (s) => `<span class="status ${e(s)}" title="Operational observation, not a security or resilience approval">${e(labels[s] || s)}</span>`;
const heading = (title, description, eyebrow = 'DATABASE OPERATIONS', actions = '<button class="button secondary" data-refresh aria-label="Refresh status"><span aria-hidden="true">↻</span> Refresh status</button>') => `<div class="page-heading"><div><p class="eyebrow">${eyebrow}</p><h1>${e(title)}</h1><p>${description}</p></div><div class="heading-actions">${actions}</div></div>`;
const stat = (label, value, note, cls = '') => `<div class="stat"><div class="stat-label">${e(label)}</div><div class="value ${cls}">${value}</div><small>${e(note)}</small></div>`;
const total = (c, field) => c.nodes.reduce((sum, n) => sum + (n[field] || 0), 0);
const definition = (rows) => `<dl class="definition-list">${rows.map(([label,value])=>`<div><dt>${e(label)}</dt><dd>${value}</dd></div>`).join('')}</dl>`;
const clusterRoute = (id, tab='overview') => `cluster=${id}&tab=${tab}`;

async function api(path, options={}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch('/api/cluster-control/' + path, {cache:'no-store', signal:controller.signal, ...options});
    if (!response.ok) {
      let body = {}; try { body = await response.json(); } catch {}
      throw new Error(typeof body.detail === 'string' ? body.detail : `Cluster API returned ${response.status}`);
    }
    return await response.json();
  } finally { clearTimeout(timer); }
}

function navigate(value) { location.hash = value; }
function readRoute() {
  const params = new URLSearchParams(location.hash.slice(1));
  return {page: params.get('page') || 'fleet', cluster:params.get('cluster'), tab:params.get('tab') || 'overview'};
}

function fleetCards() {
  const clusters = fleet.clusters.filter(c => (filter === 'all' || (filter === 'healthy' ? c.status === 'healthy' : c.status !== 'healthy')) && (c.name + c.city + c.country + c.id).toLowerCase().includes(search.toLowerCase()));
  if (!clusters.length) return '<div class="empty"><h2>No matching clusters</h2><p>Try a different cluster name or status filter.</p></div>';
  return clusters.map(c => `<article class="cluster-card" data-cluster="${c.id}"><div class="card-main"><div class="card-heading"><div class="cluster-title"><span class="cluster-icon" aria-hidden="true">⬡</span><div><h2>${e(c.name)}</h2><small>${e(c.city)} · ${e(c.country)} label</small></div></div>${badge(c.status)}</div><dl class="card-data"><div class="datum"><dt>Version</dt><dd>${e(c.version || 'Unknown')}</dd></div><div class="datum"><dt>Live nodes</dt><dd>${c.nodes.filter(n=>n.status==='live').length} <span class="muted">/ ${c.nodes.length || '—'}</span></dd></div><div class="datum"><dt>Database storage</dt><dd>${c.nodes.length ? bytes(total(c,'storage_used_bytes')) : '—'}</dd></div></dl></div><div class="card-foot"><span>◷ Single node · no failover</span><button class="text-button" data-route="${clusterRoute(c.id)}" aria-label="Manage ${e(c.name)}">Manage cluster →</button></div></article>`).join('');
}

function fleetPage() {
  const healthy = fleet.clusters.filter(c => c.status==='healthy').length;
  return heading('Database clusters', 'A clear view of your CockroachDB estate. Inspect nodes, verify recovery and track database operations.') +
    `<div class="stats">${stat('Registered clusters',fleet.clusters.length,'Independent CockroachDB instances')}${stat('Responding to SQL',fleet.clusters.filter(c=>c.sql).length,'Live database connections','positive')}${stat('Live database nodes',fleet.clusters.reduce((s,c)=>s+c.nodes.filter(n=>n.status==='live').length,0),'Observed through CockroachDB')}${stat('Single-node clusters',fleet.clusters.length,'No node or host failover','amber')}</div>` +
    `<div class="callout"><span class="callout-icon" aria-hidden="true">◇</span><div><strong>Four cluster locations. One development host.</strong><br>Country labels describe the lab’s intended placement. Physical location and regional resilience are not attested.</div><button class="text-button" data-route="page=environment">View environment →</button></div>` +
    `<div class="section-heading"><h2>Your clusters</h2><small>Checked ${e(date(fleet.observed_at))} · refreshes every 20 seconds</small></div><div class="fleet-toolbar"><div class="filters" aria-label="Filter clusters"><button class="chip ${filter==='all'?'active':''}" data-filter="all">All clusters ${fleet.clusters.length}</button><button class="chip ${filter==='healthy'?'active':''}" data-filter="healthy">Healthy ${healthy}</button><button class="chip ${filter==='attention'?'active':''}" data-filter="attention">Needs attention ${fleet.clusters.length-healthy}</button></div><input class="search" id="cluster-search" aria-label="Search clusters" placeholder="Search by name or country…" value="${e(search)}"></div><div class="cluster-grid" id="cluster-grid">${fleetCards()}</div>` +
    `<div class="support-grid"><section class="panel"><h2>Make your first recovery check</h2><p>Open a cluster and run a recovery rehearsal. CockroachDB backs up synthetic canary data, restores it into a temporary database and compares every row.</p><button class="text-button" data-route="${clusterRoute('sg','recovery')}">Start with Singapore →</button></section><section class="panel"><h2>Database control, with a clear boundary</h2><p>Cluster health and recovery live here. The environment view covers supporting services. Business interactions and sovereign data placement remain in their own services.</p><a class="text-button" href="/monitor.html">Open movement monitor →</a></section></div>`;
}

function nodeTable(c) {
  if (!c.nodes.length) return '<div class="empty"><h2>Node visibility unavailable</h2><p>Refresh once the cluster’s SQL and node status endpoints are reachable. No cached health is substituted.</p></div>';
  return `<div class="table-wrap"><table><thead><tr><th>Node</th><th>Status</th><th>Locality</th><th>Version</th><th>Ranges</th><th>CPU</th><th>Memory</th><th>Disk available</th></tr></thead><tbody>${c.nodes.map(n=>`<tr><td class="node-id">Node ${n.id}</td><td>${badge(n.status==='live'?'healthy':'attention')}</td><td><span class="pill">country=${e(n.locality.country || 'unset')}</span></td><td>${e(n.version)}</td><td>${n.ranges} <span class="muted">/ ${n.unavailable_ranges} unavailable</span></td><td>${n.cpu_percent}%</td><td>${bytes(n.memory_bytes)}</td><td>${bytes(n.disk_available_bytes)}</td></tr>`).join('')}</tbody></table></div><p class="node-footnote">Node metrics are point-in-time observations. Disk availability is shared with this development host’s other containers. Country labels do not prove physical residency.</p>`;
}

function jobsMarkup(jobs, available=true) {
  if (!available) return '<div class="empty"><h2>Operation journal unavailable</h2><p>This cluster’s SQL journal could not be read. Previously completed operations have not been replaced with an empty success state.</p></div>';
  if (!jobs.length) return '<div class="empty"><h2>No operations yet</h2><p>Run a health check or recovery rehearsal. Its progress and result will be recorded in the selected cluster.</p></div>';
  return jobs.map(j=>`<article class="operation-card ${j.id===selectedJob?'selected':''}" data-job="${e(j.id)}"><div class="operation-heading"><div><h3>${e(kinds[j.kind])}</h3><small>${e(j.cluster.toUpperCase())} · ${e(date(j.created_at))} · Development operator · <span class="mono">${e(j.id.slice(0,8))}</span></small></div>${badge(j.state)}</div><ol class="steps">${j.steps.map((s,i)=>`<li class="${e(s.state)}"><span class="step-icon" aria-hidden="true">${s.state==='succeeded'?'✓':s.state==='failed'?'!':i+1}</span><span>${e(s.label)}<span class="sr-only">: ${e(s.state)}</span></span></li>`).join('')}</ol>${j.result.summary?`<p class="job-result">${e(j.result.summary)}</p>`:''}${j.error_code?`<p class="error-text">${j.error_code==='insufficient_disk_headroom'?'Recovery stopped before creating data: free at least 8% node disk (minimum 512 MiB), then retry.':j.state==='interrupted'?'This recovery was interrupted or its outcome is uncertain. Inspect native database jobs and retained canary artifacts before another rehearsal.':'The operation could not complete. Inspect this cluster before retrying; failed canary artifacts are retained.'}</p>`:''}</article>`).join('');
}

function clusterPage(c) {
  const history = histories[c.id] || {available:false,jobs:[]};
  const latest = history.latest_recovery;
  const recoveryKnown = history.available;
  let content = '';
  if (route.tab === 'nodes') content = nodeTable(c);
  else if (route.tab === 'recovery') content = `<section class="panel recovery-hero"><span class="scope-tag">WORKING SYNTHETIC RECOVERY</span><h2>Prove that backup and restore work.</h2><p>Run native CockroachDB BACKUP and RESTORE on three generated canary rows. Compare the restored contents, then remove the temporary databases. The backup remains on this cluster’s local volume.</p><button class="button primary" data-recovery="${c.id}" ${!c.recovery_ready?'disabled':''}>Run recovery rehearsal</button>${!c.recovery_ready?'<p class="error-text">Recovery needs a healthy cluster and at least 8% free node disk (minimum 512 MiB). Refresh after restoring capacity.</p>':''}</section><div class="stats">${stat('Last successful rehearsal',!recoveryKnown?'Unavailable':latest?'Verified':'Not run',!recoveryKnown?'Journal could not be read':latest?date(latest.updated_at):'Run your first rehearsal',latest?'positive':'')}${stat('Restored canary rows',latest?latest.result.verified_rows:'—','Exact contents compared')}${stat('Business-data backup','Not set','Canary rehearsal covers synthetic data only','amber')}${stat('Off-host recovery','Not set','Backup remains on the same host','amber')}</div><div class="section-heading"><h2>Recovery activity</h2></div><div id="job-list">${jobsMarkup(history.jobs.filter(j=>j.kind==='recovery_rehearsal'),history.available)}</div>`;
  else if (route.tab === 'activity') content = `<div class="section-heading"><h2>Cluster operation history</h2><small>Durable journal in this cluster · latest 30 operations</small></div><div id="job-list">${jobsMarkup(history.jobs,history.available)}</div>`;
  else content = `<div class="stats">${stat('Live nodes',c.nodes.filter(n=>n.status==='live').length,'Single-node development topology')}${stat('SQL connection check',c.sql?`${c.sql_latency_ms}<span> ms</span>`:'Unavailable','Includes identity and database inventory',c.sql?'positive':'amber')}${stat('Unavailable ranges',c.nodes.length?total(c,'unavailable_ranges'):'—','Observed from node status')}${stat('Database storage',c.nodes.length?bytes(total(c,'storage_used_bytes')):'—','Physical store bytes')}</div><div class="detail-grid"><section class="panel"><h2>Cluster configuration</h2>${definition([['Database engine','CockroachDB'],['Binary version',e(c.version || 'Unavailable')],['Cluster version',e(c.cluster_version || 'Unavailable')],['Country locality',e(c.country)+' <span class="pill">'+(c.locality_matches?'Matches node labels':'Unverified')+'</span>'],['Cluster identifier','<span class="mono">'+e(c.cluster_id || 'Unavailable')+'</span>'],['Node-failure tolerance','0 nodes · no failover']])}</section><section class="panel"><h2>Databases</h2><p>Metadata only. Customer tables and records are not queried by this console.</p>${c.databases.map(d=>`<div class="database-row"><span>${e(d.name)}</span><small>${e(d.kind)}</small></div>`).join('') || '<p>Database inventory unavailable.</p>'}</section></div><div class="support-grid"><section class="panel"><h2>Safe lifecycle controls</h2><p>Health checks and synthetic recovery run against this cluster. Scaling, node removal and rolling upgrades require a separately validated multi-node deployment adapter.</p><button class="button secondary small" disabled>Scale cluster · needs multi-node target</button></section><section class="panel"><h2>Recovery readiness</h2><p>${!recoveryKnown?'Recovery history is unavailable.':latest?'A native backup and restore rehearsal has passed.':'No successful recovery rehearsal has been recorded.'} Business-data backups and off-host recovery still need configuration.</p><button class="text-button" data-route="${clusterRoute(c.id,'recovery')}">Review recovery →</button></section></div>`;
  return `<button class="back-button" data-route="page=fleet">← All clusters</button>` +
    `<div class="page-heading"><div class="cluster-hero"><span class="cluster-icon" aria-hidden="true">⬡</span><div><h1>${e(c.name)} ${badge(c.status)}</h1><p>${e(c.city)} · country=${e(c.country)} · Independent CockroachDB cluster</p></div></div><div class="heading-actions"><button class="button secondary" data-refresh>↻ Refresh</button><button class="button primary" data-check="${c.id}" ${!c.sql?'disabled':''}>Run health check</button></div></div>` +
    `<div class="tabs" role="navigation" aria-label="Cluster details">${[['overview','Overview'],['nodes','Nodes'],['recovery','Recovery'],['activity','Activity']].map(([id,label])=>`<button class="tab ${route.tab===id?'active':''}" data-route="${clusterRoute(c.id,id)}" ${route.tab===id?'aria-current="page"':''}>${label}</button>`).join('')}</div>` + content;
}

function operationsPage() {
  const jobs = Object.values(histories).flatMap(h=>h.jobs).sort((a,b)=>b.created_at-a.created_at);
  const unavailable = Object.entries(histories).filter(([,h])=>!h.available).map(([key])=>key.toUpperCase());
  return heading('Operation history', 'Database checks and recovery rehearsals, recorded in each cluster. Environment lifecycle operations are managed separately.') +
    (unavailable.length?`<div class="callout warning">Operation journals unavailable: ${e(unavailable.join(', '))}. The available history below is incomplete.</div>`:'') + jobsMarkup(jobs);
}

function environmentPage() {
  if (!environment) return heading('Environment', 'Reading supporting service health…','PLATFORM CONTEXT');
  if (environment.unavailable) return heading('Environment', 'Supporting service checks are unavailable. Cluster observations are managed separately.','PLATFORM CONTEXT') + '<div class="callout warning" role="alert">Environment probes could not be read. Refresh to try again.</div>';
  return heading('Environment', 'The infrastructure and supporting services around your databases. Database clusters have their own operational view.','PLATFORM CONTEXT') +
    `<div class="callout info"><span class="callout-icon" aria-hidden="true">◇</span><div><strong>You are viewing the environment.</strong><br>This view describes where the lab runs and which supporting services respond. Cluster health and recovery are managed under Clusters.</div></div>` +
    `<div class="environment-layout"><section class="panel"><h2>Federation development lab</h2>${definition([['Deployment','Docker Compose'],['Physical hosts','1 shared development host'],['Registered database clusters','4 independent clusters'],['Gateway exposure','Loopback only · ports 8080 / 8081'],['Physical country placement','Not attested'],['Workload','Synthetic data']])}<p style="margin-top:18px">SG, UK, US and India are country labels on separate database instances. All instances currently run on this same host.</p><button class="text-button" data-route="page=fleet">Manage database clusters →</button></section><section class="panel"><h2>Supporting service checks</h2><p>Direct HTTP health probes. These are service observations, not Docker daemon or host-liveness checks.</p>${environment.services.map(s=>`<div class="service-line"><span>${e(s.name)}</span>${badge(s.status)}</div>`).join('')}<a class="text-button" href="/grafana/d/sovereign-logs">Open application log dashboard →</a></section></div><div class="support-grid"><section class="panel"><h2>Business and sovereign services</h2><p>Business APIs own interactions and transactions. Sovereign peers enforce relationship-scoped sharing and trusted placement. The cluster console manages database operations beneath those services.</p><a class="text-button" href="/monitor.html">Open federation monitor →</a></section><section class="panel"><h2>Before a regional deployment</h2><p>Regional credentials and SQL TLS, independent failure domains, identity integration, supported lifecycle adapters and external backups remain implementation work. This lab does not establish production HA or physical residency.</p><a class="text-button" href="/guides/docs/CLUSTER_CONTROL.md">Read the implementation boundary →</a></section></div>`;
}

function render() {
  route = readRoute();
  document.querySelectorAll('.nav-item[data-route]').forEach(el => {
    const current = el.dataset.route === (route.cluster ? 'fleet' : route.page);
    el.classList.toggle('active',current);
    if(current) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current');
  });
  $('#breadcrumb').textContent = route.page==='environment'?'Environment':'Database operations';
  if (!fleet) return;
  const cluster = fleet.clusters.find(c=>c.id===route.cluster);
  main.innerHTML = route.cluster ? (cluster ? clusterPage(cluster) : heading('Cluster not registered','Select one of the registered clusters from the fleet.')) : route.page==='environment' ? environmentPage() : route.page==='operations' ? operationsPage() : fleetPage();
  document.title = `${cluster?cluster.name:route.page==='environment'?'Environment':route.page==='operations'?'Operations':'Database clusters'} · Cluster Control`;
}

async function refresh({quiet=false}={}) {
  if(refreshing) return;
  refreshing = true;
  try {
    const fresh = await api('clusters');
    if(fresh.mode!=='live' || !Array.isArray(fresh.clusters)) throw new Error('Live cluster inventory unavailable');
    fleet=fresh;
    await Promise.all(fleet.clusters.map(async c=>{try{histories[c.id]=await api(`clusters/${c.id}/operations`);}catch{histories[c.id]={available:false,jobs:[]};}}));
    if(readRoute().page==='environment') { try { environment=await api('environment'); } catch { environment={services:[], unavailable:true}; } }
    $('#mode').textContent='LIVE · COCKROACHDB'; $('#mode').classList.remove('failed');
    render();
    if(!quiet) $('#announcement').textContent='Live cluster status refreshed.';
  } catch(error) {
    fleet=null;
    $('#mode').textContent='API UNAVAILABLE'; $('#mode').classList.add('failed');
    main.innerHTML=heading('Live cluster status unavailable','The control API could not be reached. Check the lab connection and try again.')+`<div class="callout warning"><strong>${e(error.message)}</strong><p>This view requires the running CockroachDB container lab. It does not substitute simulated cluster data.</p></div>`;
  } finally {refreshing=false;}
}

async function run(key, kind) {
  const id = requestId || crypto.randomUUID(); requestId=id;
  const result=await api(`clusters/${key}/operations`,{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Control':'1'},body:JSON.stringify({kind,request_id:id,confirmation:kind==='recovery_rehearsal'?key:''})});
  selectedJob=result.id; requestId='';
  navigate(clusterRoute(key,'activity'));
  await refresh({quiet:true});
  $('#announcement').textContent='Operation accepted. Progress is recorded in the selected cluster.';
  main.focus();
}

document.addEventListener('click', async event=> {
  const target=event.target.closest('[data-route],[data-refresh],[data-filter],[data-check],[data-recovery]');
  if(!target) return;
  if(target.dataset.route){navigate(target.dataset.route.includes('=')?target.dataset.route:'page='+target.dataset.route);return;}
  if(target.hasAttribute('data-refresh')){target.disabled=true;await refresh();return;}
  if(target.dataset.filter){filter=target.dataset.filter;render();return;}
  if(target.dataset.recovery){actionCluster=target.dataset.recovery;requestId=crypto.randomUUID();$('#dialog-cluster').textContent=fleet.clusters.find(c=>c.id===actionCluster).name;$('#confirm-label').textContent=actionCluster.toUpperCase();$('#confirm-cluster').value='';$('#dialog-error').textContent='';$('#operation-dialog').showModal();return;}
  if(target.dataset.check){target.disabled=true;try{requestId=crypto.randomUUID();await run(target.dataset.check,'health_check');}catch(error){$('#announcement').textContent=error.message;main.insertAdjacentHTML('afterbegin',`<div class="callout warning" role="alert">${e(error.message)}</div>`);target.disabled=false;}}
});
document.addEventListener('input',event=>{if(event.target.id==='cluster-search'){search=event.target.value;$('#cluster-grid').innerHTML=fleetCards();}});
$('#close-dialog').onclick=$('#cancel-dialog').onclick=()=>$('#operation-dialog').close();
$('#operation-form').addEventListener('submit',async event=>{
  event.preventDefault();
  if($('#confirm-cluster').value.trim().toLowerCase()!==actionCluster){$('#dialog-error').textContent='Enter '+actionCluster.toUpperCase()+' to confirm this cluster.';return;}
  $('#confirm-operation').disabled=true;
  try{await run(actionCluster,'recovery_rehearsal');$('#operation-dialog').close();}catch(error){$('#dialog-error').textContent=error.message;}finally{$('#confirm-operation').disabled=false;}
});
window.addEventListener('hashchange',async()=>{render();if(readRoute().page==='environment'){environment=null;render();try{environment=await api('environment');render();}catch{environment={services:[],unavailable:true};render();}}});
await refresh();
setInterval(()=>{if(!document.hidden && !$('#operation-dialog').open && !document.activeElement?.matches('input'))refresh({quiet:true});},20000);
setInterval(async()=>{
  if(document.hidden || $('#operation-dialog').open || refreshing || !fleet) return;
  const key=readRoute().cluster;
  if(!key || !histories[key]?.jobs.some(j=>['queued','running'].includes(j.state)))return;
  try{const history=await api(`clusters/${key}/operations`);histories[key]=history;const current=readRoute();if(current.cluster!==key)return;const list=$('#job-list');if(list)list.innerHTML=jobsMarkup(current.tab==='recovery'?history.jobs.filter(j=>j.kind==='recovery_rehearsal'):history.jobs,history.available);}catch{}
},1000);
