"""Real CockroachDB projection ordering, replay and rollback regressions.

Run in the tools container after pilot-up, sequentially with mutable acceptance.
The SQL cases exercise the local transaction boundary, not source OPA approval.
The final case exercises real HTTP source/peer recovery from a consumed intent.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import sys
from threading import Barrier
import time
import uuid

from fastapi import HTTPException
import httpx
import psycopg
from psycopg.errors import DivisionByZero, SerializationFailure

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'poc'))
import operational_core as core
from pilot_projection import apply_projection
from pilot_protocol import PROTOCOL_VERSION, verify_projection_authority

DSN = os.getenv('PILOT_PROTOCOL_DSN', 'postgresql://root@db-uk:26257/defaultdb?sslmode=disable')
SCOPE, PARTY, GLOBAL = (str(uuid.uuid4()) for _ in range(3))
KEY = (core.SPEC['owner_entity_id'], SCOPE, 'LE-GB-02')
EVENTS = []


def message(data=1, policy=1, decision=1, placement=1, source=1, purge=False):
    event = str(uuid.uuid4()); EVENTS.append(event)
    rows = [] if purge else [dict(table='party', row=dict(id=PARTY, global_party_id=GLOBAL, party_type='PERSON'))]
    return dict(protocol_version=PROTOCOL_VERSION, event_id=event, owner_entity_id=KEY[0],
                scope_id=SCOPE, destination_entity_id=KEY[2], scope_kind='party',
                data_version=data, policy_generation=policy, decision_revision=decision,
                placement_version=placement, source_placement_version=source,
                policy={}, rows=rows, facts=copy.deepcopy(rows), row_counts={} if purge else {'party': 1})


def sql(query, values=()):
    with psycopg.connect(DSN, connect_timeout=3) as connection:
        cursor = connection.execute(query, values)
        return cursor.fetchall() if cursor.description is not None else []


def apply(value):
    with psycopg.connect(DSN, connect_timeout=3) as connection:
        return apply_projection(connection, value)


def rejection(value, status=409):
    try:
        apply(value)
    except HTTPException as error:
        assert error.status_code == status
    else:
        raise AssertionError('Invalid or stale projection was accepted')
    assert not sql('SELECT event_id FROM sovereignty.inbox WHERE event_id=%s', (value['event_id'],))


def snapshot():
    return dict(
        manifest=sql('SELECT data_version,policy_generation,decision_revision,placement_version '
                     'FROM sovereignty.manifest WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s', KEY),
        rows=sql('SELECT id,global_party_id,party_type FROM projection.party '
                 'WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s', KEY),
        source=sql('SELECT source_placement_version FROM sovereignty.manifest_authority '
                   'WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s', KEY),
        audits=sql("SELECT count(*) FROM sovereignty.audit WHERE doc->>'record_id'=%s", (SCOPE,)))


try:
    for field, invalid in (('protocol_version', 2), ('protocol_version', True),
                           ('data_version', 0), ('policy_generation', 1.0),
                           ('decision_revision', -1), ('placement_version', True),
                           ('source_placement_version', 0), ('row_counts', {'party': 2})):
        value = message(); value[field] = invalid
        rejection(value, 422)
    value = message(); del value['protocol_version']; rejection(value, 422)
    value = message(); value['rows'] *= 2; value['facts'] *= 2; value['row_counts'] = {'party': 2}; rejection(value, 422)
    assert snapshot()['manifest'] == []
    print('PASS unsupported protocol, ambiguous revisions and malformed graph rejected before SQL mutation')

    original = message()
    assert apply(original) == 'replicated'
    committed = snapshot()
    assert apply(original) == 'duplicate'
    assert snapshot() == committed
    conflict = copy.deepcopy(original); conflict['data_version'] = 2
    try:
        apply(conflict)
    except HTTPException as error:
        assert error.status_code == 409 and error.detail == {'code': 'projection_receipt_conflict'}
    else:
        raise AssertionError('Consumed event accepted a different envelope')
    assert snapshot() == committed
    assert sql('SELECT protocol_version FROM sovereignty.import_receipt WHERE event_id=%s', (original['event_id'],)) == [(1,)]
    print('PASS exact duplicate returns its durable receipt; changed same-event envelope cannot mutate projection or audit')

    assert apply(message(data=2, placement=2, source=2)) == 'replicated'
    before = snapshot()
    for stale in (message(data=1, placement=2, source=2),
                  message(data=3, placement=1, source=2),
                  message(data=3, placement=2, source=1)):
        rejection(stale)
        assert snapshot() == before
    with psycopg.connect(DSN) as connection:
        verify_projection_authority(connection, KEY, {'source_placement_version': 2})
        try:
            verify_projection_authority(connection, KEY, {'source_placement_version': 3})
        except HTTPException as error:
            assert error.status_code == 409
        else:
            raise AssertionError('Read accepted a different source placement')
    print('PASS independent data, destination placement and source placement rollback fences; current-source read fence')

    assert apply(message(data=6, policy=4, decision=4, placement=2, source=2)) == 'replicated'
    before = snapshot()
    rejection(message(data=5, policy=3, decision=3, placement=2, source=2, purge=True))
    assert snapshot() == before
    assert apply(message(data=7, policy=5, decision=5, placement=2, source=2, purge=True)) == 'purged'
    assert snapshot()['rows'] == []
    rejection(message(data=6, policy=4, decision=4, placement=2, source=2))
    assert snapshot()['rows'] == []
    assert apply(message(data=8, policy=6, decision=6, placement=2, source=2)) == 'replicated'
    print('PASS delayed purge cannot erase a newer grant; delayed grant cannot resurrect a newer purge')

    before = snapshot(); aborted = message(data=9, policy=6, decision=6, placement=2, source=2, purge=True)
    try:
        with psycopg.connect(DSN) as connection:
            apply_projection(connection, aborted)
            connection.execute('SELECT 1/0')
    except DivisionByZero:
        pass
    else:
        raise AssertionError('Forced SQL transaction abort did not fail')
    assert snapshot() == before
    assert not sql('SELECT event_id FROM sovereignty.inbox WHERE event_id=%s', (aborted['event_id'],))
    assert not sql('SELECT event_id FROM sovereignty.import_receipt WHERE event_id=%s', (aborted['event_id'],))
    print('PASS failed local SQL transaction rolls back graph, both fences, inbox, envelope receipt and audit together')

    barrier = Barrier(2)
    def concurrent(value):
        barrier.wait(timeout=10)
        for attempt in range(3):
            try:
                return apply(value)
            except SerializationFailure:
                if attempt == 2:
                    raise
            except HTTPException as error:
                assert error.status_code == 409
                return 'fenced'
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(concurrent, [
            message(data=9, policy=6, decision=6, placement=2, source=2, purge=True),
            message(data=10, policy=6, decision=6, placement=2, source=2)]))
    assert outcomes[1] == 'replicated'
    assert snapshot()['manifest'][0][0] == 10 and snapshot()['rows']
    print('PASS overlapping CockroachDB transactions converge to the newer grant regardless of delayed purge order')

    legacy = message(data=11, policy=6, decision=6, placement=2, source=2)
    sql('INSERT INTO sovereignty.inbox VALUES (%s,%s)', (legacy['event_id'], time.time()))
    before = snapshot()
    try:
        apply(legacy)
    except HTTPException as error:
        assert error.status_code == 409 and error.detail == {'code': 'projection_receipt_conflict'}
    else:
        raise AssertionError('Legacy inbox was incorrectly treated as payload proof')
    assert snapshot() == before
    assert apply(message(data=11, policy=6, decision=6, placement=2, source=2)) == 'replicated'
    sql('DELETE FROM sovereignty.manifest_authority WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s', KEY)
    with psycopg.connect(DSN) as connection:
        try:
            verify_projection_authority(connection, KEY, {'source_placement_version': 2})
        except HTTPException as error:
            assert error.status_code == 409
        else:
            raise AssertionError('Missing source-placement proof was silently manufactured')
    print('PASS legacy inbox collision and missing source ledger fail closed until fresh authority reconciliation')
finally:
    # Only this test's random scope and event IDs are removed, in FK-safe order.
    with psycopg.connect(DSN) as connection:
        for table in reversed(core.ORDER):
            connection.execute(f'DELETE FROM projection.{table} WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s', KEY)
        for table in ('field_manifest', 'manifest_authority', 'manifest'):
            connection.execute(f'DELETE FROM sovereignty.{table} WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s', KEY)
        connection.execute('DELETE FROM sovereignty.import_receipt WHERE event_id=ANY(%s::UUID[])', (EVENTS,))
        connection.execute('DELETE FROM sovereignty.inbox WHERE event_id=ANY(%s::UUID[])', (EVENTS,))
        connection.execute("DELETE FROM sovereignty.audit WHERE doc->>'record_id'=%s", (SCOPE,))


# A real source intent whose old receiver inbox survived without the new hash
# must self-recover. This also covers a consumed event whose recomputed envelope
# conflicts after a lost acknowledgement: only that typed conflict renews it.
config = json.loads((ROOT / '.pilot/api/config.json').read_text())
client = httpx.Client(base_url=os.getenv('PILOT_URL', 'http://pilot-gateway:8080'), timeout=25, trust_env=False)
reference = 'SYN-PROTOCOL-' + uuid.uuid4().hex.upper()
response = client.put('/pilot/system/v1/customers/' + reference,
    headers={'Authorization': 'Bearer ' + config['principals']['crm-sg']['token']},
    json=dict(request_id=str(uuid.uuid4()), expected_version=0, display_name='Synthetic Protocol Recovery',
              party_type='PERSON', identity_profile='global_minimum'))
assert response.status_code == 200
sid = response.json()['party_scope_id']
owner_dsn = os.getenv('PILOT_OWNER_DSN', 'postgresql://root@db-sg:26257/defaultdb?sslmode=disable')
deadline = time.monotonic() + 45
while True:
    with psycopg.connect(owner_dsn) as connection:
        task = connection.execute("SELECT id FROM sovereignty.outbox WHERE scope_id=%s AND destination_entity_id='LE-GB-02' AND status='replicated' ORDER BY created_at DESC LIMIT 1", (sid,)).fetchone()
    if task:
        break
    assert time.monotonic() < deadline, 'Initial live protocol projection did not settle'
    time.sleep(.3)
with psycopg.connect(DSN) as connection:
    connection.execute('DELETE FROM sovereignty.import_receipt WHERE event_id=%s', (task[0],))
with psycopg.connect(owner_dsn) as connection:
    connection.execute("UPDATE sovereignty.outbox SET status='retry',reason='Synthetic consumed-intent recovery probe' WHERE id=%s", (task[0],))
deadline = time.monotonic() + 45
while True:
    with psycopg.connect(owner_dsn) as connection:
        old = connection.execute('SELECT status FROM sovereignty.outbox WHERE id=%s', (task[0],)).fetchone()[0]
        replacements = connection.execute("SELECT id,status FROM sovereignty.outbox WHERE scope_id=%s AND destination_entity_id='LE-GB-02' AND id!=%s", (sid, task[0])).fetchall()
        audits = connection.execute("SELECT count(*) FROM sovereignty.audit WHERE doc->>'record_id'=%s AND doc->>'status'='delivery_replanned'", (sid,)).fetchone()[0]
    if old == 'superseded' and len(replacements) == 1 and replacements[0][1] == 'replicated' and audits == 1:
        break
    assert time.monotonic() < deadline, 'Consumed-intent renewal did not converge exactly once'
    time.sleep(.3)
assert sql('SELECT protocol_version FROM sovereignty.import_receipt WHERE event_id=%s', (replacements[0][0],)) == [(1,)]
response = client.get('/pilot/experience/v1/relationships/' + sid,
    headers={'Authorization': 'Bearer ' + config['principals']['uk-servicing']['token']})
assert response.status_code == 200
print('PASS live HTTP receipt conflict retires old intent once, audits one replacement and re-authorises successful delivery')
