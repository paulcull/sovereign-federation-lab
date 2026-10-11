"""Optional Chromium gate against the real gateway; run after ./lab test.

Requires Playwright and Chromium on the workstation. Mutates synthetic records
and resets only the isolated India fixture. Never invokes the browser simulator.
"""
import json
import os
from pathlib import Path
import re
import shutil
import time
from playwright.sync_api import sync_playwright, expect

base = os.getenv('POC_URL', 'http://127.0.0.1:8080').rstrip('/')
out = Path(os.getenv('BROWSER_ARTIFACTS', 'artifacts/browser'))
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    executable = os.getenv('CHROMIUM_PATH') or shutil.which('chromium')
    browser = playwright.chromium.launch(executable_path=executable, headless=True,
                                         args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text)
            if message.type == 'error' and 'module script' in message.text else None)

    def visit(route):
        response = page.goto(base + route, wait_until='domcontentloaded')
        if response is not None:
            assert response.status == 200, (route, response.status)

    def state():
        response = page.request.get(base + '/api/migration')
        assert response.ok
        return response.json()

    def action(selector, suffix, status=200):
        with page.expect_response(lambda r: r.url == base + '/api/migration' and r.request.method == 'GET') as refreshed, page.expect_response(lambda r: r.url == base + '/api/migration/' + suffix
                                  and r.request.method == 'POST') as pending:
            page.locator(selector).click()
        assert pending.value.status == status, (suffix, pending.value.status)
        current = refreshed.value.json()
        labels = {'DRAFT': 'Register Mumbai store', 'REGISTERED': 'Check placement eligibility',
                  'PLANNED': 'Capture snapshot & start', 'COPYING': 'Copy next 8 rows',
                  'CATCHING_UP': 'Apply next committed changes' if current['delta_lag'] else 'Validate target data',
                  'VALIDATED': 'Fence Singapore writer',
                  'FENCED': 'Drain final changes' if current['delta_lag'] else 'Activate India authority',
                  'ACTIVE': 'Clean next 8 source rows', 'CLEANUP': 'Clean next 8 source rows',
                  'COMPLETE': 'Live migration complete'}
        expect(page.locator('#next')).to_have_text(labels[current['phase']])

    visit('/')
    for route in ['/design/index.html', '/design/adr-register.html', '/design/development-lab.html']:
        visit(route)
        expect(page.locator('h1')).to_be_visible()
    visit('/monitor.html#services')
    expect(page.locator('#connection')).to_have_text('Live local runtime', timeout=30000)
    expect(page.locator('h1')).to_have_text('Business services lab')
    visit('/monitor.html#generator')
    expect(page.locator('#connection')).to_have_text('Live local runtime', timeout=30000)
    page.locator('#scenario').select_option('sg-uk-no-us')
    page.locator('#count').fill('1')
    with page.expect_response(lambda r: r.url == base + '/api/generate' and r.request.method == 'POST') as generated:
        page.locator('#generate').click()
    assert generated.value.status == 200
    created = generated.value.json()['created']
    assert len(created) == 1
    rid = created[0]['id']
    deadline = time.monotonic() + 45
    while True:
        current = page.request.get(base + '/api/state').json()
        assert current['mode'] == 'live' and all(s['online'] for s in current['stores'])
        copies = [r for s in current['stores'] for r in s['replicas'] if r['record_id'] == rid]
        if not any(q['record_id'] == rid for q in current['queue']):
            assert len(copies) == 1 and copies[0]['destination_entity_id'] == 'LE-GB-02'
            break
        assert time.monotonic() < deadline, 'Generated record did not settle'
        time.sleep(.2)
    visit('/monitor.html#monitor')
    expect(page.locator('#connection')).to_have_text('Live local runtime', timeout=30000)
    page.locator('[data-select="' + rid + '"]').first.click()
    expect(page.locator('.dispatch-list')).to_contain_text('REPLICATED', timeout=15000)
    page.screenshot(path=str(out / 'monitor-movement.png'), full_page=True)
    print('PASS live browser generator, new monitor record and acknowledged SG-to-UK movement; US absent', flush=True)

    visit('/migration.html')
    expect(page.locator('#connection')).to_have_text('persistent-cockroach', timeout=30000)
    action('#reset', 'reset')
    expect(page.locator('#next')).to_have_text('Register Mumbai store')
    for suffix in ['register', 'plan', 'start', 'copy']:
        action('#next', suffix)
    for kind in ['create', 'update', 'delete']:
        action('[data-write="' + kind + '"]', 'write')
    while state()['phase'] == 'COPYING':
        action('#next', 'copy')
    while state()['delta_lag']:
        action('#next', 'catchup')
    action('#next', 'validate')
    expect(page.locator('#next')).to_have_text('Fence Singapore writer')
    page.screenshot(path=str(out / 'migration-validated.png'), full_page=True)
    action('[data-write="update"]', 'write')
    assert state()['phase'] == 'CATCHING_UP'
    while state()['delta_lag']:
        action('#next', 'catchup')
    action('#next', 'validate')
    action('#next', 'fence')
    action('[data-write="update"]', 'write', 409)
    action('#other', 'other')
    action('#next', 'activate')
    action('#oldwrite', 'write', 409)
    expect(page.locator('.migration-message').first).to_have_class(re.compile('error'))
    action('[data-write="update"]', 'write')
    while state()['phase'] != 'COMPLETE':
        action('#next', 'cleanup')
    assert state()['home'] == 'IN'
    page.screenshot(path=str(out / 'migration-complete.png'), full_page=True)
    print('PASS live browser snapshot, concurrent changes, validation invalidation, fence, UK work, cutover, stale-write rejection and cleanup', flush=True)

    for width in [375, 768, 1440]:
        page.set_viewport_size({'width': width, 'height': 1000})
        visit('/monitor.html#monitor')
        expect(page.locator('#connection')).to_have_text('Live local runtime', timeout=30000)
        page.screenshot(path=str(out / f'monitor-{width}.png'), full_page=True)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    visit('/grafana/d/sovereign-logs')
    expect(page.get_by_text('API and worker events', exact=True)).to_be_visible(timeout=30000)
    expect(page.get_by_text(re.compile('http.request.completed')).first).to_be_visible(timeout=45000)
    page.screenshot(path=str(out / 'grafana.png'), full_page=True)
    assert not errors, errors
    print('PASS rendered monitor at 375/768/1440px, architecture navigation and Grafana dashboard; no module or page errors', flush=True)
    browser.close()
