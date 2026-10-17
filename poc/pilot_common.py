"""Private pilot credentials, verified TLS and bounded protocol helpers."""
import hashlib
import hmac
import json
import math
import os
import ssl
import time
from pathlib import Path

import httpx
from fastapi import HTTPException


COMMAND_ATTRIBUTES = {
    'update_contact': {'contact_info.value'},
    'withdraw_consent': {'consent.status'},
    'restore_consent': {'consent.status'},
}


def configuration(path=None):
    path = Path(path or os.environ['PILOT_CONFIG'])
    value = json.loads(path.read_text())
    if value.get('version') != 2:
        raise RuntimeError('Pilot identity configuration requires explicit setup upgrade')
    # A mode label cannot turn this root-SQL/plain-OPA, single-host deployment
    # into a bank environment. Refuse deliberate production mode requests.
    if value.get('mode') != 'synthetic' or os.getenv('PILOT_ENVIRONMENT', 'synthetic') != 'synthetic':
        raise RuntimeError('Production deployment is not supported by the synthetic pilot profile')
    countries = value.get('deployment', {}).get('processing_countries')
    if not isinstance(countries, list) or not countries or any(
            not isinstance(c, str) or len(c) != 2 or not c.isascii() or not c.isupper() or not c.isalpha()
            for c in countries):
        raise RuntimeError('Trusted deployment processing locations required')
    fixed_country = {'owner': 'SG', 'api': 'SG', 'authority': 'SG', 'servicing': 'SG'}.get(value.get('role'))
    if value.get('role') == 'peer':
        fixed_country = {'STORE-SG-01': 'SG', 'STORE-GB-01': 'GB', 'STORE-US-01': 'US'}.get(value.get('store_id'))
    if fixed_country is None or countries != [fixed_country]:
        raise RuntimeError('Deployment path outside registered synthetic topology')
    value['_config_path'] = str(path.resolve())
    return value


def live_configuration(config):
    """Reload mounted identity policy per request; do not cache revocation.

    Atomic file replacement is used by setup commands. Missing/invalid files
    fail closed. TLS certificates are intentionally rotated by service restart.
    """
    if '_config_path' not in config:
        return config
    current = configuration(config['_config_path'])
    for key in ('role', 'store_id', 'deployment', 'authority_url', 'mdm_url', 'servicing_url'):
        if current.get(key) != config.get(key):
            raise HTTPException(503, 'Deployment registration changed; controlled restart required')
    if {store: peer.get('url') for store, peer in current.get('peers', {}).items()} != {
            store: peer.get('url') for store, peer in config.get('peers', {}).items()}:
        raise HTTPException(503, 'Peer registration changed; controlled restart required')
    return current


def active_identity(identity, now=None):
    now = time.time() if now is None else now
    start, end = identity.get('not_before'), identity.get('expires_at')
    return (type(start) in (int, float) and type(end) in (int, float)
            and math.isfinite(start) and math.isfinite(end)
            and start <= now < end and identity.get('revoked') is False)


def authenticated(authorization, identities):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Bearer credential required')
    candidate = authorization[7:]
    if len(candidate) > 256 or not candidate.isascii():
        raise HTTPException(401, 'Invalid credential')
    for name, identity in identities.items():
        token = identity.get('token')
        if isinstance(token, str) and hmac.compare_digest(candidate, token) and active_identity(identity):
            return name, identity
    raise HTTPException(401, 'Invalid credential')


def registered_principal(config, name):
    identity = live_configuration(config).get('principals', {}).get(name)
    if not isinstance(identity, dict) or not active_identity(identity):
        raise HTTPException(403, 'Principal unavailable or no longer delegated')
    return {**identity, 'id': name}


def require_command(identity, payload):
    """Read rights never imply business-command or attribute mutation rights."""
    command = payload.get('command')
    required = COMMAND_ATTRIBUTES.get(command)
    allowed = identity.get('command_grants', {}).get(command)
    if (not active_identity(identity) or 'command' not in identity.get('actions', [])
            or required is None or not isinstance(allowed, list) or not required <= set(allowed)):
        raise HTTPException(403, 'Command or attribute outside delegated authority')


def processing_countries(config, identity):
    # This path comes from deployment registration, never HTTP geography headers.
    countries = live_configuration(config).get('deployment', {}).get('processing_countries')
    if not isinstance(countries, list) or not countries or not identity.get('processing_country'):
        raise HTTPException(503, 'Trusted processing path unavailable')
    return set(countries) | {identity['processing_country']}


def tls_client(config, timeout=8):
    directory = Path(os.environ['PILOT_CONFIG']).parent
    context = ssl.create_default_context(cafile=str(directory / 'ca.crt'))
    context.load_cert_chain(str(directory / 'tls.crt'), str(directory / 'tls.key'))
    return httpx.Client(verify=context, timeout=timeout, trust_env=False)


def remote(client, method, url, token, body=None, params=None):
    try:
        response = client.request(method, url, headers={'Authorization': 'Bearer ' + token},
                                  json=body, params=params)
    except httpx.HTTPError:
        raise HTTPException(503, 'Required pilot dependency unavailable; fail closed')
    if response.status_code >= 400:
        status = response.status_code if response.status_code in (401, 403, 404, 409, 422, 503) else 503
        if status == 409:
            try:
                if response.json().get('detail') == {'code': 'projection_receipt_conflict'}:
                    raise HTTPException(409, {'code': 'projection_receipt_conflict'})
            except (ValueError, AttributeError):
                pass
        # Do not propagate dependency messages, raw URLs or database diagnostics.
        raise HTTPException(status, {401: 'Workload identity rejected', 403: 'Policy denied',
            404: 'Approved view not available', 409: 'Current version not ready or request conflict',
            422: 'Invalid pilot request', 503: 'Required pilot dependency unavailable'}[status])
    try:
        return response.json()
    except ValueError:
        raise HTTPException(503, 'Invalid dependency response; fail closed')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def uuid_text(value):
    import uuid
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, 'A UUID is required')

