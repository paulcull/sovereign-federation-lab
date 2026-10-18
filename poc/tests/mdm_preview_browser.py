"""Static/failed-runtime UI checks. These are not CockroachDB integration evidence."""
import functools
import http.server
import json
import os
from pathlib import Path
import shutil
import threading

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[2]
out=ROOT/'artifacts/mdm-workspace/preview'
out.mkdir(parents=True,exist_ok=True)
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),
    functools.partial(Quiet,directory=str(ROOT/'dist')))
threading.Thread(target=server.serve_forever,daemon=True).start()
base='http://127.0.0.1:'+str(server.server_port)
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH') or shutil.which('chromium'),
            headless=True,args=['--no-sandbox'])
        retry_page=browser.new_page()
        retry_page.goto(base+'/design/index.html')
        configuration_calls=[]
        def transient_configuration(route):
            configuration_calls.append(route.request.url)
            if len(configuration_calls)==1:route.abort()
            else:route.fulfill(status=200,content_type='application/json',
                body=json.dumps({'mode':'live','database':'cockroach','pilot':True}))
        retry_page.route('**/lab-config.json',transient_configuration)
        retry_page.evaluate('''async()=>{
            const {readDeployment}=await import('/runtime-status.mjs');
            let failed=false;try{await readDeployment();}catch{failed=true;}
            if(!failed)throw Error('The first configuration request must fail');
            const result=await readDeployment();
            if(result.mode!=='live'||result.database!=='cockroach')throw Error('Recovery must return live configuration');
        }''')
        assert len(configuration_calls)==2,'A rejected configuration promise must be retried'
        retry_page.close()
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        calls=[];page.on('request',lambda r:calls.append(r.url) if '/pilot/' in r.url else None)
        page.goto(base+'/pilot.html')
        expect(page.locator('#runtime-status')).to_contain_text('BROWSER PREVIEW')
        expect(page.locator('.customer-row')).to_have_count(3)
        expect(page.locator('#new-customer')).to_be_disabled()
        expect(page.locator('#identity-switch')).to_be_disabled()
        page.get_by_role('tab',name='Relationships',exact=True).click()
        expect(page.locator('.relationship-card')).to_have_count(1)
        page.locator('#search').fill('Aster')
        expect(page.locator('.customer-row')).to_have_count(1)
        page.locator('.customer-row').click()
        expect(page.locator('.profile-name h2')).to_have_text('Synthetic Aster Trading')
        page.get_by_role('tab',name='Overview',exact=True).click()
        # Computed foregrounds against the workspace's white/light surfaces.
        contrast=page.evaluate('''()=>{
            const linear=c=>{c/=255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;};
            return ['.attribute dt','.profile-meta','.field-hint'].map(selector=>{
                const color=getComputedStyle(document.querySelector(selector)).color;
                const rgb=color.match(/[\\d.]+/g).slice(0,3).map(Number);
                const luminance=rgb.map(linear).reduce((n,c,i)=>n+c*[.2126,.7152,.0722][i],0);
                return {selector,ratio:1.05/(luminance+.05)};
            });
        }''')
        assert all(item['ratio']>=4.5 for item in contrast),contrast
        assert not calls, 'Browser preview must not call any pilot API'
        assert page.evaluate('localStorage.length===0 && sessionStorage.length===0')
        for width in (375,768,1440):
            page.set_viewport_size({'width':width,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            page.screenshot(path=str(out/('preview-'+str(width)+'.png')),full_page=True)

        page.route('**/lab-config.json',lambda route:route.fulfill(status=200,
            content_type='application/json',body=json.dumps({'mode':'live','database':'cockroach','pilot':True})))
        page.goto(base+'/pilot.html')
        expect(page.locator('#runtime-status')).to_contain_text('identity not connected')
        expect(page.locator('.customer-row')).to_have_count(0)
        page.route('**/pilot/api/**',lambda route:route.abort())
        page.locator('#identity-switch').click()
        page.locator('#token').fill('synthetic-invalid-test-token')
        page.locator('#connect').click()
        expect(page.locator('#runtime-status')).to_contain_text('connection unavailable')
        expect(page.locator('.customer-row')).to_have_count(0)
        assert 'Synthetic Maya Chen' not in page.locator('#profile-content').inner_text()
        page.screenshot(path=str(out/'live-unavailable.png'),full_page=True)
        page.unroute('**/lab-config.json')
        page.route('**/lab-config.json',lambda route:route.fulfill(status=200,
            content_type='application/json',body=json.dumps({'mode':'live','database':'sqlite','pilot':True})))
        page.goto(base+'/pilot.html')
        expect(page.locator('#runtime-status')).to_contain_text('DEPLOYMENT MODE UNAVAILABLE')
        expect(page.locator('#new-customer')).to_be_disabled()
        expect(page.locator('.customer-row')).to_have_count(0)
        assert not errors,errors
        browser.close()
finally:
    server.shutdown()
print('PASS configuration-fetch retry, essential label contrast, read-only fixtures, zero pilot API calls/storage, responsive layouts and no failed-live fallback')
