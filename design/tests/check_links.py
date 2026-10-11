from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit,unquote
from status_claims import assert_current_status
root=Path(__file__).resolve().parents[1]/'dist'
lab_root=root.parents[1]/'dist'
class Check(HTMLParser):
 def __init__(self):super().__init__();self.ids=[];self.links=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if 'id' in a:self.ids.append(a['id'])
  if tag in ('a','link','script'):self.links.append(a.get('href',a.get('src','')))
import json
files=list(root.glob('*.html'))
expected={p['slug']+'.html' for p in json.loads((root/'design-index.json').read_text())}
assert {p.name for p in files}==expected
for p in files:
 c=Check();c.feed(p.read_text());assert len(c.ids)==len(set(c.ids)),p
 for link in c.links:
  if link.startswith(('https:','http:')):continue
  if not link:continue
  parsed=urlsplit(link)
  target=(lab_root/parsed.path.lstrip('/')) if parsed.path.startswith('/') else p.parent/parsed.path
  if not parsed.path:target=p
  assert target.exists(),(p,link)
  if parsed.fragment and target.suffix=='.html':
   dest=Check();dest.feed(target.read_text())
   assert unquote(parsed.fragment) in dest.ids,(p,link)
 assert 'engineering-prompt' in c.ids
 assert 'HAND OFF TO ENGINEERING' in p.read_text()
opa=__import__('html').unescape((root/'opa.html').read_text())
federation=__import__('html').unescape((root/'federation.html').read_text())
assert '"owner_entity_id": "LE-SG-01"' in opa
assert '"denied_countries": ["US"]' in opa
assert '"destination_entity_id": "LE-GB-02"' in federation
context=(root/'project-context.html').read_text()
assert 'What the demonstration answers' in context and 'independent business ownership' in context
for p in files:
 assert_current_status(p.read_text(),p.stem)
isolation=(root/'work-isolation.html').read_text()
for contract in ['Authority guard','Operational delivery','Policy reconciliation','202 Accepted','contiguous applied revocation watermark']:
 assert contract in isolation,contract
print(f'Passed: {len(files)} pages, internal links, local assets, unique IDs, integrated prompts and isolation contracts.')
