"""Read-only reader journey against the real gateway; no comprehension certification.

Requires the same Playwright/Chromium setup as poc/tests/browser_acceptance.py.
"""
import json
import os
from pathlib import Path
import shutil
from playwright.sync_api import sync_playwright, expect

base = os.getenv('POC_URL', 'http://127.0.0.1:8080').rstrip('/')
out = Path(os.getenv('READER_ARTIFACTS', 'artifacts/reader-guide'))
out.mkdir(parents=True, exist_ok=True)
journey = ['index', 'entity-model', 'operational-model', 'opa', 'federation',
           'architecture', 'entity-migration', 'pilot-plan']

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH') or shutil.which('chromium'),
                                headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    response = page.goto(base + '/', wait_until='domcontentloaded')
    assert response.status == 200
    page.get_by_role('link', name='Follow the reader guide').click()
    expect(page).to_have_url(base + '/design/index.html')
    expect(page.locator('#example')).to_contain_text('explicitly excludes the US')
    expect(page.locator('#example')).to_contain_text('Identity is a separate question')
    assert page.locator('main h2').first.inner_text() == 'Start with one person and one relationship'
    assert not page.locator('.engineer-prompt').get_attribute('open')
    page.screenshot(path=str(out / 'overview-desktop.png'), full_page=True)

    # Follow real links rather than constructing URLs for the guided path.
    for current, following in zip(journey, journey[1:]):
        expect(page).to_have_url(base + '/design/' + current + '.html')
        assert page.locator('.reading-links a').count() == (1 if current == 'index' else 2)
        next_link = page.locator('.reading-links a[rel="next"]')
        expect(next_link).to_have_attribute('href', following + '.html')
        next_link.click()
        expect(page).to_have_url(base + '/design/' + following + '.html')
        expect(page.locator('h1')).to_be_visible()
        expect(page.locator('.reading-links a[rel="prev"]')).to_have_attribute('href', current + '.html')

    # Every component retains an entry point and evidence labels; stale claims fail.
    index = page.request.get(base + '/design/design-index.json').json()
    for item in index:
        response = page.goto(base + '/design/' + item['slug'] + '.html', wait_until='domcontentloaded')
        assert response.status == 200
        text = page.locator('main').inner_text()
        assert 'database end-to-end execution is not verified' not in text, item['slug']
        assert 'controlled migration execution is deferred' not in text, item['slug']
        if item['slug'] != 'index':
            expect(page.locator('.reader-help a').first).to_have_attribute('href', 'index.html#reading-path')
            expect(page.locator('.reader-status summary')).to_be_visible()

    page.goto(base + '/design/entity-model.html')
    page.get_by_role('link', name='Look up a term').click()
    expect(page).to_have_url(base + '/design/index.html#glossary')
    expect(page.locator('#glossary')).to_contain_text('Cutover')
    page.locator('#status').scroll_into_view_if_needed()
    expect(page.locator('#status')).to_contain_text('erasure from backups')
    evidence = page.get_by_role('link', name='Read the executed acceptance evidence')
    assert page.request.get(base + evidence.get_attribute('href')).status == 200

    for width in [375, 768, 1440]:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.goto(base + '/design/index.html', wait_until='domcontentloaded')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
        if width == 375:
            page.locator('#menu-toggle').click()
            expect(page.locator('#menu-toggle')).to_have_attribute('aria-expanded', 'true')
            page.locator('#sidebar a[data-page="entity-model"]').click()
            expect(page).to_have_url(base + '/design/entity-model.html')
            page.goto(base + '/design/index.html')
        page.screenshot(path=str(out / ('overview-' + str(width) + '.png')), full_page=True)
    page.locator('.engineer-prompt > summary').click()
    expect(page.locator('.copy-prompt')).to_be_visible()
    assert not errors, errors
    browser.close()
    print('PASS real-gateway reader path, previous/next, glossary, evidence, 28 pages, mobile navigation and bounded layout checks; no page errors')
