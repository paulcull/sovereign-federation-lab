"""Read-only, bounded observations of the existing loopback lab gateway."""
from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
import urllib.request

from .registry import BASELINE


class ObservationError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ObservationError('gateway_redirect_rejected')


@dataclass
class Observation:
    checked_at: float
    available: bool
    error: str = ''
    footprint: str = 'unknown'
    regions: dict = field(default_factory=dict)
    observability: str = 'unknown'


class GatewayObserver:
    def __init__(self, origin='http://127.0.0.1:8080', timeout=8):
        try:
            parsed = urlsplit(origin)
            port = parsed.port
            valid = (parsed.scheme in {'http', 'https'} and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}
                     and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                     and parsed.path in {'', '/'} and (port is None or 1 <= port <= 65535))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ObservationError('Use a loopback HTTP(S) gateway origin without credentials, path or query.')
        self.origin, self.timeout = origin.rstrip('/'), timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def poll(self):
        checked_at = time.time()
        try:
            try:
                response = self.opener.open(self.origin + '/api/health/ready', timeout=self.timeout)
            except HTTPError as error:
                if error.code != 503:
                    raise ObservationError('gateway_unavailable') from None
                response = error
            with response:
                status = response.code
                if response.headers.get_content_type() != 'application/json':
                    raise ObservationError('invalid_health_response')
                raw = response.read(131073)
                if len(raw) > 131072:
                    raise ObservationError('oversized_health_response')
            data = json.loads(raw)
            footprint = data.get('footprint', 'full')
            expected = {'SG', 'UK'} if footprint == 'mdm-compact' else {'SG', 'UK', 'US', 'IN'} if footprint == 'full' else set()
            if not expected or data.get('database') != 'cockroach' or not isinstance(data.get('stores'), list):
                raise ObservationError('invalid_health_response')
            regions = {}
            for row in data['stores']:
                if (not isinstance(row, dict) or not isinstance(row.get('region'), str) or row['region'] in regions
                        or type(row.get('database')) is not bool or type(row.get('policy')) is not bool):
                    raise ObservationError('invalid_health_response')
                regions[row['region']] = {'database': row['database'], 'policy': row['policy']}
            healthy = all(row['database'] and row['policy'] for row in regions.values())
            if (set(regions) != expected or status != (200 if healthy else 503)
                    or data.get('status') != ('ready' if healthy else 'not-ready')):
                raise ObservationError('inconsistent_health_response')
            return Observation(checked_at, True, footprint=footprint, regions=regions,
                               observability='suspended' if footprint == 'mdm-compact' else 'configured (not health-verified)')
        except ObservationError as error:
            return Observation(checked_at, False, error=str(error))
        except Exception:
            # No raw network/JSON exception, URL, credentials or payload enters the UI.
            return Observation(checked_at, False, error='gateway_unavailable_or_invalid')


class HealthState:
    def __init__(self, max_age=30):
        self.latest = None
        self.last_success = None
        self.max_age = max_age

    def record(self, observation):
        if self.latest and observation.checked_at < self.latest.checked_at:
            return
        self.latest = observation
        if observation.available:
            self.last_success = observation

    def snapshot(self, stores, now=None):
        now = time.time() if now is None else now
        current = (self.latest and self.latest.available and 0 <= now - self.latest.checked_at <= self.max_age)
        rows = []
        for store in stores:
            region = BASELINE.get(store['id'], (None, None, None))[2]
            check = self.latest.regions.get(region) if current else None
            if region is None:
                status = 'Backend unassigned'
            elif not current:
                status = 'Unknown / stale' if self.last_success else 'Not observed'
            elif check is None:
                status = 'Suspended (gateway report)'
            elif check['database'] and check['policy']:
                status = 'SQL + OPA healthy'
            else:
                status = 'Degraded'
            rows.append({'id': store['id'], 'status': status,
                         'database': check['database'] if check else None,
                         'policy': check['policy'] if check else None,
                         'backend_assignment': 'existing_lab_observation' if region else 'unassigned',
                         'placement_ready': False,
                         'placement_note': 'Placement is governed by the existing lab' if region else 'Backend unassigned; placement unavailable'})
        return {'current': bool(current), 'checked_at': self.latest.checked_at if self.latest else None,
                'last_success_at': self.last_success.checked_at if self.last_success else None,
                'error': self.latest.error if self.latest else '',
                'footprint': self.latest.footprint if current else 'unknown',
                'observability': self.latest.observability if current else 'unknown', 'stores': rows}


def host_resources(path):
    """Host-visible figures, explicitly shared and unrelated to any store allocation."""
    result = {'scope': 'shared host view; not per-store capacity or reservation', 'cpu_count': os.cpu_count()}
    try:
        usage = shutil.disk_usage(Path(path))
        result.update(disk_free_bytes=usage.free, disk_total_bytes=usage.total)
    except OSError:
        result.update(disk_free_bytes=None, disk_total_bytes=None)
    try:
        lines = Path('/proc/meminfo').read_text().splitlines()
        result['memory_available_bytes'] = int(next(line.split()[1] for line in lines if line.startswith('MemAvailable:'))) * 1024
    except (OSError, ValueError, StopIteration):
        result['memory_available_bytes'] = None
    return deepcopy(result)
