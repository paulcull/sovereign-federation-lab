"""Optional UK peer dataset router for independently owned servicing cases.

POST refresh explicitly materializes a source-approved current view. GET never
refreshes implicitly: it requires fresh source admission and a matching committed
projection. No background publisher, offline lease or every-transition promise.
"""
import os
import time

from fastapi import APIRouter, Header, HTTPException
import psycopg
from psycopg.errors import SerializationFailure
from psycopg.types.json import Jsonb

from pilot_common import authenticated, digest, live_configuration, remote, uuid_text
from servicing_policy import decide, FIELDS


def install_servicing_peer(app, config, http):
    if config.get('store_id') != 'STORE-GB-01' or not config.get('servicing_url'):
        return
    dsn = os.getenv('SERVICING_PROJECTION_DSN', 'postgresql://sfl_case_projection@db-uk:26257/defaultdb?sslmode=disable')
    opa = os.getenv('PILOT_OPA', 'http://opa-uk:8181')
    router = APIRouter(prefix='/service/experience/v1/cases', tags=['Independent case projections'])

    def connect():
        return psycopg.connect(dsn, connect_timeout=3, options='-c statement_timeout=5000')

    def current(case_id, authorization, action):
        case_id = uuid_text(case_id)
        cfg = live_configuration(config)
        _, principal = authenticated(authorization, cfg['servicing_principals'])
        if cfg.get('deployment', {}).get('processing_countries') != ['GB']:
            raise HTTPException(503, 'Case recipient placement not approved')
        if action not in principal['actions'] or principal['entity_id'] != 'LE-GB-02' or principal['processing_country'] != 'GB':
            raise HTTPException(403, 'Case recipient not delegated')
        recipient = dict(entity_id=principal['entity_id'], processing_country=principal['processing_country'], actions=['case.import'])
        decision = decide(opa, 'case.import', recipient, 'GB')
        envelope = remote(http, 'GET', cfg['servicing_url'] + '/service/internal/v1/cases/' + case_id + '/export', cfg['servicing_token'])
        row = envelope.get('row', {})
        if (envelope.get('contract') != 'servicing-case-state-v1' or envelope.get('owner_entity_id') != 'LE-SG-01'
                or envelope.get('destination_entity_id') != principal['entity_id']
                or set(row) != FIELDS or set(row) != set(decision['fields']) or row['case_id'] != case_id
                or type(row['data_version']) is not int or row['data_version'] < 1
                or row['status'] not in ('OPEN', 'CLOSED') or row['category'] not in ('CONTACT_REVIEW', 'DOCUMENT_REVIEW')
                or type(envelope.get('policy_revision')) is not int or envelope['policy_revision'] != decision['revision']):
            raise HTTPException(409, 'Compatible source and recipient contract not ready')
        return cfg, envelope, ('LE-SG-01', case_id, 'LE-GB-02')

    @router.post('/{case_id}/refresh')
    def refresh(case_id: str, authorization: str | None = Header(None)):
        for attempt in range(3):
            cfg, envelope, key = current(case_id, authorization, 'case.refresh')
            row = envelope['row']
            metadata = (row['data_version'], envelope['policy_revision'], digest(row))
            try:
                with connect() as connection:
                    prior = connection.execute('SELECT data_version,policy_revision,payload_hash FROM servicing_projection.case_state '
                        'WHERE owner_entity_id=%s AND case_id=%s AND destination_entity_id=%s FOR UPDATE', key).fetchone()
                    if prior and (prior[0] > metadata[0] or prior[1] > metadata[1]):
                        raise HTTPException(409, 'Older case projection fenced')
                    # Policy revisions can change admission, but the fixed four-field
                    # contract cannot change content without a new business version.
                    if prior and prior[0] == metadata[0] and prior[2] != metadata[2]:
                        raise HTTPException(409, 'Case version reused with different content')
                    connection.execute('UPSERT INTO servicing_projection.case_state VALUES (%s,%s,%s,%s,%s,%s,%s)',
                        key + metadata + (Jsonb(row),))
                    for table in ('inbox', 'import_audit'):
                        connection.execute('INSERT INTO servicing_projection.' + table + ' '
                            '(owner_entity_id,case_id,destination_entity_id,data_version,policy_revision,payload_hash) '
                            'VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING', key + metadata)
                break
            except SerializationFailure:
                if attempt == 2:
                    raise HTTPException(503, 'Projection contention; retry refresh')
                time.sleep(.02 * (attempt + 1))
        # Commit happens before source acknowledgement. An unavailable ack leaves
        # source intent pending; repeated refresh safely retries it.
        remote(http, 'POST', cfg['servicing_url'] + '/service/internal/v1/cases/' + key[1] + '/ack',
               cfg['servicing_token'], {'data_version': row['data_version']})
        return dict(served_from='servicing_projection', owner_entity_id=key[0], destination_entity_id=key[2], row=row)

    @router.get('/{case_id}')
    def read(case_id: str, authorization: str | None = Header(None)):
        _, envelope, key = current(case_id, authorization, 'case.read')
        with connect() as connection:
            stored = connection.execute('SELECT data_version,policy_revision,payload_hash,row_data '
                'FROM servicing_projection.case_state WHERE owner_entity_id=%s AND case_id=%s AND destination_entity_id=%s', key).fetchone()
        expected = envelope['row']
        if not stored or stored[0] != expected['data_version'] or stored[1] != envelope['policy_revision'] or stored[2] != digest(expected) or stored[3] != expected:
            raise HTTPException(409, 'Explicit case refresh required')
        return dict(served_from='servicing_projection', owner_entity_id=key[0], destination_entity_id=key[2], row=stored[3])

    app.include_router(router)
