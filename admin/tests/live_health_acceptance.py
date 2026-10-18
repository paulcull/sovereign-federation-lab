"""Actual lab gateway/SQL/OPA health evidence; never a substitute for lab test.

Run healthy once, stop the actual UK OPA, run --phase degraded, restore OPA,
then run healthy again. This script itself never changes infrastructure or data.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from admin.health import GatewayObserver, HealthState
from admin.registry import Registry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compact', action='store_true')
    parser.add_argument('--phase', choices=['healthy', 'degraded', 'unavailable'], default='healthy')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        registry = Registry(folder)
        registry.save(registry.plan('register_store', {'id': 'STORE-DE-01', 'name': 'Germany',
            'country': 'DE', 'node_count': 3}), str(uuid.uuid4()))
        config = registry.read()
        observer = GatewayObserver()
        deadline = time.monotonic() + 45
        while True:
            observed = observer.poll()
            expected = {'SG', 'UK'} if args.compact else {'SG', 'UK', 'US', 'IN'}
            if args.phase == 'unavailable':
                if not observed.available:
                    break
                healthy = False
            else:
                healthy = observed.available and set(observed.regions) == expected
            if healthy:
                healthy = all(row['database'] and row['policy'] == (region != 'UK' or args.phase == 'healthy')
                              for region, row in observed.regions.items())
            if healthy:
                break
            if time.monotonic() >= deadline:
                raise AssertionError('Actual lab SQL/OPA observation did not match the requested phase')
            time.sleep(1)
        health = HealthState()
        health.record(observed)
        view = health.snapshot(config['stores'])
        rows = {row['id']: row for row in view['stores']}
        if args.phase == 'unavailable':
            assert not view['current']
            assert not any(row['status'] == 'SQL + OPA healthy' for row in rows.values())
            assert rows['STORE-DE-01']['status'] == 'Backend unassigned'
            print(json.dumps({'passed': True, 'source': 'actual unavailable gateway', 'health': view}, indent=2))
            return
        assert view['current']
        assert rows['STORE-DE-01']['status'] == 'Backend unassigned'
        assert rows['STORE-GB-01']['status'] == ('Degraded' if args.phase == 'degraded' else 'SQL + OPA healthy')
        assert not any(row['placement_ready'] for row in rows.values())
        if args.compact:
            assert rows['STORE-US-01']['status'] == rows['STORE-IN-01']['status'] == 'Suspended (gateway report)'
        assert registry.read() == config, 'Read-only observation must never alter configuration'
        expired = health.snapshot(config['stores'], now=observed.checked_at + 31)
        assert not expired['current'] and not any(row['status'] == 'SQL + OPA healthy' for row in expired['stores'])
        print(json.dumps({'passed': True, 'source': 'actual gateway readiness with CockroachDB and OPA',
            'phase': args.phase, 'footprint': observed.footprint, 'health': view}, indent=2))


if __name__ == '__main__':
    main()
