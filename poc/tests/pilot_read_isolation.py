"""Real HTTP concurrency gate; caller orchestrates a paused UK peer with a trap.

Run setup while healthy, paused while pilot-peer-uk is docker-paused, then
recovered after unpause. This file neither stops processes nor substitutes peers.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / '.pilot/api/config.json').read_text())
STATE = ROOT / 'artifacts/pilot/read-isolation.json'
BASE = os.getenv('PILOT_URL', 'http://pilot-gateway:8080')


def get(path, identity):
    with httpx.Client(base_url=BASE, timeout=25, trust_env=False) as client:
        start = time.monotonic()
        response = client.get(path, headers={
            'Authorization':'Bearer ' + CONFIG['principals'][identity]['token']})
        return response, time.monotonic()-start


def ready(path):
    deadline = time.monotonic()+45
    while time.monotonic() < deadline:
        response, elapsed = get(path, 'uk-servicing')
        if response.status_code == 200:
            return elapsed
        time.sleep(.3)
    raise AssertionError('UK projection did not become readable')


phase = sys.argv[1]
if phase == 'setup':
    with psycopg.connect(os.getenv('DB_SG', 'postgresql://root@db-sg:26257/defaultdb?sslmode=disable')) as connection:
        sid = str(connection.execute("SELECT id FROM sovereignty.scope WHERE owner_entity_id='LE-SG-01' "
            "AND doc->>'name'='Aster · Personal relationship'").fetchone()[0])
    path = '/pilot/experience/v1/relationships/' + sid
    ready(path)
    owner, baseline = get(path+'?freshness=owner', 'sg-owner')
    assert owner.status_code == 200
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(dict(path=path, baseline_owner_seconds=baseline,
                                    version=owner.json()['data_version'])))
    print('PASS read isolation fixture uses actual owner and current UK projection')
elif phase in ('paused','policy-paused'):
    state = json.loads(STATE.read_text())
    started = threading.Event()
    request_id = str(uuid.uuid4())
    def stalled():
        started.set()
        if phase == 'paused':
            return get(state['path'], 'uk-servicing')
        with httpx.Client(base_url=BASE, timeout=25, trust_env=False) as client:
            start=time.monotonic()
            response=client.post(state['path']+'/commands',json=dict(request_id=request_id,
                expected_version=state['version'],command='update_contact',value='isolation@example.invalid'),
                headers={'Authorization':'Bearer '+CONFIG['principals']['uk-servicing']['token']})
            return response,time.monotonic()-start
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(stalled)
        assert started.wait(2)
        time.sleep(.3)
        assert not future.done(), 'Peer is not paused or request failed before the peer hop'
        owner, duration = get(state['path']+'?freshness=owner', 'sg-owner')
        assert owner.status_code == 200, owner.status_code
        assert not future.done(), 'Unrelated owner read waited for the stalled peer'
        budget = 2 if phase == 'paused' else 1.5
        assert duration < budget, f'Owner read exceeded isolated {budget}-second budget: {duration:.2f}'
        failure, stalled_duration = future.result(timeout=20)
        assert failure.status_code == 503, failure.status_code
        assert stalled_duration >= (4 if phase == 'paused' else 1.8), 'Did not exercise the real dependency timeout'
    if phase == 'policy-paused':
        with psycopg.connect(os.getenv('DB_SG', 'postgresql://root@db-sg:26257/defaultdb?sslmode=disable')) as connection:
            assert connection.execute('SELECT count(*) FROM sovereignty.command_receipt WHERE request_id=%s',
                                      (request_id,)).fetchone()[0] == 0
    state[phase]=dict(owner_seconds=duration, stalled_dependency_seconds=stalled_duration)
    STATE.write_text(json.dumps(state))
    print(f'PASS {phase} failed closed in {stalled_duration:.2f}s; concurrent owner read '
          f'completed in {duration:.2f}s before dependency timeout (budget <{budget}s)')
elif phase == 'recovered':
    state = json.loads(STATE.read_text())
    ready(state['path'])
    print('PASS real peer recovered and returned a currently authorised projection')
else:
    raise AssertionError('Unknown read isolation phase')
