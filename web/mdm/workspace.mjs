import {readDeployment,showRuntime} from '/runtime-status.mjs';

const el=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state={mode:'checking',session:null,runtime:null,directory:[],next:null,source:null,profile:null,selectedScope:null,tab:'overview',activity:[],last:null,busy:false};
const profileEmpty=el('profile-content').innerHTML;
let epoch=0,sessionAbort=new AbortController(),directorySerial=0,profileSerial=0,runtimeSerial=0,preview=null,searchTimer;
class SessionChanged extends Error {}
class ApiError extends Error {constructor(status,message){super(message);this.status=status;}}
const can=action=>state.mode==='live'&&state.session?.context?.actions.includes(action);
const canCommand=command=>can('command')&&Array.isArray(state.session.context.command_grants?.[command])&&state.session.context.command_grants[command].includes(command==='update_contact'?'contact_info.value':'consent.status');
const rows=view=>view?.rows||[];
const allViews=()=>state.profile?.views||[];
const relationships=()=>allViews().filter(v=>v.scope_kind==='relationship');
const initials=name=>name.replace(/^Synthetic /,'').split(/\s+/).slice(0,2).map(s=>s[0]).join('').toUpperCase()||'ID';
const label=value=>String(value??'').replaceAll('_',' ').toLowerCase().replace(/^\w/,s=>s.toUpperCase());
const country=id=>({'LE-SG-01':'Singapore','LE-GB-02':'United Kingdom','LE-US-01':'United States'}[id]||id);
const shortStore=id=>({'STORE-SG-01':'Singapore','STORE-GB-01':'United Kingdom','STORE-US-01':'United States'}[id]||id||'Not returned');
function toast(message){el('toast').textContent=message;el('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>el('toast').hidden=true,5500);}
function openDialog(id){const dialog=el(id);if(!dialog.open)dialog.showModal();}
function closeDialogs(){for(const d of document.querySelectorAll('dialog[open]'))d.close();}
function controls(){
  el('new-customer').disabled=!can('system')||state.busy;
  el('search').disabled=!(can('system')||state.mode==='preview');
  el('customer').disabled=!(can('read')||state.mode==='preview')||state.busy;
  el('view').disabled=!can('read')||state.busy;
  el('upsert').disabled=el('relationship').disabled=!can('system')||state.busy;
  el('contact').disabled=!canCommand('update_contact')||state.busy;
  el('retry').disabled=!state.last||state.last.epoch!==epoch||state.busy;
  el('connect').disabled=state.mode!=='live'||state.busy;
  el('identity-switch').disabled=state.mode!=='live';
  el('refresh').disabled=state.mode==='checking'||state.busy;
  document.querySelector('.session-dot').classList.toggle('connected',!!state.session?.context);
  el('session-label').textContent=state.mode==='preview'?'Read-only preview':state.session?.context?country(state.session.context.entity_id)+' · '+(can('system')?'System API':'Experience API'):'Connect an identity';
}
function clearProtectedData(){
  profileSerial++;directorySerial++;
  state.source=null;state.profile=null;state.selectedScope=null;state.directory=[];state.next=null;
  el('profile-content').innerHTML=profileEmpty;
  el('name').value='Synthetic Pilot Customer';el('email').value='pilot@example.invalid';el('command-value').value='';
  el('reference').value='';el('customer-version').value='0';
  el('result').textContent='No response received.';renderDirectory();renderMetrics();
}
function disconnect(message='Not connected'){
  epoch++;runtimeSerial++;sessionAbort.abort();sessionAbort=new AbortController();
  state.session=null;state.runtime=null;state.activity=[];state.last=null;clearProtectedData();
  clearTimeout(searchTimer);el('party-type').value='PERSON';el('profile').value='owner_only';el('search').value='';el('party').value='';el('scope').value='';el('scope-version').value='1';el('minimum').value='0';
  el('token').value='';el('identity').textContent=message;el('outcome').textContent='No request in this identity session';
  renderActivity();controls();
  if(state.mode==='live')showRuntime(el('runtime-status'),'checking','LIVE PILOT · identity not connected','This gateway is configured for real services. Connect an identity to verify CockroachDB, OPA and recipient peers.');
}
function evidence(entry,data){
  state.activity.unshift(entry);state.activity=state.activity.slice(0,25);
  el('outcome').textContent='HTTP '+entry.status+' · '+entry.name+' · Trace '+(entry.trace||'unavailable');
  el('result').textContent=JSON.stringify(data,null,2);renderActivity();renderMetrics();
}
async function api(path,method='GET',body,options={}){
  const session=state.session,currentEpoch=epoch;
  if(!session)throw new ApiError(401,'Connect a pilot identity first.');
  const started=performance.now();
  if(options.remember)state.last={path,method,body:body===undefined?undefined:structuredClone(body),name:options.name,epoch:currentEpoch};
  let response,data;
  try{
    response=await fetch(path,{method,cache:'no-store',headers:{Authorization:'Bearer '+session.token,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.any([sessionAbort.signal,AbortSignal.timeout(25000)])});
    try{data=await response.json();}catch{throw new ApiError(503,'The live service did not return a valid API response.');}
    if(response.ok&&!/^[0-9a-f]{32}$/.test(response.headers.get('X-Trace-ID')||''))throw new ApiError(503,'The live API receipt could not be verified.');
  }catch(error){
    if(currentEpoch!==epoch||session!==state.session)throw new SessionChanged();
    state.runtime=null;runtimeSerial++;clearProtectedData();controls();
    showRuntime(el('runtime-status'),'offline','LIVE PILOT · connection unavailable','The request was not verified. No browser-demo fallback. A write may have committed: retry its unchanged request ID.');
    if(options.track!==false)evidence({name:options.name||'API request',method,status:'—',trace:null,ms:Math.round(performance.now()-started)}, {detail:'Service unavailable. No simulated fallback.'});
    throw new ApiError(503,'Required pilot service unavailable. Retry the same request if its outcome is uncertain.');
  }
  if(currentEpoch!==epoch||session!==state.session)throw new SessionChanged();
  if(options.track!==false)evidence({name:options.name||'API request',method,status:response.status,trace:response.headers.get('X-Trace-ID'),ms:Math.round(performance.now()-started)},data);
  if(response.status===401){disconnect('Credential rejected or expired. Connect again.');throw new ApiError(401,'Credential rejected or expired.');}
  if(!response.ok&&!options.accept?.includes(response.status)){
    if([403,404,503].includes(response.status)){clearProtectedData();el('result').textContent=JSON.stringify(data,null,2);}
    if(response.status===503){state.runtime=null;runtimeSerial++;showRuntime(el('runtime-status'),'offline','LIVE PILOT · dependency unavailable','A required service could not complete this request. No simulated data was substituted.');}
    throw new ApiError(response.status,typeof data.detail==='string'?data.detail:'The request could not be completed.');
  }
  return {data,response};
}
async function run(operation){
  if(state.busy)return;
  state.busy=true;controls();
  try{await operation();}
  catch(error){if(!(error instanceof SessionChanged)){toast(error.status===409?'The record changed or is not yet current. Refresh, review its version and try again.':error.message||'The operation could not be completed.');if(el('identity-dialog').open)el('identity').textContent=error.message;}}
  finally{state.busy=false;controls();}
}
async function probe(){
  if(!state.session?.context)return;
  const serial=++runtimeSerial;
  const {data}=await api('/pilot/api/v1/runtime','GET',undefined,{track:false,accept:[503]});
  if(serial!==runtimeSerial)return;
  const expected=data.footprint==='mdm-compact'?['SG','UK']:data.footprint==='full'?['SG','UK','US','IN']:null;
  const valid=expected&&data.mode==='live'&&data.database==='cockroach'&&JSON.stringify(data.active_regions)===JSON.stringify(expected)&&Array.isArray(data.components)&&data.components.length===(expected.length===2?6:11)&&data.components.every(c=>typeof c.id==='string'&&typeof c.label==='string'&&['ready','unavailable'].includes(c.state))&&['ready','not-ready'].includes(data.status)&&(data.status==='ready')===data.components.every(c=>c.state==='ready');
  if(!valid){state.runtime=null;clearProtectedData();showRuntime(el('runtime-status'),'offline','LIVE PILOT · connection not verified','The API returned incomplete dependency evidence. No sample data or connected status has been substituted.');throw new ApiError(503,'Live dependency evidence unavailable.');}
  state.runtime={...data,checked:new Date()};
  const compact=data.footprint==='mdm-compact',ready=data.status==='ready';
  showRuntime(el('runtime-status'),ready?'live':'offline',ready?(compact?'LIVE PILOT · SG + UK connected':'LIVE PILOT · full footprint connected'):'LIVE PILOT · a dependency is unavailable',
    ready?(compact?'Real CockroachDB, OPA and authenticated APIs. US, India, migration and telemetry are suspended.':'Real CockroachDB, OPA and authenticated peers checked. Synthetic data on one host; not production.'):
    'Check connection details. Individual requests still enforce policy and fail closed; a browser demo is never substituted.');
  if(!ready){clearProtectedData();controls();}
  renderConnection();renderMetrics();
}
async function connect(){
  if(state.mode!=='live')return;
  const token=el('token').value.trim();if(!token)return;
  disconnect();state.session={token,context:null};
  const {data}=await api('/pilot/api/v1/context','GET',undefined,{name:'Verify identity'});
  if(!Array.isArray(data.actions)||typeof data.entity_id!=='string'||typeof data.processing_country!=='string'){disconnect('The identity response could not be verified.');throw new ApiError(503,'Identity evidence unavailable.');}
  state.session.context=data;el('token').value='';
  el('identity').textContent=data.entity_id+' · Processing '+data.processing_country;
  closeDialogs();controls();renderMetrics();
  await probe();
  if(can('system'))await loadDirectory();
  else renderDirectory();
}
async function loadDirectory(after=''){
  if(state.mode==='preview'){renderDirectory();return;}
  if(!can('system'))return;
  const serial=++directorySerial,query=el('search').value.trim();
  const {data}=await api('/pilot/system/v1/customers?q='+encodeURIComponent(query)+'&after='+encodeURIComponent(after)+'&limit=25','GET',undefined,{name:'Read source directory'});
  if(serial!==directorySerial)return;
  state.directory=data.items;state.next=data.next_cursor;renderDirectory();renderMetrics();
}
function renderDirectory(){
  let items=state.directory;
  if(state.mode==='preview')items=preview.previewCustomers.filter(c=>(c.display_name+' '+c.external_reference).toLowerCase().includes(el('search').value.toLowerCase()));
  const authorised=can('system')||state.mode==='preview';
  el('directory-count').textContent=authorised?items.length:'—';el('nav-count').textContent=authorised?items.length:'—';
  el('directory-caption').textContent=state.mode==='preview'?'Read-only browser fixtures · not backend records':can('system')?'CockroachDB · your source system only':'Experience access · permitted customer lookup';
  el('directory').innerHTML=authorised?(items.length?items.map(c=>'<button class="customer-row '+(state.profile?.global_party_id===c.global_party_id?'selected':'')+'" data-customer="'+esc(c.global_party_id)+'"><span class="customer-avatar">'+esc(initials(c.display_name))+'</span><span class="customer-row-text"><strong>'+esc(c.display_name)+'</strong><small>'+esc(c.external_reference)+'</small></span><span class="row-type">'+(c.party_type==='ORGANISATION'?'ORG':'PERSON')+'</span></button>').join(''):'<div class="empty-state compact"><span class="empty-symbol" aria-hidden="true">⌕</span><h3>No matching source records</h3><p>Try another search or create a synthetic customer.</p></div>'):
    '<div class="empty-state compact"><span class="empty-symbol" aria-hidden="true">◎</span><h3>'+(state.session?.context?'Look up an approved view':'Connect to your customer data')+'</h3><p>'+(state.session?.context?'This identity cannot browse the owner’s source directory. Use a global customer ID below.':'Connect a Singapore system identity to load real records, or an experience identity to read a permitted view.')+'</p>'+(!state.session?.context?'<button class="button secondary" id="directory-connect">Connect an identity</button>':'')+'</div>';
  el('page-note').textContent=state.mode==='preview'?items.length+' sample profiles · read only':authorised?'Showing '+items.length+' records on this page':'No owner directory disclosed';
  el('next-page').hidden=!state.next||state.mode==='preview';
  for(const button of document.querySelectorAll('[data-customer]'))button.onclick=()=>run(async()=>{
    const gid=button.dataset.customer;el('party').value=gid;
    if(state.mode==='preview'){const profile=preview.previewCustomer(gid);state.source=profile.source;state.profile=profile.view;state.selectedScope=relationships()[0]?.scope_id;renderProfile();renderDirectory();renderMetrics();return;}
    const item=state.directory.find(c=>c.global_party_id===gid);await selectOwner(item);
  });
  if(el('directory-connect'))el('directory-connect').onclick=()=>openDialog('identity-dialog');
}
function renderMetrics(){
  const previewing=state.mode==='preview',context=state.session?.context,view=allViews()[0];
  el('metric-records').textContent=previewing?preview.previewCustomers.length+' sample profiles':can('system')?state.directory.length+' records':'—';
  el('metric-records-note').textContent=previewing?'Static fixtures · no database connection':can('system')?'On this page, from your source system':'Owner directory is not available to this identity';
  el('metric-perspective').textContent=previewing?'Sample owner view':context?country(context.entity_id):'Not connected';
  el('metric-perspective-note').textContent=previewing?'Illustrative preview, not an authenticated role':context?context.entity_id+' · Processing '+context.processing_country:'Connect a registered test identity';
  el('metric-source').textContent=previewing?'Browser fixtures':view?(view.served_from==='owner'?'Owner · '+shortStore(view.store_id):'Projection · '+shortStore(view.store_id)):state.runtime?.status==='ready'?'Live services verified':'Not verified';
  el('metric-source-note').textContent=previewing?'Read-only sample data':view?'Actual returned data version '+view.data_version:state.runtime?.checked?'Checked '+state.runtime.checked.toLocaleTimeString():'No backend view received';
  el('metric-requests').textContent=state.activity.length+' requests';
}
function attributes(entries){return '<dl class="attribute-grid">'+entries.filter(([,v])=>v!==undefined&&v!==null).map(([k,v])=>'<div class="attribute"><dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl>';}
function renderProfile(){
  if(!state.profile){el('profile-content').innerHTML=profileEmpty;return;}
  const views=allViews(),parties=views.flatMap(v=>rows(v).filter(r=>r.table==='party').map(r=>r.row));
  const party=parties.find(p=>p.display_name)||parties[0]||{},name=state.source?.display_name||party.display_name||'Restricted customer identity';
  const kind=state.source?.party_type||party.party_type||'Customer',previewing=state.mode==='preview';
  const gid=state.profile.global_party_id||el('party').value,owner=views[0]?.owner_entity_id,version=views[0]?.data_version;
  if(!state.selectedScope&&relationships().length)state.selectedScope=relationships()[0].scope_id;
  const header='<div class="profile-header"><div class="profile-main"><span class="profile-avatar">'+esc(initials(name))+'</span><div class="profile-name"><h2>'+esc(name)+'</h2><div class="profile-subtitle"><span class="pill neutral">'+esc(label(kind))+'</span><span>'+esc(state.source?.external_reference||'Approved identity fields only')+'</span></div></div><span class="pill '+(previewing?'warning':'')+'">'+(previewing?'PREVIEW FIXTURE':'API VERIFIED VIEW')+'</span></div><div class="profile-meta"><span>Global customer ID <code>'+esc(gid)+'</code></span><span>Owner '+esc(owner||'Not returned')+'</span><button class="text-button copy-customer-id" id="copy-customer-id">Copy customer ID</button></div></div>';
  const tabs='<div class="profile-tabs" role="tablist" aria-label="Customer details">'+[['overview','Overview'],['relationships','Relationships'],['attributes','Attributes'],['activity','Session activity']].map(([id,text])=>'<button role="tab" id="profile-tab-'+id+'" aria-controls="profile-tab-panel" tabindex="'+(state.tab===id?'0':'-1')+'" aria-selected="'+(state.tab===id)+'" data-tab="'+id+'">'+text+'</button>').join('')+'</div>';
  let content='';
  if(state.tab==='overview'){
    const contact=views.flatMap(v=>rows(v)).find(r=>r.table==='contact_info')?.row;
    content='<div class="profile-section-heading"><h3>Identity & provenance</h3><span>Only returned fields are shown</span></div>'+attributes([['Display name',state.source?.display_name||party.display_name],['Customer type',label(kind)],['Authoritative entity',owner],['Serving location',shortStore(views[0]?.store_id)],['Source system',state.source?.source_system],['Source reference',state.source?.external_reference],['Contact email',contact?.value],['Returned business version',version]])+
      '<div class="source-callout"><span aria-hidden="true">◇</span><div><strong>'+(previewing?'A read-only illustration':'A relationship is its own sharing boundary')+'</strong><p>'+(previewing?'These profiles come from shipped synthetic browser fixtures. No service, database, entitlement or policy check was performed.':'Minimal identity and relationship information follow independent policies. This profile is assembled only from views approved for your current identity.')+'</p></div></div>';
  }else if(state.tab==='relationships'){
    content='<div class="profile-section-heading"><h3>Approved relationships</h3><span>Current identity’s returned views</span></div>'+
      (relationships().length?relationships().map(v=>{
        const rel=rows(v).find(r=>r.table==='relationship')?.row||{},contact=rows(v).find(r=>r.table==='contact_info')?.row,consent=rows(v).find(r=>r.table==='consent')?.row;
        return '<article class="relationship-card"><div class="relationship-top"><h3>'+esc(label(rel.relationship_type||'Banking relationship'))+'</h3><span class="pill">'+esc(rel.status||'Approved view')+'</span></div><div class="relationship-detail"><span>'+esc(shortStore(v.store_id))+'</span><span>'+esc(label(v.served_from))+'</span><span>Version '+esc(v.data_version)+'</span></div>'+(contact?'<div class="relationship-contact">'+esc(contact.channel)+' · '+esc(contact.value)+'</div>':'')+(consent?'<div class="relationship-contact">Email consent · <b>'+esc(label(consent.status))+'</b></div>':'')+
          '<div class="relationship-actions"><button class="text-button" data-open-scope="'+esc(v.scope_id)+'">Refresh relationship</button>'+(!previewing&&can('command')?(canCommand('update_contact')?'<button class="text-button" data-contact="'+esc(v.scope_id)+'">Edit contact</button>':'')+(canCommand('withdraw_consent')?'<button class="text-button" data-consent="'+esc(v.scope_id)+'" data-command="withdraw_consent">Withdraw consent</button>':'')+(canCommand('restore_consent')?'<button class="text-button" data-consent="'+esc(v.scope_id)+'" data-command="restore_consent">Restore consent</button>':''):'')+'</div></article>';
      }).join(''):'<div class="empty-state"><span class="empty-symbol">◇</span><h3>No relationship views returned</h3><p>This is the response for your current identity. The workspace does not disclose withheld relationships or their count.</p></div>');
  }else if(state.tab==='attributes'){
    content='<div class="profile-section-heading"><h3>Returned attributes</h3><span>Grouped by approved scope and dataset</span></div>'+views.map(v=>'<article class="relationship-card"><h3>'+esc(label(v.scope_kind))+' · '+esc(label(v.served_from))+' · v'+esc(v.data_version)+'</h3>'+rows(v).map(r=>'<p class="muted" style="margin:14px 0 7px">'+esc(label(r.table))+'</p>'+attributes(Object.entries(r.row).map(([k,value])=>[label(k),typeof value==='object'?JSON.stringify(value):value]))).join('')+'</article>').join('');
  }else content='<div class="profile-section-heading"><h3>Requests in this identity session</h3><span>Not the durable business audit</span></div>'+activityMarkup();
  const actions=can('system')&&state.source?'<button class="button primary" id="add-relationship">＋ Add relationship</button>':'';
  el('profile-content').innerHTML=header+tabs+'<div class="profile-body" id="profile-tab-panel" role="tabpanel" aria-labelledby="profile-tab-'+state.tab+'">'+content+'</div><div class="profile-footer"><span>'+(previewing?'Sample fixture · no backend writes':esc(views[0]?.served_from==='owner'?'Current approved owner view':'Approved local projection')+' · independent scope versions')+'</span>'+actions+'</div>';
  el('copy-customer-id').onclick=async()=>{try{await navigator.clipboard.writeText(gid);toast('Customer ID copied. Switch identity, then paste it into the customer lookup.');}catch{toast('Select and copy the global customer ID shown above.');}};
  for(const tab of document.querySelectorAll('[data-tab]')){
    const activate=name=>{state.tab=name;renderProfile();el('profile-tab-'+name).focus({preventScroll:true});};
    tab.onclick=()=>activate(tab.dataset.tab);
    tab.onkeydown=event=>{const names=['overview','relationships','attributes','activity'];const index=names.indexOf(tab.dataset.tab);const key=event.key;if(!['ArrowLeft','ArrowRight','Home','End'].includes(key))return;event.preventDefault();activate(names[key==='Home'?0:key==='End'?3:(index+(key==='ArrowRight'?1:3))%4]);};
  }
  for(const button of document.querySelectorAll('[data-open-scope]'))button.onclick=()=>run(async()=>{if(previewing)return;selectScope(button.dataset.openScope);await loadRelationship();});
  for(const button of document.querySelectorAll('[data-contact]'))button.onclick=()=>{selectScope(button.dataset.contact);const v=relationships().find(v=>v.scope_id===state.selectedScope);el('command-value').value=rows(v).find(r=>r.table==='contact_info')?.row.value||'';openDialog('contact-dialog');};
  for(const button of document.querySelectorAll('[data-consent]'))button.onclick=()=>run(async()=>{selectScope(button.dataset.consent);await command(button.dataset.command);});
  if(el('add-relationship'))el('add-relationship').onclick=()=>{el('sharing').value='owner_only';openDialog('relationship-dialog');};
}
function selectScope(sid){state.selectedScope=sid;el('scope').value=sid;const view=relationships().find(v=>v.scope_id===sid);if(view)el('scope-version').value=view.data_version;}
async function selectOwner(item){
  const serial=++profileSerial;state.profile=null;state.source=null;renderProfile();
  const {data}=await api('/pilot/system/v1/customers/'+encodeURIComponent(item.external_reference),'GET',undefined,{name:'Read source customer'});
  if(serial!==profileSerial)return;
  await loadCustomer(item.global_party_id,data,serial);
}
function query(minimum=Number(el('minimum').value||0)){return '?freshness='+encodeURIComponent(el('freshness').value)+'&minimum_data_version='+minimum;}
async function loadCustomer(gid=el('party').value.trim(),source=null,serial=++profileSerial){
  if(state.mode==='preview'){const p=preview.previewCustomer(gid);if(!p)throw new Error('This ID is not part of the read-only preview fixtures.');state.source=p.source;state.profile=p.view;renderProfile();renderMetrics();return;}
  state.profile=null;state.source=null;renderProfile();
  const {data}=await api('/pilot/experience/v1/customers/'+encodeURIComponent(gid)+query(0),'GET',undefined,{name:'Read approved customer view',remember:true});
  if(serial!==profileSerial)return;
  state.profile=data;state.source=can('system')?source:null;
  if(source){el('reference').value=source.external_reference;el('customer-version').value=source.version;}
  if(relationships().length)selectScope(relationships()[0].scope_id);
  renderProfile();renderDirectory();renderMetrics();
}
async function loadRelationship(){
  const sid=el('scope').value.trim(),serial=++profileSerial;
  const {data}=await api('/pilot/experience/v1/relationships/'+encodeURIComponent(sid)+query(),'GET',undefined,{name:'Read approved relationship',remember:true});
  if(serial!==profileSerial)return;
  const gid=rows(data).find(r=>r.table==='party')?.row.global_party_id;
  if(!state.profile||!gid||state.profile.global_party_id!==gid){state.source=null;state.profile={global_party_id:gid,views:[data]};}
  else state.profile={...state.profile,views:[...state.profile.views.filter(v=>v.scope_id!==data.scope_id),data]};
  state.tab='relationships';selectScope(data.scope_id);el('scope-version').value=data.data_version;
  renderProfile();renderMetrics();
}
function activityMarkup(){
  return state.activity.length?state.activity.map(a=>'<div class="activity-row"><span class="http-code '+(Number(a.status)>=400||a.status==='—'?'error':'')+'">'+esc(a.status)+'</span><div><strong>'+esc(a.name)+'</strong><small>'+esc(a.method)+' · Trace '+esc(a.trace||'not received')+'</small></div><span class="muted">'+esc(a.ms)+'ms</span></div>').join(''):'<p class="muted">No API requests in this session.</p>';
}
function renderActivity(){el('activity-list').innerHTML=activityMarkup();if(state.tab==='activity'&&state.profile)renderProfile();}
function renderConnection(){
  const data=state.runtime;
  el('connection-summary').innerHTML=state.mode==='preview'?'<p class="policy-note">BROWSER PREVIEW · read-only sample fixtures. No backend has been contacted.</p>':
    !data?'<p class="policy-note">No current backend readiness evidence. Connect an identity or refresh the live connection.</p>':
    '<p class="policy-note">'+esc(data.footprint==='mdm-compact'?'Compact MDM · SG and UK':'Full pilot footprint')+' · checked '+esc(data.checked.toLocaleTimeString())+'</p><p class="field-hint">'+esc(data.suspended_regions.length?'Suspended regions: '+data.suspended_regions.join(', ')+'. Pending delivery is retained until the full footprint resumes.':'All configured regions are active.')+' Telemetry: '+esc(data.telemetry)+'.</p>';
  el('dependency-list').innerHTML=data?data.components.map(c=>'<div class="dependency-row"><span>'+esc(c.label)+'</span><span class="pill '+(c.state==='ready'?'':'warning')+'">'+esc(c.state)+'</span></div>').join(''):'';
}
async function upsert(){
  if(!can('system'))throw new Error('An authenticated source-system identity is required.');
  const body={request_id:crypto.randomUUID(),expected_version:Number(el('customer-version').value),display_name:el('name').value,party_type:el('party-type').value,identity_profile:el('profile').value};
  const {data}=await api('/pilot/system/v1/customers/'+encodeURIComponent(el('reference').value),'PUT',body,{name:'Save source customer',remember:true});
  el('party').value=data.global_party_id;el('customer-version').value=data.version;
  const write=state.last;closeDialogs();try{await loadDirectory();await loadCustomer(data.global_party_id,data);}finally{state.last=write;}toast('Customer saved in Singapore. Its approved view was read back from the API.');
}
async function createRelationship(){
  if(!can('system'))throw new Error('An authenticated source-system identity is required.');
  if(!state.source)throw new Error('Select an owner source customer first.');
  const body={request_id:crypto.randomUUID(),expected_version:state.source.version,email:el('email').value,sharing_profile:el('sharing').value};
  const {data}=await api('/pilot/system/v1/customers/'+encodeURIComponent(state.source.external_reference)+'/relationships','POST',body,{name:'Create banking relationship',remember:true});
  const source=state.source,write=state.last;closeDialogs();state.tab='relationships';try{await loadCustomer(data.global_party_id,source);selectScope(data.scope_id);}finally{state.last=write;}renderProfile();toast('Relationship committed. Recipient projections follow source-side policy.');
}
async function command(name){
  if(!canCommand(name))throw new Error('This command is outside the current identity delegation.');
  if(!el('scope').value)throw new Error('Select an approved relationship first.');
  const body={request_id:crypto.randomUUID(),expected_version:Number(el('scope-version').value),command:name,...(name==='update_contact'?{value:el('command-value').value}:{})};
  const {data}=await api('/pilot/experience/v1/relationships/'+encodeURIComponent(el('scope').value)+'/commands','POST',body,{name:label(name)+' · owner-routed command',remember:true});
  const write=state.last,version=data.scope_versions?.[el('scope').value]||data.data_version;
  if(version){el('scope-version').value=version;el('minimum').value=version;}
  closeDialogs();state.last=write;
  toast('Command committed by the owner. Refresh the relationship to verify the new version.');
}
for(const button of document.querySelectorAll('[data-close]'))button.onclick=()=>button.closest('dialog').close();
for(const form of document.querySelectorAll('dialog form'))form.addEventListener('submit',event=>event.preventDefault());
el('identity-form').onsubmit=event=>{event.preventDefault();run(connect);};
el('customer-form').onsubmit=event=>{event.preventDefault();run(upsert);};
el('relationship-form').onsubmit=event=>{event.preventDefault();run(createRelationship);};
el('contact-form').onsubmit=event=>{event.preventDefault();run(()=>command('update_contact'));};
el('identity-switch').onclick=()=>openDialog('identity-dialog');
el('disconnect').onclick=()=>{disconnect();closeDialogs();};
el('token').addEventListener('input',()=>{if(state.session){const value=el('token').value;disconnect();el('token').value=value;}});
for(const button of document.querySelectorAll('[data-principal]'))button.onclick=()=>{
  if(state.session)disconnect();
  for(const b of document.querySelectorAll('[data-principal]'))b.classList.toggle('selected',b===button);
  el('credential-command').textContent='./lab pilot-token '+button.dataset.principal;
};
el('new-customer').onclick=()=>{el('reference').value='SYN-DEMO-'+crypto.randomUUID().slice(0,8).toUpperCase();el('name').value='Synthetic Pilot Customer';el('customer-version').value='0';el('party-type').value='PERSON';el('profile').value='owner_only';openDialog('customer-dialog');};
el('source').onclick=()=>run(async()=>{const {data}=await api('/pilot/system/v1/customers/'+encodeURIComponent(el('reference').value),'GET',undefined,{name:'Read source customer',remember:true});el('customer-version').value=data.version;el('name').value=data.display_name;el('party-type').value=data.party_type;el('profile').value=data.identity_profile;el('party').value=data.global_party_id;});
el('customer').onclick=()=>run(()=>loadCustomer());
el('view').onclick=()=>run(loadRelationship);
el('next-page').onclick=()=>run(()=>loadDirectory(state.next));
el('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{if(state.mode==='preview')renderDirectory();else loadDirectory().catch(error=>{if(!(error instanceof SessionChanged))toast(error.message);});},300);};
el('refresh').onclick=()=>run(async()=>{if(state.mode==='unavailable'){location.reload();return;}if(!state.session&&state.mode==='live'){toast('Connect an identity to verify the live services.');return;}if(state.mode==='preview'){renderDirectory();return;}await probe();if(can('system'))await loadDirectory();if(state.profile)await loadCustomer(state.profile.global_party_id,state.source);});
el('retry').onclick=()=>run(async()=>{const last=state.last;if(!last||last.epoch!==epoch)return;const {data}=await api(last.path,last.method,last.body,{name:last.name+' · unchanged retry',remember:true});if(data.global_party_id)el('party').value=data.global_party_id;if(data.scope_id)el('scope').value=data.scope_id;toast('The unchanged request was replayed. Inspect its API receipt.');});
el('connection-details').onclick=()=>{renderConnection();openDialog('connection-dialog');};
el('help').onclick=()=>openDialog('help-dialog');
el('walkthrough').onclick=()=>{el('journey').hidden=!el('journey').hidden;if(!el('journey').hidden)el('journey').scrollIntoView({behavior:'smooth',block:'start'});};
el('close-journey').onclick=()=>el('journey').hidden=true;
el('nav-customers').onclick=()=>{state.tab='overview';renderProfile();el('directory-heading').scrollIntoView({behavior:'smooth',block:'center'});};
el('nav-relationships').onclick=()=>{state.tab='relationships';renderProfile();if(!state.profile)toast('Select a customer to inspect its approved relationships.');};
el('nav-activity').onclick=el('show-evidence').onclick=()=>{el('evidence-panel').hidden=!el('evidence-panel').hidden;if(!el('evidence-panel').hidden)el('evidence-panel').scrollIntoView({behavior:'smooth',block:'start'});};
setInterval(()=>{if(!document.hidden&&state.session?.context&&!state.busy)probe().catch(error=>{if(!(error instanceof SessionChanged))renderConnection();});},20000);
try{
  const config=await readDeployment();
  if(config.mode==='simulation'){
    state.mode='preview';preview=await import('./preview.mjs');
    showRuntime(el('runtime-status'),'demo','BROWSER PREVIEW · no backend connection','Read-only sample profiles. No API calls, CockroachDB writes or OPA checks. Use the container pilot for real transactions.');
    const first=preview.previewCustomer(preview.previewCustomers[0].global_party_id);
    state.source=first.source;state.profile=first.view;el('party').value=first.view.global_party_id;renderProfile();renderDirectory();
  }else if(config.pilot!==true){
    state.mode='unavailable';showRuntime(el('runtime-status'),'offline','MDM PILOT NOT ENABLED ON THIS GATEWAY','This page cannot reach the authenticated pilot here. Run ./lab pilot-compact-up or ./lab pilot-up, then open port 8081. No simulated fallback.');
  }else{state.mode='live';disconnect();}
}catch{
  state.mode='unavailable';showRuntime(el('runtime-status'),'offline','DEPLOYMENT MODE UNAVAILABLE','The UI cannot verify its configuration. Customer actions remain disabled; no browser preview has been substituted.');
}
controls();renderMetrics();renderConnection();
