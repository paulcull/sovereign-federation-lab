"""Click through real system/experience APIs; synthetic operator console only."""
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
config = json.loads((ROOT / '.pilot/api/config.json').read_text())
base = os.getenv('PILOT_URL', 'http://127.0.0.1:8081')
out = ROOT / 'artifacts/pilot/browser'; out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH') or shutil.which('chromium'),
                                headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':1440,'height':1100})
    errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
    response=page.goto(base + '/',wait_until='domcontentloaded'); assert response.status==200
    expect(page.get_by_role('heading',name='Customer MDM · system and experience APIs')).to_be_visible()

    def identity(name):
        page.locator('#token').fill(config['principals'][name]['token'])
        page.locator('#connect').click()
        expect(page.locator('#identity')).to_contain_text(config['principals'][name]['entity_id'])

    def click(button, method, fragment, status=200):
        with page.expect_response(lambda r:r.request.method==method and fragment in r.url) as result:
            page.locator('#'+button).click()
        assert result.value.status==status, (button,result.value.status,status)
        return result.value.json()

    identity('crm-sg')
    reference='SYN-BROWSER-'+uuid.uuid4().hex.upper()
    page.locator('#reference').fill(reference)
    page.locator('#name').fill('Synthetic Browser Customer')
    page.locator('#profile').select_option('global_minimum')
    customer=click('upsert','PUT','/pilot/system/v1/customers/')
    assert customer['owner_entity_id']=='LE-SG-01'
    expect(page.locator('#party')).to_have_value(customer['global_party_id'])
    page.locator('#sharing').select_option('uk_servicing_no_us')
    relationship=click('relationship','POST','/relationships')
    expect(page.locator('#scope')).to_have_value(relationship['scope_id'])
    page.screenshot(path=str(out/'mdm-system.png'),full_page=True)

    identity('uk-servicing')
    end=time.monotonic()+45
    while True:
        with page.expect_response(lambda r:'/pilot/experience/v1/relationships/' in r.url and r.request.method=='GET') as result:
            page.locator('#view').click()
        if result.value.status==200:break
        assert time.monotonic()<end
        page.wait_for_timeout(500)
    assert any(r['table']=='contact_info' for r in result.value.json()['rows'])
    page.locator('#email').fill('browser.updated@example.invalid')
    changed=click('contact','POST','/commands')
    page.locator('#minimum').fill(str(changed['scope_versions'][relationship['scope_id']]))
    end=time.monotonic()+45
    while True:
        with page.expect_response(lambda r:'/pilot/experience/v1/relationships/' in r.url and r.request.method=='GET') as result:
            page.locator('#view').click()
        if result.value.status==200 and 'browser.updated@example.invalid' in result.value.text():break
        assert time.monotonic()<end
        page.wait_for_timeout(500)
    page.screenshot(path=str(out/'uk-experience.png'),full_page=True)
    identity('us-reader');page.locator('#minimum').fill('0')
    view=click('customer','GET','/pilot/experience/v1/customers/')
    assert len(view['views'])==1 and view['views'][0]['scope_kind']=='party'
    assert set(view['views'][0]['rows'][0]['row'])=={'id','global_party_id','party_type'}
    assert 'browser.updated@example.invalid' not in json.dumps(view)
    page.screenshot(path=str(out/'us-minimum.png'),full_page=True)
    click('view','GET','/pilot/experience/v1/relationships/',403)

    for width in (375,768,1440):
        page.set_viewport_size({'width':width,'height':1100})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        page.screenshot(path=str(out/f'pilot-{width}.png'),full_page=True)
    assert not errors,errors
    browser.close()
    print('PASS real browser MDM creation, system and experience API calls, routed contact update, US minimum and exclusion; responsive operator console')
