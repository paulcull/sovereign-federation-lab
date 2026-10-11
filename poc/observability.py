"""Payload-free application logs; no root logger or container-log scraping.

Only emit fixed event names and reviewed scalar fields. Export is bounded and
asynchronous; SQL audit durability remains independent of telemetry delivery.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from opentelemetry import trace
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

FIELDS = {"method", "route", "status", "duration_ms"}
EVENTS = {"http.request.completed", "worker.retry", "service.started", "service.stopped"}


class ApplicationLogs:
    def __init__(self, service, endpoint=None, exporter=None, stream=None):
        self.provider = LoggerProvider(resource=Resource.create({"service.name": service}))
        endpoint = endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if exporter is None and endpoint:
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
            exporter = OTLPLogExporter(endpoint=endpoint.rstrip("/") + "/v1/logs", timeout=2)
        if exporter is not None:
            self.provider.add_log_record_processor(BatchLogRecordProcessor(
                exporter, max_queue_size=2048, max_export_batch_size=256,
                schedule_delay_millis=1000, export_timeout_millis=2000))
        # Dedicated logger avoids exporter recursion and third-party payload leakage.
        self.logger = logging.Logger(service + ".safe-events", level=logging.INFO)
        self.logger.propagate = False
        console = logging.StreamHandler(stream if stream is not None else sys.stdout)
        console.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(console)
        self.logger.addHandler(LoggingHandler(logger_provider=self.provider))

    def emit(self, event, level=logging.INFO, **fields):
        if event not in EVENTS or set(fields) - FIELDS:
            raise ValueError("Unapproved telemetry event or field")
        ctx = trace.get_current_span().get_span_context()
        body = {"timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event, "level": logging.getLevelName(level), **fields}
        if ctx.is_valid:
            body.update(trace_id=f"{ctx.trace_id:032x}", span_id=f"{ctx.span_id:016x}")
        self.logger.log(level, json.dumps(body, separators=(",", ":")))

    def shutdown(self):
        self.provider.shutdown()


class RequestTelemetry:
    """Pure ASGI middleware: logs completion, preserves responses and exceptions.

    Route templates are resolved after routing. Unknown paths become 'unmatched'.
    No incoming trace context/baggage is accepted; a local correlation ID is made.
    """
    def __init__(self, app, logs, tracer):
        self.app, self.logs, self.tracer = app, logs, tracer

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        status = 500
        with self.tracer.start_as_current_span(
                "http.server", kind=trace.SpanKind.SERVER,
                record_exception=False, set_status_on_exception=False) as span:
            async def traced_send(message):
                nonlocal status
                if message["type"] == "http.response.start":
                    status = message["status"]
                    message = dict(message)
                    message["headers"] = [
                        (k, v) for k, v in message.get("headers", [])
                        if k.lower() != b"x-trace-id"] + [
                        (b"x-trace-id", f"{span.get_span_context().trace_id:032x}".encode())]
                await send(message)
            try:
                await self.app(scope, receive, traced_send)
            except Exception:
                status = 500
                raise
            finally:
                # Never fall back to raw scope['path'] or exception messages.
                route = getattr(scope.get("route"), "path", "unmatched")
                method = scope.get("method", "OTHER")
                if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                    method = "OTHER"
                span.set_attributes({"http.request.method": method,
                                     "http.route": route,
                                     "http.response.status_code": status})
                if status >= 500:
                    span.set_status(trace.Status(trace.StatusCode.ERROR))
                self.logs.emit("http.request.completed",
                               level=logging.ERROR if status >= 500 else logging.INFO,
                               method=method, route=route, status=status,
                               duration_ms=round((time.perf_counter() - started) * 1000, 2))
