"""Real OTLP HTTP export, correlation, minimisation and failure isolation tests."""
import asyncio
import io
import json
import logging
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from fastapi import FastAPI
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk._logs.export import LogExportResult
from observability import ApplicationLogs, RequestTelemetry


class ObservabilityTests(unittest.TestCase):
    def test_otlp_http_correlation_and_minimisation(self):
        received = []
        class Sink(BaseHTTPRequestHandler):
            def do_POST(self):
                packet = ExportLogsServiceRequest()
                packet.ParseFromString(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((self.path, packet))
                self.send_response(200); self.end_headers()
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Sink)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        stdout = io.StringIO()
        logs = ApplicationLogs('test-service', endpoint=f'http://127.0.0.1:{server.server_port}', stream=stdout)
        traces = TracerProvider()
        app = FastAPI()
        app.add_middleware(RequestTelemetry, logs=logs, tracer=traces.get_tracer('test'))
        @app.post('/party/{party_id}')
        async def party(party_id: str): return {'ok': True}
        @app.get('/failure')
        async def failure(): raise RuntimeError('secret-exception-canary')
        async def exercise():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test', trust_env=False) as c:
                response = await c.post('/party/secret-path-canary?key=secret-query-canary',
                    headers={'authorization': 'secret-header-canary'}, json={'name': 'secret-body-canary'})
                self.assertEqual(response.status_code, 200)
                await c.get('/secret-unmatched-canary')
                self.assertEqual((await c.get('/failure')).status_code, 500)
                return response.headers['x-trace-id']
        try:
            trace_id = asyncio.run(exercise())
            self.assertTrue(logs.provider.force_flush())
            records = [record for _, p in received for resource in p.resource_logs
                       for scope in resource.scope_logs for record in scope.log_records]
            self.assertEqual(len(records), 3)
            self.assertTrue(all(path == '/v1/logs' for path, _ in received))
            bodies = [json.loads(record.body.string_value) for record in records]
            self.assertEqual(bodies[0]['route'], '/party/{party_id}')
            self.assertEqual(bodies[1]['route'], 'unmatched')
            self.assertEqual(bodies[2]['level'], 'ERROR')
            self.assertEqual(bodies[2]['status'], 500)
            self.assertEqual(records[0].trace_id.hex(), trace_id)
            self.assertEqual(bodies[0]['trace_id'], trace_id)
            self.assertNotIn('secret-', stdout.getvalue() + str(received))
            with self.assertRaises(ValueError): logs.emit('worker.retry', customer_id='forbidden')
        finally:
            logs.shutdown(); traces.shutdown(); server.shutdown(); server.server_close()

    def test_failed_export_does_not_fail_application(self):
        class FailedExporter:
            def export(self, batch): return LogExportResult.FAILURE
            def shutdown(self): pass
        logs = ApplicationLogs('failure-test', exporter=FailedExporter(), stream=io.StringIO())
        try:
            logs.emit('worker.retry', level=logging.WARNING)
            logs.provider.force_flush()  # Export failure is not a business exception.
        finally: logs.shutdown()


if __name__ == '__main__': unittest.main()
