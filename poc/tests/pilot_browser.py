"""Real MDM workspace: SQL-backed APIs, role changes, privacy and actual API outage."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from playwright.sync_api import sync_playwright, expect, Error as PlaywrightError

parser=argparse.ArgumentParser()
parser.add_argument('--compact',action='store_true')
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[2]
config=json.loads((ROOT/'.pilot/api/config.json').read_text())
base=os.getenv('PILOT_URL','http://127.0.0.1:8081')
out=ROOT/'artifacts/pilot/browser';out.mkdir(parents=True,exist_ok=True)
compose=['docker','compose','-f','compose.yaml','-f','compose.pilot.yaml']
if args.compact:compose+=['-f','infra/compose.mdm-compact.yaml']

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH') or shutil.which('chromium'),
        headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1100})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    response=page.goto(base+'/',wait_until='domcontentloaded');assert response.status==200
    expect(page.get_by_role('heading',name='Customer workspace',exact=True)).to_be_visible()
    expect(page.locator('#runtime-status')).to_contain_text('identity not connected')
    expect(page.locator('.customer-row')).to_have_count(0)
    expect(page.locator('#new-customer')).to_be_disabled()

    def identity(name):
        if not page.locator('#identity-dialog').evaluate('(d)=>d.open'):
            page.locator('#identity-switch').click()
        button=page.locator('[data-principal="'+name+'"]')
        if button.count():button.click()
        page.locator('#token').fill(config['principals'][name]['token'])
        page.locator('#connect').click()
        expect(page.locator('#identity')).to_contain_text(config['principals'][name]['entity_id'])
        expect(page.locator('#identity-dialog')).not_to_be_visible()
        expect(page.locator('#runtime-status')).to_contain_text('LIVE PILOT')
        expect(page.locator('#runtime-status')).to_contain_text('SG + UK connected' if args.compact else 'full footprint connected',timeout=30000)

    def click(selector,method,fragment,status=200):
        with page.expect_response(lambda r:r.request.method==method and fragment in r.url) as result:
            page.locator(selector).click()
        assert result.value.status==status,(selector,result.value.status,status)
        assert len(result.value.headers.get('x-trace-id',''))==32
        return result.value.json()

    def eventually(selector,fragment,predicate):
        deadline=time.monotonic()+45
        while True:
            with page.expect_response(lambda r:r.request.method=='GET' and fragment in r.url) as result:
                page.locator(selector).click()
            if result.value.status==200 and predicate(result.value.json()):
                return result.value.json()
            assert time.monotonic()<deadline,'Approved API view did not converge'
            page.wait_for_timeout(400)

    identity('crm-sg')
    reference='SYN-BROWSER-'+uuid.uuid4().hex.upper()
    page.locator('#new-customer').click()
    page.locator('#reference').fill(reference)
    page.locator('#name').fill('Synthetic Browser Customer')
    page.locator('#profile').select_option('global_minimum')
    customer=click('#upsert','PUT','/pilot/system/v1/customers/')
    assert customer['owner_entity_id']=='LE-SG-01'
    expect(page.locator('#party')).to_have_value(customer['global_party_id'])
    expect(page.locator('.profile-name h2')).to_have_text('Synthetic Browser Customer',timeout=30000)
    page.locator('#add-relationship').click()
    page.locator('#sharing').select_option('uk_servicing_no_us')
    relationship=click('#relationship','POST','/relationships')
    expect(page.locator('#scope')).to_have_value(relationship['scope_id'])
    expect(page.locator('.relationship-card')).to_have_count(1)
    page.screenshot(path=str(out/'mdm-system.png'),full_page=True)

    page.reload()
    expect(page.locator('.customer-row')).to_have_count(0)
    expect(page.locator('#search')).to_have_value('')
    expect(page.locator('#reference')).to_have_value('')
    expect(page.locator('#scope')).to_have_value('')
    assert 'Synthetic Browser Customer' not in page.locator('main').inner_text()
    assert page.evaluate('localStorage.length===0 && sessionStorage.length===0')
    identity('crm-sg')
    page.locator('#search').fill(reference)
    expect(page.locator('.customer-row')).to_have_count(1)
    page.locator('.customer-row').click()
    expect(page.locator('.profile-name h2')).to_have_text('Synthetic Browser Customer')
    print('PASS real source directory persists across page reload; credentials and private profile data do not',flush=True)

    # Hold a real owner's API response across the identity switch. No fake data.
    held=[]
    owner_url=base+'/pilot/system/v1/customers/'+reference
    def hold_owner(route):
        actual=route.fetch()
        assert actual.status==200
        held.append((route,actual))
    page.route(owner_url,hold_owner)
    page.locator('.customer-row').click()
    deadline=time.monotonic()+10
    while not held:
        assert time.monotonic()<deadline,'Owner response was not intercepted'
        page.wait_for_timeout(50)
    identity('uk-servicing')
    for route,actual in held:
        try:route.fulfill(response=actual)
        except PlaywrightError:pass  # AbortController may already have cancelled it.
    page.unroute(owner_url)
    page.wait_for_timeout(50)
    expect(page.locator('.customer-row')).to_have_count(0)
    expect(page.locator('#search')).to_have_value('')
    expect(page.locator('#reference')).to_have_value('')
    expect(page.locator('#scope')).to_have_value('')
    assert 'Synthetic Browser Customer' not in page.locator('main').inner_text()
    assert reference not in page.locator('#directory').inner_text()
    print('PASS late real owner response cannot repopulate a different identity session',flush=True)
    page.locator('#party').fill(customer['global_party_id'])
    view=eventually('#customer','/pilot/experience/v1/customers/',
        lambda d:any(r['table']=='contact_info' for v in d['views'] for r in v['rows']))
    page.get_by_role('tab',name='Relationships',exact=True).click()
    scope=relationship['scope_id']
    page.locator('[data-contact="'+scope+'"]').click()
    page.locator('#command-value').fill('browser.updated@example.invalid')
    changed=click('#contact','POST','/commands')
    expect(page.locator('#minimum')).to_have_value(str(changed['scope_versions'][scope]))
    view=eventually('[data-open-scope="'+scope+'"]','/pilot/experience/v1/relationships/',
        lambda d:any(r['table']=='contact_info' and r['row'].get('value')=='browser.updated@example.invalid' for r in d['rows']))
    assert view['served_from']=='projection'
    expect(page.locator('.relationship-contact').filter(has_text='browser.updated@example.invalid')).to_be_visible()
    expect(page.locator('#metric-source')).to_contain_text('Projection')
    page.screenshot(path=str(out/'uk-experience.png'),full_page=True)
    print('PASS real UK projection, owner-routed contact command, current version and visible rendered contact',flush=True)

    if not args.compact:
        identity('us-reader');expect(page.locator('#minimum')).to_have_value('0')
        assert 'browser.updated@example.invalid' not in page.locator('main').inner_text()
        page.locator('#party').fill(customer['global_party_id'])
        view=eventually('#customer','/pilot/experience/v1/customers/',lambda d:bool(d['views']))
        assert len(view['views'])==1 and view['views'][0]['scope_kind']=='party'
        assert set(view['views'][0]['rows'][0]['row'])=={'id','global_party_id','party_type'}
        assert 'browser.updated@example.invalid' not in json.dumps(view)
        expect(page.locator('.profile-name h2')).to_have_text('Restricted customer identity')
        page.get_by_role('tab',name='Relationships',exact=True).click()
        expect(page.locator('.relationship-card')).to_have_count(0)
        page.screenshot(path=str(out/'us-minimum.png'),full_page=True)
        page.locator('#show-evidence').click()
        page.locator('#advanced-tools > summary').click()
        page.locator('#scope').fill(scope)
        click('#view','GET','/pilot/experience/v1/relationships/',403)
        assert 'browser.updated@example.invalid' not in page.locator('main').inner_text()
        print('PASS US exact minimal fields, undisclosed relationships and explicit denied relationship; no owner/UK cache leak',flush=True)
    else:
        page.locator('#connection-details').click()
        expect(page.locator('#connection-summary')).to_contain_text('Suspended regions: US, IN')
        expect(page.locator('#connection-summary')).to_contain_text('Telemetry: suspended')
        page.get_by_role('button',name='Close connection details').click()

    identity('crm-sg')
    stopped=False
    try:
        result=subprocess.run(compose+['stop','pilot-api'],cwd=ROOT,capture_output=True,text=True)
        assert result.returncode==0,'Could not stop the actual pilot API'
        stopped=True
        page.locator('#refresh').click()
        expect(page.locator('#runtime-status')).to_contain_text('connection unavailable',timeout=30000)
        expect(page.locator('.customer-row')).to_have_count(0)
        assert 'BROWSER PREVIEW' not in page.locator('#runtime-status').inner_text()
        assert 'Synthetic Maya Chen' not in page.locator('main').inner_text()
        page.screenshot(path=str(out/'actual-api-outage.png'),full_page=True)
    finally:
        if stopped:
            restored=subprocess.run(compose+['start','pilot-api'],cwd=ROOT,capture_output=True,text=True)
            assert restored.returncode==0,'Actual API restart failed'
    deadline=time.monotonic()+45
    while True:
        probe=page.request.get(base+'/pilot/api/v1/context',
            headers={'Authorization':'Bearer '+config['principals']['crm-sg']['token']})
        if probe.status==200:break
        assert time.monotonic()<deadline,'Pilot API did not recover'
        page.wait_for_timeout(500)
    page.reload();identity('crm-sg')
    page.locator('#search').fill(reference)
    expect(page.locator('.customer-row')).to_have_count(1)
    print('PASS actual stopped API clears unverified data, never loads preview fixtures, and recovers real SQL records',flush=True)

    for width in (375,768,1440):
        page.set_viewport_size({'width':width,'height':1100})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        page.screenshot(path=str(out/('pilot-'+str(width)+'.png')),full_page=True)
    assert not errors,errors
    browser.close()
print('PASS real modern MDM workspace, role-safe views, evidence, actual outage and responsive layouts')
