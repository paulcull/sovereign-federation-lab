"""Live cluster UX, real recovery progress, responsive layout and API outage UX."""
import os
from pathlib import Path
import shutil
from playwright.sync_api import expect, sync_playwright

OUT = Path(__file__).resolve().parents[2] / 'artifacts/cluster-control/browser'
OUT.mkdir(parents=True, exist_ok=True)
base = os.getenv('POC_URL', 'http://127.0.0.1:8080').rstrip('/')
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.getenv('CHROMIUM_PATH') or shutil.which('chromium'), headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1080})
    errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base + '/clusters/', wait_until='domcontentloaded')
    expect(page.get_by_role('heading', name='Database clusters', exact=True)).to_be_visible()
    expect(page.locator('.cluster-card')).to_have_count(4)
    expect(page.locator('#mode')).to_have_text('LIVE · COCKROACHDB')
    page.screenshot(path=str(OUT / 'fleet.png'), full_page=True)
    page.get_by_role('textbox', name='Search clusters').fill('Mumbai')
    expect(page.locator('.cluster-card')).to_have_count(1)
    page.get_by_role('textbox', name='Search clusters').fill('')
    page.get_by_role('button', name='Manage Singapore', exact=True).click()
    expect(page.get_by_role('heading', name='Cluster configuration')).to_be_visible()
    page.get_by_role('button', name='Nodes', exact=True).click()
    expect(page.get_by_role('cell', name='country=SG')).to_be_visible()
    page.screenshot(path=str(OUT / 'nodes.png'), full_page=True)
    # Lose the HTTP acknowledgement after the real API/SQL transaction commits.
    # Browser retry must reuse that request, rather than enqueue another job.
    attempts, receipts = [], []
    def lose_first_ack(route):
        if route.request.method != 'POST':
            route.continue_()
            return
        attempts.append(route.request.post_data_json['request_id'])
        if len(attempts) == 1:
            response = route.fetch()
            assert response.status == 202
            receipts.append(response.json()['id'])
            route.fulfill(status=503, content_type='application/json', body='{"detail":"Acceptance uncertain; retry with the same request identifier"}')
        else:
            route.continue_()
    page.route('**/api/cluster-control/clusters/sg/operations', lose_first_ack)
    page.get_by_role('button', name='Run health check', exact=True).click()
    expect(page.get_by_role('alert')).to_contain_text('same request identifier')
    page.get_by_role('button', name='Run health check', exact=True).click()
    expect(page.locator('.operation-card.selected')).to_have_attribute('data-job', receipts[0], timeout=30000)
    expect(page.locator('.operation-card.selected .status')).to_have_text('Succeeded', timeout=30000)
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert page.locator('.operation-card.selected').get_attribute('data-job') == receipts[0]
    page.unroute('**/api/cluster-control/clusters/sg/operations', lose_first_ack)
    # AbortError.message is read-only. Lose a real committed response in the
    # browser transport and ensure both the diagnostic and UUID retry survive.
    page.evaluate('''() => {
      window.originalControlFetch = window.fetch;
      window.abortAttempts = [];
      window.fetch = async (url, options) => {
        const response = await window.originalControlFetch(url, options);
        if (options?.method === 'POST' && url.endsWith('/sg/operations')) {
          window.abortAttempts.push(JSON.parse(options.body).request_id);
          if (window.abortAttempts.length === 1) {
            window.abortReceipt = await response.clone().json();
            throw new DOMException('Operation response lost', 'AbortError');
          }
        }
        return response;
      };
    }''')
    page.get_by_role('button', name='Run health check', exact=True).click()
    expect(page.get_by_role('alert')).to_contain_text('same request identifier')
    abort_receipt = page.evaluate('window.abortReceipt.id')
    page.get_by_role('button', name='Run health check', exact=True).click()
    expect(page.locator('.operation-card.selected')).to_have_attribute('data-job', abort_receipt, timeout=30000)
    expect(page.locator('.operation-card.selected .status')).to_have_text('Succeeded', timeout=30000)
    aborted = page.evaluate('window.abortAttempts')
    assert len(aborted) == 2 and aborted[0] == aborted[1]
    assert page.locator('.operation-card.selected').get_attribute('data-job') == abort_receipt
    page.evaluate('window.fetch = window.originalControlFetch')
    page.get_by_role('button', name='Recovery', exact=True).click()
    page.get_by_role('button', name='Run recovery rehearsal', exact=True).click()
    dialog = page.get_by_role('dialog'); expect(dialog).to_be_visible()
    page.locator('#confirm-cluster').fill('UK')
    page.get_by_role('button', name='Run rehearsal', exact=True).click()
    expect(page.locator('#dialog-error')).to_contain_text('Enter SG')
    page.locator('#confirm-cluster').fill('SG')
    page.screenshot(path=str(OUT / 'recovery-review.png'), full_page=True)
    page.get_by_role('button', name='Run rehearsal', exact=True).click()
    expect(dialog).not_to_be_visible(timeout=20000)
    expect(page.locator('.operation-card.selected .status')).to_have_text('Succeeded', timeout=65000)
    expect(page.locator('.operation-card.selected')).to_contain_text('verified three synthetic rows')
    page.screenshot(path=str(OUT / 'recovery-complete.png'), full_page=True)
    page.get_by_role('button', name='Recovery', exact=True).click()
    expect(page.get_by_text('Verified', exact=True)).to_be_visible()
    page.screenshot(path=str(OUT / 'recovery.png'), full_page=True)
    for width in (375, 768, 1440):
        page.set_viewport_size({'width': width, 'height': 1080})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('recovery', width)
        page.screenshot(path=str(OUT / f'recovery-{width}.png'), full_page=True)
    page.get_by_role('button', name='Environment', exact=True).click()
    expect(page.get_by_role('heading', name='Environment', exact=True)).to_be_visible()
    expect(page.get_by_role('heading', name='Supporting service checks')).to_be_visible()
    expect(page.get_by_text('1 shared development host', exact=True)).to_be_visible()
    page.screenshot(path=str(OUT / 'environment.png'), full_page=True)
    page.get_by_role('button', name='Clusters', exact=True).click()
    for width in (375, 768, 1440):
        page.set_viewport_size({'width': width, 'height': 1080})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('fleet', width)
        for name in ('Clusters', 'Operation history', 'Environment'):
            expect(page.get_by_role('button', name=name, exact=True)).to_be_visible()
        expect(page.get_by_role('link', name='Federation lab', exact=True)).to_be_visible()
        page.screenshot(path=str(OUT / f'fleet-{width}.png'), full_page=True)
    # All-journal transport loss exercises presentation; database pause coverage
    # remains in cluster-faults. Unknown persisted history must not look empty.
    page.route('**/api/cluster-control/clusters/*/operations', lambda route: route.fulfill(status=503))
    page.get_by_role('button', name='Refresh status', exact=True).click()
    page.get_by_role('button', name='Operation history', exact=True).click()
    expect(page.get_by_role('heading', name='Operation journal unavailable')).to_be_visible()
    expect(page.get_by_role('heading', name='No operations yet')).to_have_count(0)
    page.unroute('**/api/cluster-control/clusters/*/operations')
    page.get_by_role('button', name='Clusters', exact=True).click()
    # Transport failure checks the browser presentation, not business integration.
    page.route('**/api/cluster-control/clusters', lambda route: route.abort())
    page.get_by_role('button', name='Refresh status', exact=True).click()
    expect(page.get_by_role('heading', name='Live cluster status unavailable')).to_be_visible()
    expect(page.locator('.cluster-card')).to_have_count(0)
    page.unroute('**/api/cluster-control/clusters')
    page.get_by_role('button', name='Refresh status', exact=True).click()
    expect(page.locator('.cluster-card')).to_have_count(4)
    assert not errors, errors
    browser.close()
print('PASS live fleet UX, cluster/environment separation, native health/recovery, confirmation, durable results, responsive layouts and explicit API outage state')
