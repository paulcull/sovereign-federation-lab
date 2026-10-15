"""Build the portable lab portal, monitor, design pages and ADRs. No network."""
from pathlib import Path
import html,json,os,re,shutil,subprocess,sys
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'dist';OUT.mkdir(exist_ok=True)
DESIGN_ORIGIN='https://customer-federation-design.paulcull.chatgpt.site'
MONITOR_ORIGIN='https://sovereign-data-monitor.paulcull.chatgpt.site'
def portable(s):
    s=s.replace(DESIGN_ORIGIN+'/','/design/').replace(DESIGN_ORIGIN,'/design/index.html')
    s=s.replace(MONITOR_ORIGIN+'/#','/monitor.html#').replace(MONITOR_ORIGIN+'/','/').replace(MONITOR_ORIGIN,'/monitor.html')
    return s
def page(title,body):
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+' · Sovereign Lab</title><link rel="stylesheet" href="/lab.css"></head><body><header><a class="brand" href="/">SOVEREIGN <span>DEVELOPMENT LAB</span></a><nav aria-label="Lab navigation"><a href="/monitor.html">Monitor</a><a href="/migration.html">Relocation</a><a href="/design/index.html">Design</a><a href="/design/adr-register.html">ADRs</a><a href="/design/development-lab.html">Run guide</a></nav></header><main>'+body+'</main><footer>Synthetic bank data · CockroachDB / OPA / OpenTelemetry · Edition 09</footer></body></html>'
for src in (ROOT/'web/monitor').rglob('*'):
    if not src.is_file():continue
    rel=src.relative_to(ROOT/'web/monitor');dest=OUT/('monitor.html' if str(rel)=='index.html' else rel)
    dest.parent.mkdir(parents=True,exist_ok=True)
    if src.suffix in ('.html','.js','.mjs','.md'):
        text=portable(src.read_text()).replace('index.html#','monitor.html#')
        if src.suffix=='.html':text=text.replace('</nav>','<a href="/">⌂ <span>Lab home</span></a><a href="/design/adr-register.html">▤ <span>ADRs</span></a></nav>')
        dest.write_text(text)
    else:shutil.copy2(src,dest)
subprocess.run([sys.executable,str(ROOT/'design/src/build.py')],check=True)
for src in (ROOT/'design/dist').rglob('*'):
    if not src.is_file():continue
    dest=OUT/'design'/src.relative_to(ROOT/'design/dist');dest.parent.mkdir(parents=True,exist_ok=True)
    if src.suffix in ('.html','.js','.json'):
        s=portable(src.read_text())
        if src.suffix=='.html':
            s=s.replace('</nav>','<div class="nav-group">Development lab</div><a href="/">Lab home</a><a href="/design/development-lab.html">Container run guide</a><a href="/design/adr-register.html">ADR register</a></nav>',1)
        dest.write_text(s)
    else:shutil.copy2(src,dest)
adrs=json.loads((ROOT/'docs/adrs.json').read_text());cards=[]
for a in adrs:
    recorded=a.get('recorded','11 October 2026')
    kind=a.get('kind','Retrospective project decision')
    label=a.get('kind','Retrospective architecture decision')
    name='ADR-'+a['id'];body=f'<p class="eyebrow">{html.escape(label.upper())} · {html.escape(recorded.upper())}</p><h1>{name}: {html.escape(a["title"])}</h1>'
    md=f'# {name}: {a["title"]}\n\nRecorded: {recorded}. {kind}; not a bank governance approval.\n'
    for key in ['status','context','decision','alternatives','consequences','evidence','gate']:
        value=a[key];body+='<section><h2>'+key.title()+'</h2><p>'+html.escape(value)+'</p></section>';md+='\n## '+key.title()+'\n\n'+value+'\n'
    body+='<p><a href="/design/adr-register.html">← All decisions</a> · <a href="/guides/docs/adr/'+name+'.md">Markdown source</a></p>'
    (ROOT/'docs/adr'/f'{name}.md').write_text(md);(OUT/'design'/f'{name}.html').write_text(page(name,body))
    cards.append('<a class="card" href="/design/'+name+'.html"><small>'+name+' · '+html.escape(a['status'])+'</small><h2>'+html.escape(a['title'])+'</h2><p>'+html.escape(a['decision'])+'</p></a>')
(OUT/'design/adr-register.html').write_text(page('ADR register','<p class="eyebrow">DECISIONS WITH CONSEQUENCES</p><h1>How this architecture took shape.</h1><p class="lead">'+str(len(adrs))+' decisions and proposals, their alternatives, current implementation and acceptance gates. These are project design records, not formal bank approvals.</p><div class="cards">'+''.join(cards)+'</div>'))
(ROOT/'docs/adr/README.md').write_text('# Architecture decision register\n\nRetrospective decisions recorded on 11 October 2026; subsequent proposals carry their own dates and status.\n\n'+''.join(f'- [ADR-{a["id"]}: {a["title"]}](ADR-{a["id"]}.md) — {a["status"]}\n' for a in adrs))
for name in ['README.md','DESIGN.md','OPERATIONAL.md','MIGRATION.md','WORK_ISOLATION.md','TESTING.md']:
    target=OUT/'guides'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(portable((ROOT/name).read_text()))
for folder in ['docs','scale']:
    for src in (ROOT/folder).rglob('*'):
        if src.is_file() and src.suffix in ('.md','.json','.csv') and 'history' not in src.parts:
            dest=OUT/'guides'/src.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(portable(src.read_text()))
# Compatibility downloads live outside guides; rebase canonical relative links.
for source, destination in [('MIGRATION.md','migration/migration-guide.md'),
                            ('WORK_ISOLATION.md','isolation/work-isolation.md')]:
    target=OUT/destination
    def rebase(match):
        url=match[2];parsed=urlsplit(url)
        if parsed.scheme or url.startswith(('/', '#')):return match[0]
        canonical=(ROOT/source).parent/parsed.path
        copied=OUT/'guides'/canonical.relative_to(ROOT)
        relative=os.path.relpath(copied,target.parent)
        return match[1]+relative+url[len(parsed.path):]+match[3]
    text=portable((ROOT/source).read_text())
    target.write_text(re.sub(r'(!?\[[^\]]*\]\()([^\s)]+)(\))',rebase,text))
(OUT/'lab-config.json').write_text('{"mode":"simulation","edition":9}\n')
shutil.copy2(ROOT/'web/lab.css',OUT/'lab.css')
for src,dest in [('web/portal.html','index.html'),('web/development.html','design/development-lab.html'),('web/pilot.html','pilot.html')]:
    (OUT/dest).write_text(page('Sovereign Federation Lab', (ROOT/src).read_text()))
print(f'Built portable lab: monitor, 28 component pages, {len(adrs)} ADRs, register, deployment guide and portal.')
