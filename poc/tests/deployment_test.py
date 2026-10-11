"""Regression for internal HTTP traffic on hosts with inherited proxy defaults."""
import json
import os
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import requests


class ProxyBypassTests(unittest.TestCase):
    def test_internal_traffic_does_not_use_inherited_proxy(self):
        services = json.loads((Path(__file__).resolve().parents[2] / 'compose.yaml').read_text())['services']
        targets = {
            'monitor': ['gateway:8080', 'otel-collector:4318', 'opa-sg:8181', '127.0.0.1:8000'],
            'tools': ['gateway:8080'],
            'otel-collector': ['loki:3100'],
            'grafana': ['loki:3100'],
        }
        inherited = {
            'HTTP_PROXY': 'http://outbound-proxy.invalid:8080',
            'http_proxy': 'http://outbound-proxy.invalid:8080',
            'NO_PROXY': 'external.invalid', 'no_proxy': 'external.invalid',
        }
        for service, hosts in targets.items():
            with self.subTest(service=service), patch.dict(os.environ, inherited, clear=True):
                os.environ.update(services[service]['environment'])
                for host in hosts:
                    self.assertTrue(urllib.request.proxy_bypass(host), (service, host))
                    self.assertEqual(requests.utils.get_environ_proxies('http://' + host), {})
                self.assertTrue(requests.utils.get_environ_proxies('http://external.example'))


if __name__ == '__main__':
    unittest.main()
