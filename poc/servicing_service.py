"""Independent synthetic case service: its own model and local transaction boundary.

It consumes the existing MDM experience API. It neither imports the coordinator's
model nor writes its business, sovereignty or MDM tables.
"""
from contextlib import asynccontextmanager
import os
import time
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from pydantic import BaseModel, ConfigDict, Field
import psycopg

from observability import ApplicationLogs, RequestTelemetry
from pilot_common import authenticated, configuration, live_configuration, remote, tls_client, uuid_text
from service_adapter import LocalTransaction
from servicing_policy import decide

CONFIG = configuration()
OWNER = 'LE-SG-01'
OPA = os.getenv('SERVICING_OPA', 'http://opa-sg:8181')
DSN = os.getenv('SERVICING_DSN', 'postgresql://sfl_servicing@db-sg:26257/defaultdb?sslmode=disable')
provider = TracerProvider(resource=Resource.create({'service.name': 'sovereign-servicing'}))
if os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT'):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
logs = ApplicationLogs('sovereign-servicing')
HTTP = tls_client(CONFIG, timeout=8)


def connect():
    return psycopg.connect(DSN, connect_timeout=3, options='-c statement_timeout=5000')


adapter = LocalTransaction(connect, 'servicing', 'servicing-cases')


@asynccontextmanager
async def lifespan(app):
    logs.emit('service.started')
    try:
        yield
    finally:
        HTTP.close()
        logs.emit('service.stopped')
        logs.shutdown()
        provider.shutdown()


app = FastAPI(title='Independent servicing case service', lifespan=lifespan,
              docs_url='/service/api-docs', openapi_url='/service/openapi.json', redoc_url=None)


class SafeErrors:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        except Exception:
            if scope['type'] != 'http':
                raise
            await JSONResponse(status_code=503, content={'detail': 'Required service dependency unavailable; fail closed'})(scope, receive, send)


app.add_middleware(SafeErrors)
app.add_middleware(RequestTelemetry, logs=logs, tracer=trace.get_tracer('sovereign.servicing'))


@app.exception_handler(Exception)
async def unavailable(request: Request, error: Exception):
    return JSONResponse(status_code=503, content={'detail': 'Required service dependency unavailable; fail closed'})


class NewCase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    case_id: UUID
    expected_version: int = Field(ge=0, le=0, strict=True)
    global_party_id: UUID
    relationship_scope_id: UUID
    category: Literal['CONTACT_REVIEW', 'DOCUMENT_REVIEW']


class CaseCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_version: int = Field(ge=1, strict=True)
    command: Literal['close', 'reopen']


class DeliveryAcknowledgement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    data_version: int = Field(ge=1, strict=True)


def identity(header, action):
    cfg = live_configuration(CONFIG)
    actor, principal = authenticated(header, cfg['principals'])
    if action not in principal['actions']:
        raise HTTPException(403, 'Business action not delegated')
    if cfg.get('deployment', {}).get('processing_countries') != ['SG']:
        raise HTTPException(503, 'Service placement not approved')
    return actor, principal


def case_record(case_id):
    case_id = uuid_text(case_id)
    with connect() as connection:
        row = connection.execute('SELECT case_id,mdm_owner_entity_id,global_party_id,relationship_scope_id,'
            'category,status,data_version FROM servicing.case_record WHERE owner_entity_id=%s AND case_id=%s',
            (OWNER, case_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Case not found')
    return dict(case_id=str(row[0]), mdm_owner_entity_id=row[1], global_party_id=str(row[2]),
                relationship_scope_id=str(row[3]), category=row[4], status=row[5], data_version=row[6])


def authorize(case, principal, action, *, exported=False):
    decision = decide(OPA, action, principal, 'SG')
    cfg = live_configuration(CONFIG)
    token = cfg['mdm_export_token'] if exported else cfg['mdm_token']
    view = remote(HTTP, 'GET', cfg['mdm_url'] + '/pilot/experience/v1/relationships/' + case['relationship_scope_id'],
                  token, params={'freshness': 'owner'})
    if (view.get('owner_entity_id') != OWNER or view.get('scope_kind') != 'relationship'
            or not any(item.get('table') == 'party' and item.get('row', {}).get('global_party_id') == case['global_party_id']
                       for item in view.get('rows', []))):
        raise HTTPException(403, 'MDM relationship association is not authorised')
    return dict(service_policy_revision=decision['revision'], observed_at=time.time(),
                mdm_data_version=view['data_version'], mdm_policy_generation=view['policy_generation'],
                mdm_decision_revision=view['decision_revision'])


@app.get('/healthz')
def health():
    return {'status': 'alive', 'service': 'servicing-cases'}


@app.get('/readyz')
def ready():
    with connect() as connection:
        for table in ('case_record', 'aggregate_version', 'state_outbox', 'transition_event',
                      'transaction_audit', 'request_receipt', 'delivery_receipt'):
            connection.execute('SELECT 1 FROM servicing.' + table + ' LIMIT 0')
    decide(OPA, 'case.read', dict(entity_id=OWNER, processing_country='SG', actions=['case.read']), 'SG')
    return {'status': 'ready', 'service': 'servicing-cases'}


@app.post('/service/system/v1/cases', tags=['Independent business service'])
def create(body: NewCase, authorization: str | None = Header(None)):
    actor, principal = identity(authorization, 'case.create')
    values = body.model_dump(mode='json')

    def mutate(connection, version):
        connection.execute('INSERT INTO servicing.case_record VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
            (OWNER, values['case_id'], OWNER, values['global_party_id'], values['relationship_scope_id'],
             values['category'], 'OPEN', version))
        return {'case_id': values['case_id'], 'status': 'OPEN'}

    return adapter.execute(owner=OWNER, aggregate=values['case_id'], actor=actor,
        request_id=values['request_id'], operation='create', body=values, expected_version=0,
        authorize=lambda: authorize(values, identity(authorization, 'case.create')[1], 'case.create'), mutate=mutate)


@app.get('/service/system/v1/cases/{case_id}', tags=['Independent business service'])
def read(case_id: str, authorization: str | None = Header(None)):
    _, principal = identity(authorization, 'case.read')
    case = case_record(case_id)
    authorize(case, principal, 'case.read')
    with connect() as connection:
        receipt = connection.execute('SELECT data_version FROM servicing.delivery_receipt '
            "WHERE service_id='servicing-cases' AND owner_entity_id=%s AND aggregate_id=%s AND destination_entity_id='LE-GB-02'",
            (OWNER, case['case_id'])).fetchone()
        pending = max(0, case['data_version'] - receipt[0]) if receipt else case['data_version']
    return {'owner_entity_id': OWNER, **case, 'delivery': dict(mode='explicit_recipient_refresh', pending_intents=pending)}


@app.post('/service/system/v1/cases/{case_id}/commands', tags=['Independent business service'])
def command(case_id: str, body: CaseCommand, authorization: str | None = Header(None)):
    case_id = uuid_text(case_id)
    actor, principal = identity(authorization, 'case.' + body.command)
    case = case_record(case_id)
    values = body.model_dump(mode='json')
    desired = 'CLOSED' if body.command == 'close' else 'OPEN'

    def mutate(connection, version):
        current = connection.execute('SELECT status,data_version FROM servicing.case_record '
            'WHERE owner_entity_id=%s AND case_id=%s FOR UPDATE', (OWNER, case_id)).fetchone()
        if current is None or current[1] != version - 1:
            raise HTTPException(409, 'Business row and aggregate version diverged')
        if current[0] == desired:
            raise HTTPException(409, 'Case already has requested status')
        connection.execute('UPDATE servicing.case_record SET status=%s,data_version=%s '
                           'WHERE owner_entity_id=%s AND case_id=%s', (desired, version, OWNER, case_id))
        return {'case_id': case_id, 'status': desired}

    return adapter.execute(owner=OWNER, aggregate=case_id, actor=actor, request_id=values['request_id'],
        operation=body.command, body=values, expected_version=body.expected_version,
        authorize=lambda: authorize(case, identity(authorization, 'case.' + body.command)[1], 'case.' + body.command),
        mutate=mutate)


@app.get('/service/internal/v1/cases/{case_id}/export', include_in_schema=False)
def export(case_id: str, authorization: str | None = Header(None)):
    cfg = live_configuration(CONFIG)
    _, peer = authenticated(authorization, cfg['export_identities'])
    if cfg.get('deployment', {}).get('processing_countries') != ['SG']:
        raise HTTPException(503, 'Service placement not approved')
    if peer.get('role') != 'peer' or peer.get('store_id') != 'STORE-GB-01':
        raise HTTPException(403, 'Case recipient excluded')
    principal = dict(entity_id='LE-GB-02', processing_country='GB', actions=['case.export'])
    case = case_record(case_id)
    authorize(case, principal, 'case.export', exported=True)
    # Re-read the bounded case: export current state, not queued payload snapshots.
    case = case_record(case_id)
    decision = decide(OPA, 'case.export', principal, 'SG')
    fields = set(decision['fields'])
    if fields != {'case_id', 'status', 'category', 'data_version'}:
        raise HTTPException(409, 'Compatible case field contract not ready')
    return dict(contract='servicing-case-state-v1', owner_entity_id=OWNER, destination_entity_id='LE-GB-02',
                policy_revision=decision['revision'], row={key: case[key] for key in sorted(fields)})


@app.post('/service/internal/v1/cases/{case_id}/ack', include_in_schema=False)
def acknowledgement(case_id: str, body: DeliveryAcknowledgement, authorization: str | None = Header(None)):
    cfg = live_configuration(CONFIG)
    _, peer = authenticated(authorization, cfg['export_identities'])
    if peer.get('role') != 'peer' or peer.get('store_id') != 'STORE-GB-01':
        raise HTTPException(403, 'Case recipient excluded')
    case = case_record(case_id)
    if body.data_version > case['data_version']:
        raise HTTPException(409, 'Cannot acknowledge an uncommitted version')
    with connect() as connection:
        key = ('servicing-cases', OWNER, case['case_id'], 'LE-GB-02')
        prior = connection.execute('SELECT data_version FROM servicing.delivery_receipt '
            'WHERE service_id=%s AND owner_entity_id=%s AND aggregate_id=%s AND destination_entity_id=%s FOR UPDATE', key).fetchone()
        if not prior or prior[0] < body.data_version:
            connection.execute('UPSERT INTO servicing.delivery_receipt '
                '(service_id,owner_entity_id,aggregate_id,destination_entity_id,data_version) VALUES (%s,%s,%s,%s,%s)',
                key + (body.data_version,))
    return {'acknowledged_data_version': body.data_version}


original_openapi = app.openapi


def authenticated_openapi():
    schema = original_openapi()
    schema.setdefault('components', {}).setdefault('securitySchemes', {})['CaseBearer'] = {
        'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'opaque synthetic case credential'}
    for path, operations in schema['paths'].items():
        if path.startswith('/service/system/'):
            for operation in operations.values():
                operation['security'] = [{'CaseBearer': []}]
                operation['parameters'] = [item for item in operation.get('parameters', [])
                    if not (item.get('in') == 'header' and item.get('name', '').lower() == 'authorization')]
    return schema


app.openapi = authenticated_openapi
