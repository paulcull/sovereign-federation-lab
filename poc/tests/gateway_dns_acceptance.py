"""Real Docker DNS regression; restore Grafana's network attachment in finally.

Run on the Docker host after ./lab up, with no concurrent mutable lab suites.
The gateway process must serve the same real Grafana after its address changes.
No alternate server or simulated health response is used.
"""
import json
import os
import subprocess
import time
import urllib.request
import uuid


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def container(service):
    identifier = docker('compose', 'ps', '-q', service)
    assert identifier, f'{service} must be running'
    return json.loads(docker('inspect', identifier))[0]


base = os.getenv('POC_URL', 'http://127.0.0.1:8080').rstrip('/')
client = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def healthy():
    with client.open(base + '/grafana/api/health', timeout=3) as response:
        data = json.load(response)
    assert data['database'] == 'ok'
    return data['version']


def await_healthy(version):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            assert healthy() == version
            return
        except (OSError, ValueError, AssertionError):
            time.sleep(.5)
    raise AssertionError('Gateway did not follow the real Grafana address change')


grafana = container('grafana')
gateway = container('gateway')
version = healthy()
networks = grafana['NetworkSettings']['Networks']
assert len(networks) == 1, 'This regression targets the single-network development lab'
network_name, endpoint = next(iter(networks.items()))
original = endpoint['IPAddress']
requested_ip = (endpoint.get('IPAMConfig') or {}).get('IPv4Address')
aliases = endpoint.get('Aliases') or ['grafana']
reservations = []


def connect(address=None):
    args = ['network', 'connect']
    if address:
        args.extend(['--ip', address])
    for alias in aliases:
        args.extend(['--alias', alias])
    docker(*args, network_name, grafana['Id'])


try:
    # Default Docker IPAM can reject --ip even though inspect shows a subnet.
    # Reserve released addresses with short-lived sleep processes using the
    # already-built gateway image. Grafana itself receives a normal dynamic IP.
    # These containers serve no HTTP or business/database substitute.
    for attempt in range(8):
        docker('network', 'disconnect', network_name, grafana['Id'])
        holder = docker('run', '--rm', '-d', '--network', network_name,
                        '--name', 'sfl-dns-reserve-' + uuid.uuid4().hex[:12],
                        '--entrypoint', '/bin/sh', gateway['Image'], '-c', 'sleep 120')
        reservations.append(holder)
        connect()
        if container('grafana')['NetworkSettings']['Networks'][network_name]['IPAddress'] != original:
            break
    else:
        raise AssertionError('Docker did not allocate a different real Grafana address')
    await_healthy(version)
    current_gateway = container('gateway')
    assert current_gateway['Id'] == gateway['Id']
    assert current_gateway['State']['StartedAt'] == gateway['State']['StartedAt']
    print('PASS gateway follows a different real Grafana address without restarting')
finally:
    for holder in reservations:
        subprocess.run(['docker', 'rm', '-f', holder], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    current = container('grafana')['NetworkSettings']['Networks']
    if network_name in current:
        docker('network', 'disconnect', network_name, grafana['Id'])
    # Preserve an originally requested static IP; otherwise let Docker restore
    # the original network/aliases with its normal dynamic address allocation.
    connect(requested_ip)
    await_healthy(version)
print('PASS Grafana network attachment restored, reservations removed and service healthy')
