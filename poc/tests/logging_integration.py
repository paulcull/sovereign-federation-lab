"""Container gate: API-generated trace ID must be found in Loki via OTLP.

No direct log injection: verifies the deployed API → Collector → Loki path.
Also verifies gateway → Grafana and provisioned data source/dashboard.
"""
import json
import os
import time
import httpx

base = os.getenv('POC_URL', 'http://gateway:8080').rstrip('/')
with httpx.Client(timeout=10, trust_env=False) as client:
    response = client.get(base + '/api/health/live')
    response.raise_for_status()
    trace_id = response.headers['x-trace-id']
    query = '{service_name="sovereign-poc-harness"} | json | trace_id="' + trace_id + '"'
    matched = False
    for attempt in range(45):
        try:
            result = client.get('http://loki:3100/loki/api/v1/query_range',
                params={'query': query, 'since': '5m', 'limit': 20})
            result.raise_for_status()
            entries = [json.loads(v[1]) for stream in result.json()['data']['result'] for v in stream['values']]
            if any(e.get('trace_id') == trace_id and e.get('route') == '/api/health/live' and e.get('status') == 200 for e in entries):
                matched = True; break
        except (httpx.HTTPError, KeyError, ValueError): pass
        time.sleep(1)
    assert matched, 'API request log did not arrive in Loki through the Collector'
    health = client.get(base + '/grafana/api/health'); health.raise_for_status()
    assert health.json()['database'] == 'ok'
    datasource = client.get(base + '/grafana/api/datasources/uid/sovereign-loki')
    datasource.raise_for_status(); assert datasource.json()['type'] == 'loki'
    dashboard = client.get(base + '/grafana/api/dashboards/uid/sovereign-logs')
    dashboard.raise_for_status(); assert len(dashboard.json()['dashboard']['panels']) == 2
print('PASS API → OTLP → Loki trace-correlated log, Grafana gateway and provisioning')
