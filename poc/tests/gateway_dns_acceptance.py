"""Real Docker DNS regression; restore Grafana's original address in finally.

Run on the Docker host after ./lab up, with no concurrent mutable lab suites.
The gateway process must serve the same real Grafana after its address changes.
No alternate server or simulated health response is used.
"""
import ipaddress
import json
import os
import subprocess
import time
import urllib.request


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
network = json.loads(docker('network', 'inspect', network_name))[0]
original = endpoint['IPAddress']
subnet = next(ipaddress.ip_network(c['Subnet']) for c in network['IPAM']['Config']
              if ipaddress.ip_network(c['Subnet']).version == 4)
occupied = {c['IPv4Address'].split('/')[0] for c in network['Containers'].values()}
occupied.update(c.get('Gateway', '') for c in network['IPAM']['Config'])
replacement = next(str(subnet.broadcast_address - offset) for offset in range(2, 100)
                   if str(subnet.broadcast_address - offset) not in occupied
                   and subnet.broadcast_address - offset > subnet.network_address)
aliases = endpoint.get('Aliases') or ['grafana']


def connect(address):
    args = ['network', 'connect', '--ip', address]
    for alias in aliases:
        args.extend(['--alias', alias])
    docker(*args, network_name, grafana['Id'])


try:
    docker('network', 'disconnect', network_name, grafana['Id'])
    connect(replacement)
    assert container('grafana')['NetworkSettings']['Networks'][network_name]['IPAddress'] != original
    await_healthy(version)
    current_gateway = container('gateway')
    assert current_gateway['Id'] == gateway['Id']
    assert current_gateway['State']['StartedAt'] == gateway['State']['StartedAt']
    print('PASS gateway follows a different real Grafana address without restarting')
finally:
    current = container('grafana')['NetworkSettings']['Networks']
    if network_name in current:
        docker('network', 'disconnect', network_name, grafana['Id'])
    connect(original)
    await_healthy(version)
print('PASS original Grafana address restored and dashboard service healthy')
