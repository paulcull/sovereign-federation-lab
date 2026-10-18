"""Independent authenticated system/experience API adapter or recipient peer.

Processes use private role-specific files and mutually authenticated TLS. The
existing business coordinator retains its atomic local transaction boundary.
"""
import json
import os
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
import psycopg
from fastapi import FastAPI, Header, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

import operational_core as core
from observability import ApplicationLogs, RequestTelemetry
from operational import clean
from pilot_common import (authenticated, configuration, digest, live_configuration,
                          remote, require_command, tls_client, uuid_text)
from pilot_projection import apply_projection
from pilot_protocol import validate_envelope, verify_projection_authority
from pilot_contracts import CustomerInput, RelationshipInput, BusinessCommand
from pilot_tracing import PilotTraceEvidence
from servicing_peer import install_servicing_peer
from seed import ENTITIES, STORE_INFO

CONFIG = configuration()
ROLE = CONFIG['role']
provider = TracerProvider(resource=Resource.create({'service.name': 'sovereign-pilot-' + ROLE}))
if os.getenv('LAB_TELEMETRY_ENABLED','1')=='1':
    provider.add_span_processor(BatchSpanProcessor(PilotTraceEvidence(ROLE, CONFIG.get('store_id','')),
                                                   schedule_delay_millis=1000))
if os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT'):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer('sovereign.pilot')
logs = ApplicationLogs('sovereign-pilot-' + ROLE)
HTTP = tls_client(CONFIG, timeout=20 if ROLE == 'api' else 5)
@asynccontextmanager
async def lifespan(app):
    logs.emit('service.started')
    try:
        yield
    finally:
        HTTP.close()
        logs.emit('service.stopped')
        logs.shutdown(); provider.shutdown()

app = FastAPI(title='Sovereign Pilot · ' + ROLE, lifespan=lifespan,
              docs_url='/pilot/api-docs', redoc_url=None)
class SafeErrors:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        except Exception:
            if scope['type'] != 'http':
                raise
            # Do not send raw SQL/transport exception text to clients or Uvicorn.
            response = JSONResponse(status_code=503, content={'detail': 'Required pilot dependency unavailable; fail closed'})
            await response(scope, receive, send)

app.add_middleware(SafeErrors)
app.add_middleware(RequestTelemetry, logs=logs, tracer=tracer)


@app.exception_handler(Exception)
async def unavailable(request: Request, error: Exception):
    return JSONResponse(status_code=503, content={'detail': 'Required pilot dependency unavailable; fail closed'})


@app.get('/healthz')
def health():
    return dict(status='alive', role=ROLE)


def bound(value):
    if len(json.dumps(value, separators=(',', ':')).encode()) > 32768:
        raise HTTPException(422, 'Pilot result exceeds 32 KiB; use a bounded view')
    return value


def principal(authorization):
    name, identity = authenticated(authorization, live_configuration(CONFIG)['principals'])
    return name, identity


def call_owner(endpoint, name, **body):
    config = live_configuration(CONFIG)
    return remote(HTTP, 'POST', config['authority_url'] + '/api/pilot/internal/' + endpoint,
                  config['authority_token'], dict(principal_id=name, **body))


if ROLE == 'api':
    @app.get('/pilot/api/v1/runtime')
    def runtime_status(authorization: str | None = Header(None)):
        name, identity = principal(authorization)
        result = call_owner('runtime', name)
        return JSONResponse(result, status_code=200 if result['status']=='ready' else 503)

    @app.get('/pilot/system/v1/customers', tags=['System APIs'])
    def system_directory(q: str = Query('', max_length=80), after: str = Query('', max_length=68),
                         limit: int = Query(25, ge=1, le=50), authorization: str | None = Header(None)):
        name, identity = principal(authorization)
        if 'system' not in identity['actions']:
            raise HTTPException(403, 'System authority required')
        return bound(call_owner('system', name, operation='directory', query=q, after=after, limit=limit))

    @app.get('/pilot/api/v1/context')
    def context(authorization: str | None = Header(None)):
        name, identity = principal(authorization)
        result = {k: identity[k] for k in ('entity_id', 'processing_country', 'actions',
                                          'command_grants', 'expires_at')}
        result['deployment_processing_countries'] = live_configuration(CONFIG)['deployment']['processing_countries']
        return result

    @app.get('/pilot/system/v1/customers/{reference}', tags=['System APIs'])
    def system_get(reference: str, authorization: str | None = Header(None)):
        name, identity = principal(authorization)
        if 'system' not in identity['actions']:
            raise HTTPException(403, 'System authority required')
        return call_owner('system', name, operation='get', reference=reference)

    @app.put('/pilot/system/v1/customers/{reference}', tags=['System APIs'])
    def system_upsert(reference: str, body: CustomerInput, authorization: str | None = Header(None)):
        name, identity = principal(authorization)
        if 'system' not in identity['actions']:
            raise HTTPException(403, 'System authority required')
        return call_owner('system', name, operation='upsert', reference=reference, payload=body.model_dump(mode='json'))

    @app.post('/pilot/system/v1/customers/{reference}/relationships', tags=['System APIs'])
    def system_relationship(reference: str, body: RelationshipInput, authorization: str | None = Header(None)):
        name, identity = principal(authorization)
        if 'system' not in identity['actions']:
            raise HTTPException(403, 'System authority required')
        return call_owner('system', name, operation='relationship', reference=reference, payload=body.model_dump(mode='json'))

    @app.get('/pilot/experience/v1/customers/{global_party_id}', tags=['Experience APIs'])
    def customer(global_party_id: str, freshness: str = 'projection', minimum_data_version: int = 0,
                 authorization: str | None = Header(None)):
        name, identity = principal(authorization)
        if 'read' not in identity['actions']:
            raise HTTPException(403, 'Read authority required')
        return bound(call_owner('experience', name, global_party_id=uuid_text(global_party_id),
                     freshness=freshness, minimum_data_version=minimum_data_version))

    @app.get('/pilot/experience/v1/relationships/{scope_id}', tags=['Experience APIs'])
    def relationship(scope_id: str, freshness: str = 'projection', minimum_data_version: int = 0,
                     authorization: str | None = Header(None)):
        name, identity = principal(authorization)
        if 'read' not in identity['actions']:
            raise HTTPException(403, 'Read authority required')
        return bound(call_owner('experience', name, scope_id=uuid_text(scope_id),
                     freshness=freshness, minimum_data_version=minimum_data_version))

    @app.post('/pilot/experience/v1/relationships/{scope_id}/commands', tags=['Experience APIs'])
    def business_command(scope_id: str, body: BusinessCommand, authorization: str | None = Header(None)):
        name, identity = principal(authorization)
        require_command(identity, body.model_dump(mode='json', exclude_none=True))
        return call_owner('command', name, scope_id=uuid_text(scope_id), payload=body.model_dump(mode='json', exclude_none=True))

elif ROLE == 'peer':
    def importing(authorization):
        config = live_configuration(CONFIG)
        authenticated(authorization, {'owner': config['import_credential']})

    def admission(body):
        config = live_configuration(CONFIG)
        return remote(HTTP, 'POST', config['authority_url'] + '/api/pilot/internal/admission',
                      config['authority_token'], body)

    def destination(entity):
        config = live_configuration(CONFIG)
        if entity not in ENTITIES or ENTITIES[entity]['store_id'] != config['store_id']:
            raise HTTPException(403, 'Recipient store binding rejected')
        return ENTITIES[entity]

    @app.get('/readyz')
    def ready():
        with psycopg.connect(os.environ['PILOT_DSN'], connect_timeout=2) as c:
            c.execute('SELECT 1 FROM sovereignty.manifest LIMIT 1')
        with httpx.Client(trust_env=False, timeout=2) as local:
            response = local.get(os.environ['PILOT_OPA'] + '/health')
            response.raise_for_status()
        return dict(status='ready', database='cockroach', store_id=CONFIG['store_id'])

    @app.post('/internal/import')
    def import_graph(message: dict, authorization: str | None = Header(None)):
        importing(authorization)
        validate_envelope(message)
        entity = destination(message.get('destination_entity_id'))
        uuid_text(message.get('event_id')); uuid_text(message.get('scope_id'))
        if message.get('owner_entity_id') != core.SPEC['owner_entity_id'] or message.get('scope_kind') not in ('party', 'relationship'):
            raise HTTPException(403, 'Unknown source or scope kind')
        rows = message.get('rows'); facts = message.get('facts')
        if not isinstance(rows, list) or not isinstance(facts, list) or len(rows) > 50 or len(facts) != len(rows):
            raise HTTPException(422, 'Invalid bounded graph')
        bound(message)
        for row, fact in zip(rows, facts):
            table = row.get('table'); data = row.get('row', {})
            columns = core.TABLES.get(table, {}).get('global_fields' if message['scope_kind'] == 'party' else 'export_fields', [])
            if not isinstance(data, dict) or set(data) - set(columns) or not data.get('id') or fact.get('table') != table or fact.get('row') != data:
                raise HTTPException(422, 'Invalid approved dataset or fields')
        admission(dict(operation='import', event_id=message['event_id'], scope_id=message['scope_id'],
                       destination_entity_id=entity['id'], digest=digest(message)))
        if facts:
            with httpx.Client(timeout=2, trust_env=False) as local:
                response = local.post(os.environ['PILOT_OPA'] + '/v1/data/operational/decisions',
                    json={'input': dict(customer=message['policy'], destination_entity=entity,
                         destination_store=STORE_INFO[CONFIG['store_id']], now=__import__('time').time(), resources=facts)})
                response.raise_for_status(); decisions = response.json().get('result')
            if not isinstance(decisions, list) or len(decisions) != len(facts) or not all(
                d.get('allow') is True and set(r['row']) <= set(d.get('fields',[]))
                for d,r in zip(decisions,rows)):
                raise HTTPException(403, 'Recipient policy admission denied')
        with psycopg.connect(os.environ['PILOT_DSN'], connect_timeout=2) as c:
            status = apply_projection(c, message)
        return dict(status=status)

    @app.post('/internal/read')
    def read_graph(body: dict, authorization: str | None = Header(None)):
        importing(authorization)
        entity = destination(body.get('destination_entity_id'))
        current = admission(dict(operation='read', scope_id=uuid_text(body.get('scope_id')),
            destination_entity_id=entity['id'], principal_id=body.get('principal_id'),
            minimum_data_version=body.get('minimum_data_version', 0)))
        key = (current['owner_entity_id'], current['scope_id'], entity['id'])
        with psycopg.connect(os.environ['PILOT_DSN'], connect_timeout=2) as c:
            receipt = c.execute('SELECT data_version,policy_generation,decision_revision,placement_version '
                'FROM sovereignty.manifest WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s', key).fetchone()
            if not receipt:
                raise HTTPException(404, 'Projection not ready')
            verify_projection_authority(c, key, current)
            if tuple(receipt[1:]) != tuple(current[k] for k in ('policy_generation', 'decision_revision', 'placement_version')) or receipt[0] < body.get('minimum_data_version', 0):
                raise HTTPException(409, 'Current authorised data version not ready')
            kind = 'party' if current.get('scope_kind') == 'party' else 'relationship'
            imported = {(r[0],str(r[1])):set(r[2]) for r in c.execute(
                'SELECT resource_type,resource_id,fields FROM sovereignty.field_manifest '
                'WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s',key)}
            rows = []
            for table in core.ORDER:
                if kind == 'party' and table != 'party':
                    continue
                columns = core.TABLES[table]['global_fields' if kind == 'party' else 'export_fields']
                if not columns:
                    continue
                records = c.execute('SELECT ' + ','.join(columns) + f' FROM projection.{table} '
                    'WHERE owner_entity_id=%s AND scope_id=%s AND destination_entity_id=%s LIMIT 51', key).fetchall()
                for record in records:
                    row=clean(dict(zip(columns,record)))
                    # Older lab projections have no field ledger: treat them as
                    # the full registered set so source narrowing still fences them.
                    present=imported.get((table,row['id']),set(columns))
                    rows.append(dict(table=table,row={k:v for k,v in row.items() if k in present}))
            if len(rows) > 50:
                raise HTTPException(422, 'Pilot graph requires a bounded query')
        guard = {(r['table'], r['row']['id']): r for r in current['facts']}
        if any((r['table'],r['row']['id']) not in guard or
               not set(r['row']) <= set(guard[(r['table'],r['row']['id'])].get('source_fields',[]))
               for r in rows):
            raise HTTPException(409, 'Stored graph requires current-policy reconciliation')
        facts = [guard[(r['table'],r['row']['id'])] for r in rows]
        with httpx.Client(timeout=2, trust_env=False) as local:
            response = local.post(os.environ['PILOT_OPA'] + '/v1/data/operational/decisions',
                json={'input': dict(customer=current['policy'], destination_entity=entity,
                     destination_store=STORE_INFO[CONFIG['store_id']], now=__import__('time').time(), resources=facts)})
            response.raise_for_status(); decisions = response.json().get('result')
        if not isinstance(decisions,list) or len(decisions) != len(rows) or not all(d.get('allow') is True and set(r['row']) <= set(d.get('fields',[])) for d,r in zip(decisions,rows)):
            raise HTTPException(403, 'Recipient read policy denied')
        view = {k:v for k,v in current.items() if k not in ('policy','facts')}
        return bound({**view, 'data_version': receipt[0], 'served_from': 'projection', 'rows': rows})
else:
    raise RuntimeError('Unknown pilot service role')

original_openapi = app.openapi
def authenticated_openapi():
    schema = original_openapi()
    schema.setdefault('components', {}).setdefault('securitySchemes', {})['PilotBearer'] = {
        'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'opaque synthetic pilot credential'}
    for path, operations in schema['paths'].items():
        if path.startswith(('/pilot/system/', '/pilot/experience/', '/pilot/api/')):
            for operation in operations.values():
                operation['security'] = [{'PilotBearer': []}]
    return schema
app.openapi = authenticated_openapi
install_servicing_peer(app, CONFIG, HTTP)
