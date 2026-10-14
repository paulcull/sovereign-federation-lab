"""Generate private per-role pilot identities and a local test CA. Never print keys."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.pilot'
ROLES = ['owner', 'api', 'authority', 'peer-sg', 'peer-uk', 'peer-us']


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')
    path.chmod(0o600)


def openssl(*args):
    subprocess.run(['openssl', *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if sys.argv[1:] and sys.argv[1] == 'token':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: pilot_setup.py token crm-sg|sg-owner|uk-servicing|uk-business|us-reader|uk-from-us')
    config = json.loads((OUT / 'api/config.json').read_text())
    identity = config['principals'].get(sys.argv[2])
    if identity is None:
        raise SystemExit('Unknown pilot identity')
    print(identity['token'])  # Explicit operator command, never executed in acceptance logs.
    raise SystemExit(0)

if (OUT / 'ready.json').exists():
    expected = json.loads((OUT / 'ready.json').read_text())
    if expected.get('version') != 1 or not all((OUT / role / 'config.json').exists() for role in ROLES):
        raise SystemExit('Pilot identity directory incomplete; recover it explicitly')
    print('Reusing existing private pilot identities.')
    raise SystemExit(0)
if OUT.exists() and any(OUT.iterdir()):
    raise SystemExit('Partial pilot setup; move aside the incomplete private directory before retrying')

os.umask(0o077)
OUT.mkdir(exist_ok=True, mode=0o700)
ca = OUT / 'issuer'; ca.mkdir(mode=0o700)
openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(ca / 'ca.key'),
        '-out', str(ca / 'ca.crt'), '-days', '30', '-subj', '/CN=Sovereign Synthetic Pilot CA')
for role in ROLES:
    directory = OUT / role; directory.mkdir(mode=0o700)
    hostname = 'pilot-' + role
    openssl('req', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(directory / 'tls.key'),
            '-out', str(directory / 'tls.csr'), '-subj', '/CN=' + hostname)
    extension = directory / 'tls.ext'
    extension.write_text('subjectAltName=DNS:' + hostname + '\nextendedKeyUsage=serverAuth,clientAuth\n')
    openssl('x509', '-req', '-in', str(directory / 'tls.csr'), '-CA', str(ca / 'ca.crt'),
            '-CAkey', str(ca / 'ca.key'), '-CAcreateserial', '-out', str(directory / 'tls.crt'),
            '-days', '14', '-extfile', str(extension))
    (directory / 'ca.crt').write_bytes((ca / 'ca.crt').read_bytes())
    (directory / 'tls.csr').unlink(); extension.unlink()

principals = {
    'crm-sg': dict(entity_id='LE-SG-01', processing_country='SG', actions=['system', 'read', 'command'], source_system='crm-sg'),
    'sg-owner': dict(entity_id='LE-SG-01', processing_country='SG', actions=['read', 'command']),
    'uk-servicing': dict(entity_id='LE-GB-02', processing_country='GB', actions=['read', 'command']),
    'uk-business': dict(entity_id='LE-GB-03', processing_country='GB', actions=['read']),
    'us-reader': dict(entity_id='LE-US-01', processing_country='US', actions=['read']),
    'uk-from-us': dict(entity_id='LE-GB-02', processing_country='US', actions=['read', 'command']),
}
api_token = secrets.token_urlsafe(32)
identities = {'api': dict(token=api_token, role='api')}
peers = {}
for region, store in [('sg', 'STORE-SG-01'), ('uk', 'STORE-GB-01'), ('us', 'STORE-US-01')]:
    caller = secrets.token_urlsafe(32); importer = secrets.token_urlsafe(32)
    identities['peer-' + region] = dict(token=caller, role='peer', store_id=store)
    peers[store] = dict(url='https://pilot-peer-' + region + ':8443', import_token=importer)
    write(OUT / ('peer-' + region) / 'config.json', dict(version=1, role='peer', store_id=store,
        authority_url='https://pilot-authority:8443', authority_token=caller, import_token=importer))
write(OUT / 'owner/config.json', dict(version=1, role='owner', identities=identities,
    peers=peers, principals={name: {**profile, 'id': name} for name, profile in principals.items()}))
write(OUT / 'api/config.json', dict(version=1, role='api', authority_url='https://pilot-authority:8443',
    authority_token=api_token, principals={name: {**profile, 'token': secrets.token_urlsafe(32)}
                                         for name, profile in principals.items()}))
write(OUT / 'authority/config.json', dict(version=1, role='authority'))
write(OUT / 'ready.json', dict(version=1))
print('Created private synthetic pilot identities and verified-TLS certificates; credentials are not logged.')
