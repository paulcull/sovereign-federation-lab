"""Standalone durable migration demo: uvicorn migration_app:app."""
import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from migration import MigrationRuntime,make_router
provider=TracerProvider(resource=Resource.create({'service.name':'sovereign-migration-poc'}))
if os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT'):
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
if os.getenv('MIGRATION_STORAGE','cockroach')!='cockroach':raise RuntimeError('Service entry points require CockroachDB; SQLite is only an explicit historical unit-test adapter')
runtime=MigrationRuntime(mode='cockroach',tracer=trace.get_tracer('sovereign.migration'))
@asynccontextmanager
async def lifespan(app):
    runtime.initialize()
    yield
    provider.shutdown()
app=FastAPI(title='Sovereign relocation PoC',lifespan=lifespan)
app.include_router(make_router(runtime))
app.mount('/',StaticFiles(directory=os.getenv('UI_DIR',str(Path(__file__).resolve().parents[1]/'dist')),html=True))
