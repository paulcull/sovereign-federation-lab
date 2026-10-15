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
                cursor = connection.execute(
                    'INSERT INTO sovereignty.outbox (id,scope_id,destination_entity_id,created_at) '
                    'SELECT %s,%s,%s,%s WHERE NOT EXISTS '
                    "(SELECT 1 FROM sovereignty.outbox WHERE scope_id=%s AND destination_entity_id=%s AND status IN ('queued','retry')) "
                    'RETURNING id', (event, sid, destination, now, sid, destination))
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
    args = parser.parse_args()
    dsn = os.getenv(args.dsn_env)
    if not dsn:
        parser.error('The selected database environment variable is required')
    if not 1 <= args.batch_size <= 50:
        parser.error('Batch size must be between 1 and 50')
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
    print(json.dumps(dict(scopes_examined=examined, intents_queued=queued, complete=True)))


if __name__ == '__main__':
    try:
        main()
    except (psycopg.Error, ValueError):
        # SQL exception strings can contain connection details or business facts.
        raise SystemExit('Reconciliation failed; no success receipt was issued. Retry from the beginning.')
