"""Payload-free local trace evidence; export failure never changes business success."""
import json
import os
from pathlib import Path

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class PilotTraceEvidence(SpanExporter):
    def __init__(self, role, store=''):
        self.path = Path(os.getenv('TELEMETRY_DIR', '/tmp/pilot-telemetry')) / ('pilot-' + role + store + '-traces.jsonl')

    def export(self, spans):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a') as output:
                for span in spans:
                    fields = {k:v for k,v in dict(span.attributes or {}).items() if k in (
                        'http.request.method', 'http.route', 'http.response.status_code')}
                    output.write(json.dumps(dict(trace_id=f'{span.context.trace_id:032x}',
                        span=span.name, attributes=fields)) + '\n')
        except OSError:
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS
