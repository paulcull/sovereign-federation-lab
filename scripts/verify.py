"""Offline source, deployment and documentation contracts. Not a container test."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit,unquote
import ast,json,re,sys
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'dist';errors=[];links=0;external=set()
class Document(HTMLParser):
    def __init__(self,s):
        super().__init__();self.ids=[];self.links=[];self.feed(s)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.append(a['id'])
        for k in ('href','src'):
            if k in a:self.links.append(a[k])
docs={p:Document(p.read_text()) for p in OUT.rglob('*.html')}
release={'/downloads/sovereign-federation-lab.zip','/downloads/sovereign-federation-lab.bundle','/downloads/sovereign-data-poc.zip'}
spa={'monitor','business','services','entities','customers','policy','generator','technical'}
def check_url(source,url,web=True):
    global links
    parsed=urlsplit(url)
    if parsed.scheme in ('http','https','mailto','data','blob'):external.add(url);return
    if url.startswith('//'):external.add(url);return
    if not url or url.startswith(('javascript:','tel:')):return
    if web and parsed.path in ('/api-docs','/openapi.json'):return
    if web and parsed.path in release and '--release' not in sys.argv:return
    target=((OUT if web else ROOT)/parsed.path.lstrip('/')) if parsed.path.startswith('/') else source.parent/parsed.path
    if not parsed.path:target=source
    target=target.resolve()
    if target.is_dir():target=target/'index.html'
    if web and '--release' not in sys.argv and target.is_relative_to(OUT) and '/'+str(target.relative_to(OUT)) in release:return
    links+=1
    if not target.exists():errors.append(f'{source.relative_to(ROOT)} → missing {url}');return
    if parsed.fragment and target.suffix=='.html':
        fragment=unquote(parsed.fragment)
        if target.name=='monitor.html' and fragment in spa:return
        if target==OUT/'scale.html' and fragment in {'overview','workloads','storage','pilot'} and 'tab=location.hash.slice(1)' in (OUT/'scale/app.js').read_text():return
        if fragment not in docs.get(target,Document(target.read_text())).ids:errors.append(f'{source.relative_to(ROOT)} → missing fragment {url}')
for path,d in docs.items():
    if len(d.ids)!=len(set(d.ids)):errors.append(f'duplicate HTML IDs: {path.relative_to(ROOT)}')
    for u in d.links:check_url(path,u)
    text=path.read_text()
    if 'MIGRATION_STORAGE=sqlite' in text or 'compose.migration.yaml up' in text:errors.append(f'obsolete deployment instructions: {path.relative_to(ROOT)}')
    if 'https://customer-federation-design.paulcull.chatgpt.site' in text or 'https://sovereign-data-monitor.paulcull.chatgpt.site' in text:errors.append(f'non-portable historical project link: {path.relative_to(ROOT)}')
for path in [*ROOT.glob('*.md'),*ROOT.glob('docs/*.md'),*ROOT.glob('docs/adr/*.md')]:
    content=re.sub(r'```[\s\S]*?```','',path.read_text())
    for match in re.finditer(r'!?\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)',content):check_url(path,match[1],False)
for path in OUT.rglob('*'):
    if path.suffix in ('.js','.mjs'):
        for ref in re.findall(r'(?:from\s*|import\s*)[\'"]([^\'"]+)[\'"]',path.read_text()):
            if ref.startswith(('./','../')):check_url(path,ref)
    if path.suffix=='.css':
        for ref in re.findall(r'url\([\'"]?([^\)\'\"]+)',path.read_text()):check_url(path,ref)
for path in (ROOT/'poc').rglob('*.py'):ast.parse(path.read_text(),filename=str(path))
for path in (ROOT/'scripts').glob('*.py'):ast.parse(path.read_text(),filename=str(path))
c=json.loads((ROOT/'compose.yaml').read_text());services=c['services']
assert {x for x in services if x.startswith('db-')}=={'db-sg','db-uk','db-us','db-in'}
assert {x for x in services if x.startswith('opa-')}=={'opa-sg','opa-uk','opa-us','opa-in'}
assert [k for k,v in services.items() if v.get('ports')]==['gateway']
assert services['gateway']['ports'][0].startswith('127.0.0.1:')
assert services['monitor']['environment']['MIGRATION_STORAGE']=='cockroach'
for name in ('db-sg','db-uk','db-us','db-in'):
    assert services[name]['command'][0]=='start-single-node'
    assert services[name]['volumes'] and services[name]['healthcheck']
for name in ('opa-sg','opa-uk','opa-us','opa-in'):assert '--disable-telemetry' in services[name]['command']
assert json.loads((ROOT/'infra/lab-config.live.json').read_text())['database']=='cockroach'
assert json.loads((OUT/'lab-config.json').read_text())['mode']=='simulation'
assert 'localhost\'||location.hostname' not in (OUT/'app.js').read_text()
assert json.loads((ROOT/'shared/catalog.json').read_text())==json.loads((OUT/'catalog.json').read_text())
assert json.loads((ROOT/'shared/operational.json').read_text())==json.loads((OUT/'operational.json').read_text())
adrs=json.loads((ROOT/'docs/adrs.json').read_text());assert len(adrs)==16 and len({a['id'] for a in adrs})==16
for a in adrs:
    for key in ('status','context','decision','alternatives','consequences','evidence','gate'):assert a[key]
    for ref in a['evidence'].split('; '):assert (ROOT/ref).exists(),ref
assert len(json.loads((OUT/'design/design-index.json').read_text()))==28
assert (OUT/'design/development-lab.html').exists() and (OUT/'design/adr-register.html').exists()
if errors:
    print('\n'.join(errors));raise SystemExit(1)
print(f'PASS {len(docs)} HTML pages; {links} local links/assets/fragments; Python syntax; 16 ADRs; canonical fixtures; four-store Cockroach-only deployment contracts. {len(external)} external references inventoried, not uptime-verified.')
