"""Queue fresh source-authorised intents for legacy/persisted pilot projections.

This operator action never reads recipient payloads or manufactures a receipt.
The ordinary source policy and recipient admission paths perform each delivery.
"""
import argparse
import json
import os
import time
import uuid

import psycopg
from psycopg.errors import SerializationFailure
from psycopg.types.json import Jsonb

import operational_core as core
from seed import ENTITIES
from deployment import enabled_store_ids


PENDING_LOOKUP_SQL = (
    'SELECT 1 FROM sovereignty.outbox@{FORCE_INDEX=outbox_pending_scope_destination,NO_FULL_SCAN} '
    "WHERE scope_id=%s AND destination_entity_id=%s AND status IN ('queued','retry') LIMIT 1")
ENQUEUE_INTENT_SQL = (
    'INSERT INTO sovereignty.outbox (id,scope_id,destination_entity_id,created_at) '
    'SELECT %s,%s,%s,%s WHERE NOT EXISTS (' + PENDING_LOOKUP_SQL + ') RETURNING id')


def enqueue_page(connection, after=None, limit=10, through=None):
    """One bounded SQL transaction; caller commits queue and audit together.

    The primary-key cursor bounds work independently of total owner rows. Existing
    pending work is retained: relay conflict recovery renews a consumed event.
    """
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('Reconciliation page size must be between 1 and 50')
    owner = core.SPEC['owner_entity_id']
    rows = connection.execute(
        'SELECT id,doc FROM sovereignty.scope WHERE owner_entity_id=%s '
        'AND (%s::UUID IS NULL OR id>%s::UUID) '
        'AND (%s::UUID IS NULL OR id<=%s::UUID) ORDER BY id LIMIT %s',
        (owner, after, after, through, through, limit)).fetchall()
    pending = []
    with connection.pipeline():
        for sid, scope in rows:
            policy = scope['policy']
            destinations = sorted(set(policy['allowed_entities']) | set(policy['denied_entities']) |
                                  set(policy['grants']) | set(scope['contacted']))
            if any(destination not in ENTITIES for destination in destinations):
                raise ValueError('Unknown reconciliation destination')
            for destination in destinations:
                event, now = str(uuid.uuid4()), time.time()
                cursor = connection.execute(ENQUEUE_INTENT_SQL, (event, sid, destination, now, sid, destination))
                pending.append((cursor, str(sid), destination, now))
    queued = 0
    with connection.pipeline():
        for cursor, sid, destination, now in pending:
            if cursor.fetchone() is None:
                continue
            queued += 1
            event = dict(id=str(uuid.uuid4()), time=now, record_id=sid, owner_entity_id=owner,
                         destination_entity_id=destination, status='protocol_reconcile',
                         dataset='party_relationship_graph',
                         reason='Fresh current-state delivery requested; authority admission still required')
            connection.execute('INSERT INTO sovereignty.audit VALUES (%s,%s,%s)',
                               (event['id'], now, Jsonb(event)))
    return dict(after=str(rows[-1][0]) if rows else after, examined=len(rows), queued=queued)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn-env', default='PILOT_OWNER_DSN')
    parser.add_argument('--batch-size', type=int, default=10)
    parser.add_argument('--wait-active', type=int, default=0,
                        help='Wait up to this many seconds for startup intents to active stores')
    args = parser.parse_args()
    dsn = os.getenv(args.dsn_env)
    if not dsn:
        parser.error('The selected database environment variable is required')
    if not 1 <= args.batch_size <= 50:
        parser.error('Batch size must be between 1 and 50')
    if not 0 <= args.wait_active <= 600:
        parser.error('Active reconciliation wait must be between 0 and 600 seconds')
    after, examined, queued = None, 0, 0
    with psycopg.connect(dsn, connect_timeout=3) as connection:
        last = connection.execute('SELECT id FROM sovereignty.scope WHERE owner_entity_id=%s ORDER BY id DESC LIMIT 1',
                                  (core.SPEC['owner_entity_id'],)).fetchone()
        through = last[0] if last else None
    if through is not None:
        while True:
            for attempt in range(3):
                try:
                    with psycopg.connect(dsn, connect_timeout=3) as connection:
                        page = enqueue_page(connection, after, args.batch_size, through)
                    break
                except SerializationFailure:
                    if attempt == 2:
                        raise
            after = page['after']; examined += page['examined']; queued += page['queued']
            if page['examined'] < args.batch_size:
                break
    if args.wait_active:
        cutoff, deadline = time.time(), time.monotonic() + args.wait_active
        destinations = [entity['id'] for entity in ENTITIES.values()
                        if entity['store_id'] in enabled_store_ids()]
        while True:
            with psycopg.connect(dsn, connect_timeout=3) as connection:
                pending = connection.execute(
                    "SELECT count(*) FROM sovereignty.outbox WHERE status IN ('queued','retry') "
                    'AND destination_entity_id=ANY(%s) AND created_at<=%s',
                    (destinations, cutoff)).fetchone()[0]
            if pending == 0:
                break
            if time.monotonic() >= deadline:
                raise SystemExit('Active startup reconciliation is still pending; startup did not complete. Check peers and policies, then retry.')
            time.sleep(1)
    print(json.dumps(dict(scopes_examined=examined, intents_queued=queued, complete=True,
                         active_startup_drained=bool(args.wait_active))))


if __name__ == '__main__':
    try:
        main()
    except (psycopg.Error, ValueError):
        # SQL exception strings can contain connection details or business facts.
        raise SystemExit('Reconciliation failed; no success receipt was issued. Retry from the beginning.')
