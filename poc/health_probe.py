"""Container health probe; no dependency on a shell/curl inside the API image."""
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready',timeout=10) as response:
    body=json.load(response)
    if body.get('status')!='ready' or body.get('database')!='cockroach':raise SystemExit(1)
