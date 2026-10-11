"""Probe retry/timeout unit tests; real OPA recovery is exercised by ./lab faults."""
import io
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from health_probe import wait_ready


class ReadinessProbeTests(unittest.TestCase):
    def test_starting_policy_is_retried_until_ready(self):
        starting = urllib.error.HTTPError('http://localhost', 503, 'not-ready', {}, None)
        ready = io.BytesIO(b'{"status":"ready","database":"cockroach"}')
        with patch('health_probe.urllib.request.urlopen', side_effect=[starting, ready]) as request, \
             patch('health_probe.time.sleep') as sleep:
            wait_ready(45)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once()

    def test_unavailable_policy_fails_at_deadline(self):
        with patch('health_probe.urllib.request.urlopen', side_effect=urllib.error.URLError('starting')), \
             patch('health_probe.time.monotonic', side_effect=[0, 0, 46]), \
             patch('health_probe.time.sleep') as sleep:
            with self.assertRaisesRegex(SystemExit, 'timeout'):
                wait_ready(45)
        sleep.assert_not_called()

    def test_default_probe_does_not_retry_or_accept_wrong_database(self):
        with patch('health_probe.urllib.request.urlopen', return_value=io.BytesIO(
                b'{"status":"ready","database":"sqlite"}')), \
             patch('health_probe.time.sleep') as sleep:
            with self.assertRaises(SystemExit):
                wait_ready()
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
