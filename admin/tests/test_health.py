import http.server
import json
import threading
import time
import unittest

from admin.health import GatewayObserver, HealthState, Observation, ObservationError
from admin.registry import initial


def response(ready=True):
    return {'database': 'cockroach', 'status': 'ready' if ready else 'not-ready',
            'footprint': 'mdm-compact', 'stores': [
                {'region': 'SG', 'database': True, 'policy': True},
                {'region': 'UK', 'database': True, 'policy': ready}]}


class HealthTests(unittest.TestCase):
    def setUp(self):
        owner = self
        self.reply, self.status, self.content_type = response(), 200, 'application/json'
        self.redirect = False
        self.trickle = None
        self.disconnected = threading.Event()
        self.paths = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):pass
            def do_GET(self):
                owner.paths.append(self.path)
                trickle = owner.trickle
                if trickle:
                    try:
                        if trickle == 'headers':
                            self.connection.sendall(b'HTTP/1.1 200 OK\r\n')
                        else:
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                        for _ in range(50):
                            self.connection.sendall(b'X-Drip: x\r\n' if trickle == 'headers' else b' ')
                            time.sleep(.06)
                    except (BrokenPipeError, ConnectionResetError):
                        owner.disconnected.set()
                    return
                self.send_response(302 if owner.redirect else owner.status)
                self.send_header('Content-Type', owner.content_type)
                if owner.redirect:self.send_header('Location', 'http://example.invalid/private-canary')
                self.end_headers()
                self.wfile.write(json.dumps(owner.reply).encode())
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.observer = GatewayObserver('http://127.0.0.1:' + str(self.server.server_port))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_valid_partial_503_and_recovery_are_observations(self):
        self.assertTrue(self.observer.poll().available)
        self.reply, self.status = response(False), 503
        observation = self.observer.poll()
        self.assertTrue(observation.available)
        health = HealthState()
        health.record(observation)
        self.assertEqual(health.snapshot(initial()['stores'])['stores'][1]['status'], 'Degraded')
        self.reply, self.status = response(), 200
        health.record(self.observer.poll())
        self.assertEqual(health.snapshot(initial()['stores'])['stores'][1]['status'], 'SQL + OPA healthy')
        self.assertEqual(set(self.paths), {'/api/health/ready'})

    def test_redirect_invalid_schema_inconsistent_status_and_oversize_fail_closed(self):
        self.redirect = True
        self.assertEqual(self.observer.poll().error, 'gateway_redirect_rejected')
        self.assertEqual(len(self.paths), 1)
        self.redirect = False
        for reply, status in ((response(False), 200), (response(), 503), ([], 200), ({**response(), 'database': 'sqlite'}, 200),
                              ({**response(), 'stores': response()['stores'] * 2}, 200), ({'canary': 'x' * 132000}, 200)):
            self.reply, self.status = reply, status
            self.assertFalse(self.observer.poll().available)
        self.reply, self.content_type = response(), 'text/html'
        self.assertFalse(self.observer.poll().available)

    def test_gateway_address_is_loopback_only_and_has_no_credentials(self):
        for url in ('http://example.com', 'http://127.0.0.1@evil.example', 'http://user:secret@127.0.0.1',
                    'http://127.0.0.1/?secret=canary', 'file:///etc/passwd', 'http://127.0.0.1/private'):
            with self.assertRaises(ObservationError):GatewayObserver(url)

    def test_total_deadline_kills_and_reaps_trickling_headers_and_body(self):
        self.observer.timeout = .8
        for kind in ['headers', 'body']:
            self.trickle = kind
            self.disconnected.clear()
            started = time.monotonic()
            result = self.observer.poll()
            self.assertEqual(result.error, 'gateway_deadline_exceeded')
            self.assertFalse(result.available)
            self.assertLess(time.monotonic() - started, 2)
            self.assertTrue(self.disconnected.wait(2), 'Timed-out probe retained its connection')
            self.trickle = None
            self.assertTrue(self.observer.poll().available, 'A subsequent refresh must recover')

    def test_failure_age_and_out_of_order_success_never_preserve_false_healthy(self):
        health = HealthState(max_age=30)
        good = Observation(100, True, footprint='mdm-compact', regions={'SG': {'database': True, 'policy': True}, 'UK': {'database': True, 'policy': True}})
        health.record(good)
        self.assertTrue(health.snapshot(initial()['stores'], now=110)['current'])
        self.assertFalse(health.snapshot(initial()['stores'], now=131)['current'])
        health.record(Observation(120, False, error='gateway_unavailable'))
        health.record(Observation(110, True, regions=good.regions))
        snapshot = health.snapshot(initial()['stores'], now=125)
        self.assertFalse(snapshot['current'])
        self.assertEqual(snapshot['stores'][0]['status'], 'Unknown / stale')

    def test_new_country_or_same_country_store_cannot_inherit_existing_health(self):
        health = HealthState()
        health.record(self.observer.poll())
        stores = initial()['stores'] + [{'id': 'STORE-DE-01', 'country': 'DE'}, {'id': 'STORE-SG-99', 'country': 'SG'}]
        snapshot = health.snapshot(stores)
        self.assertEqual(snapshot['stores'][2]['status'], 'Suspended (gateway report)')
        for row in snapshot['stores'][-2:]:
            self.assertEqual(row['status'], 'Backend unassigned')
            self.assertFalse(row['placement_ready'])
            self.assertIsNone(row['database'])


if __name__ == '__main__':unittest.main()
