"""Small local-transaction contract for an independently owned business schema.

The callback owns business semantics. This adapter owns only aggregate versions,
current-state intent, an uncoalesced transition ledger, audit and replay receipts.
No HTTP, broker or coordinator call runs inside the transaction/retry closure.
"""
import re
import time
import uuid

from fastapi import HTTPException
from psycopg import sql
from psycopg.errors import SerializationFailure
from psycopg.types.json import Jsonb

from pilot_common import digest


class LocalTransaction:
    def __init__(self, connect, schema, service):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,40}', schema):
            raise ValueError('Invalid fixed service schema')
        self.connect, self.schema, self.service = connect, schema, service

    def table(self, name):
        return sql.Identifier(self.schema, name)

    def execute(self, *, owner, aggregate, actor, request_id, operation, body,
                expected_version, authorize, mutate):
        """Authorize anew before each SQL attempt; mutation must be local SQL only.

        `authorize` returns bounded provenance, not a claim that remote rights
        cannot change during a local commit. Production authority/fencing is a
        separate contract. Aggregate identity and owner cannot change on retry.
        """
        fingerprint = digest(dict(service=self.service, owner=owner, aggregate=aggregate,
                                  actor=actor, operation=operation,
                                  expected_version=expected_version, body=body))
        key = (self.service, owner, aggregate)
        receipt_key = (self.service, owner, actor, request_id)
        for attempt in range(3):
            proof = authorize()  # Remote policy/MDM checks are outside the SQL unit of work.
            try:
                with self.connect() as connection:
                    prior = connection.execute(sql.SQL('SELECT request_hash,result FROM {} '
                        'WHERE service_id=%s AND owner_entity_id=%s AND actor_id=%s AND request_id=%s')
                        .format(self.table('request_receipt')), receipt_key).fetchone()
                    if prior:
                        if prior[0] != fingerprint:
                            raise HTTPException(409, 'Request ID reused with different input')
                        return {**prior[1], 'idempotent_replay': True}
                    row = connection.execute(sql.SQL('SELECT data_version FROM {} '
                        'WHERE service_id=%s AND owner_entity_id=%s AND aggregate_id=%s FOR UPDATE')
                        .format(self.table('aggregate_version')), key).fetchone()
                    version = row[0] if row else 0
                    if version != expected_version:
                        raise HTTPException(409, 'Stale service aggregate version')
                    version += 1
                    result = mutate(connection, version)
                    connection.execute(sql.SQL('UPSERT INTO {} VALUES (%s,%s,%s,%s)')
                        .format(self.table('aggregate_version')), key + (version,))
                    event_id = str(uuid.uuid4())
                    connection.execute(sql.SQL('INSERT INTO {} '
                        '(event_id,service_id,owner_entity_id,aggregate_id,data_version,intent_kind) '
                        'VALUES (%s,%s,%s,%s,%s,%s)').format(self.table('state_outbox')),
                        (event_id,) + key + (version, 'current_state'))
                    # Consumers needing every business transition use this distinct
                    # ledger. A latest-state relay must never coalesce this table.
                    connection.execute(sql.SQL('INSERT INTO {} '
                        '(event_id,service_id,owner_entity_id,aggregate_id,data_version,operation) '
                        'VALUES (%s,%s,%s,%s,%s,%s)').format(self.table('transition_event')),
                        (event_id,) + key + (version, operation))
                    connection.execute(sql.SQL('INSERT INTO {} '
                        '(event_id,service_id,owner_entity_id,aggregate_id,data_version,actor_id,request_id,operation,authority_observation) '
                        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)').format(self.table('transaction_audit')),
                        (event_id,) + key + (version, actor, request_id, operation, Jsonb(proof)))
                    receipt = {**result, 'request_id': request_id, 'data_version': version,
                               'idempotent_replay': False}
                    connection.execute(sql.SQL('INSERT INTO {} VALUES (%s,%s,%s,%s,%s,%s)')
                        .format(self.table('request_receipt')), receipt_key + (fingerprint, Jsonb(receipt)))
                return receipt
            except SerializationFailure:
                if attempt == 2:
                    raise HTTPException(503, 'Transaction contention; retry the same request ID')
                time.sleep(.02 * (attempt + 1))
