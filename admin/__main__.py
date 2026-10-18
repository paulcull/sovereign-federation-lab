"""Optional terminal interface plus standard-library JSON automation commands."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

from .health import GatewayObserver, HealthState, ObservationError, host_resources
from .registry import Plan, Registry, RegistryError, canonical


def main():
    parser = argparse.ArgumentParser(description='Logical store administration; deployment bindings are deferred.')
    parser.add_argument('--state-dir', default=os.getenv('LAB_ADMIN_STATE_DIR', '.lab-admin'))
    parser.add_argument('--gateway', default='http://127.0.0.1:8080')
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('status', help='JSON configuration and observed live health')
    sub.add_parser('config', help='JSON configuration; no network or UI dependency')
    sub.add_parser('history', help='JSON configuration receipts')
    plan = sub.add_parser('plan', help='Review a configuration operation without saving')
    plan.add_argument('action', choices=['register_store', 'configure_store', 'observability'])
    plan.add_argument('--payload', required=True, help='Non-sensitive JSON logical configuration')
    save = sub.add_parser('save', help='Save reviewed intent; never provision or change data placement')
    save.add_argument('action', choices=['register_store', 'configure_store', 'observability'])
    save.add_argument('--payload', required=True)
    save.add_argument('--expected-revision', type=int, required=True)
    save.add_argument('--request-id', required=True, help='Reuse this UUID after an uncertain result')
    args = parser.parse_args()
    registry = Registry(Path(args.state_dir))
    try:
        if args.command is None:
            try:
                from .tui import AdminApp
            except ImportError:
                raise RegistryError('Install the optional terminal dependencies: python3 -m venv .venv-admin; .venv-admin/bin/python -m pip install --require-hashes -r requirements-admin.txt') from None
            AdminApp(registry, GatewayObserver(args.gateway)).run()
            return 0
        state = registry.read()
        if args.command == 'config':
            output = state
        elif args.command == 'history':
            output = {'revision': state['revision'], 'history': state['history']}
        elif args.command == 'status':
            health = HealthState()
            health.record(GatewayObserver(args.gateway).poll())
            output = {'revision': state['revision'], 'configuration': state,
                      'health': health.snapshot(state['stores']), 'resources': host_resources(registry.directory),
                      'deployment_adapter': 'not assigned; configuration changes are pending', 'business_audit': 'required'}
        else:
            try:
                payload = json.loads(args.payload)
            except ValueError:
                raise RegistryError('Payload must be valid logical-configuration JSON.') from None
            if args.command == 'plan':
                review = registry.plan(args.action, payload)
                output = {**asdict(review), 'effect': 'Configuration only; deployment adapter pending'}
            else:
                # Validate/recompute at commit. Identical retries must reach the
                # receipt before registration validation rejects the existing ID.
                review = Plan(args.expected_revision, args.action, canonical(payload), '', ())
                output = registry.save(review, args.request_id)
        print(json.dumps(output, indent=2))
        return 0
    except (RegistryError, ObservationError):
        error = sys.exception()
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
