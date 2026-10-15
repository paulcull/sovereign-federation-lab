"""Private pilot credentials, verified TLS and bounded protocol helpers."""
import hashlib
import hmac
import json
import os
import ssl
from pathlib import Path

import httpx
from fastapi import HTTPException


def configuration():
    path = Path(os.environ['PILOT_CONFIG'])
    value = json.loads(path.read_text())
    if value.get('version') != 1:
        raise RuntimeError('Unsupported pilot configuration')
    return value


def authenticated(authorization, identities):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Bearer credential required')
    candidate = authorization[7:]
    if len(candidate) > 256 or not candidate.isascii():
        raise HTTPException(401, 'Invalid credential')
    for name, identity in identities.items():
        if hmac.compare_digest(candidate, identity['token']):
            return name, identity
    raise HTTPException(401, 'Invalid credential')


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

