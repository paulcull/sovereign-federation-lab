"""Focused identity boundary tests; no database substitutes or production claims."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'poc'))
from pilot_common import (active_identity, authenticated, configuration, live_configuration,
                          processing_countries, registered_principal, remote, require_command)

spec = importlib.util.spec_from_file_location('pilot_setup', ROOT / 'scripts/pilot_setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def valid_identity(**overrides):
    return dict(token='synthetic-test-token', not_before=100, expires_at=300,
                revoked=False, **overrides)


class IdentityTests(unittest.TestCase):
    def assert_http(self, status, function, *args):
        with self.assertRaises(HTTPException) as caught:
            function(*args)
        self.assertEqual(caught.exception.status_code, status)

    def test_lifecycle_requires_explicit_valid_interval_and_status(self):
        value = valid_identity()
        self.assertTrue(active_identity(value, now=200))
        self.assertFalse(active_identity(value, now=99))
        self.assertFalse(active_identity(value, now=300))
        self.assertFalse(active_identity({**value, 'revoked': True}, now=200))
        self.assertFalse(active_identity({'token': value['token']}, now=200))
        self.assertFalse(active_identity({**value, 'not_before': True}, now=200))
        self.assertFalse(active_identity({**value, 'expires_at': float('inf')}, now=200))
        with patch('pilot_common.time.time', return_value=200):
            self.assertEqual(authenticated('Bearer ' + value['token'], {'test': value})[0], 'test')
            self.assert_http(401, authenticated, 'Bearer ' + value['token'], {'test': {**value, 'revoked': True}})
            self.assert_http(401, authenticated, 'Bearer wrong', {'test': value})
            self.assert_http(401, authenticated, 'Bearer ' + ('a' * 257), {'test': value})

    def test_read_and_command_actions_do_not_imply_attribute_delegation(self):
        principal = valid_identity(actions=['read', 'command'], command_grants={'update_contact': ['contact_info.value']})
        with patch('pilot_common.time.time', return_value=200):
            require_command(principal, {'command': 'update_contact'})
            self.assert_http(403, require_command, principal, {'command': 'withdraw_consent'})
            self.assert_http(403, require_command, {**principal, 'command_grants': {}}, {'command': 'update_contact'})
            self.assert_http(403, require_command, {**principal, 'actions': ['read']}, {'command': 'update_contact'})
            self.assert_http(403, require_command, {**principal, 'command_grants': {'update_contact': ['party.name']}}, {'command': 'update_contact'})
            self.assert_http(403, require_command, principal, {'command': 'unknown'})

    def test_deployment_path_adds_to_caller_country(self):
        config = {'deployment': {'processing_countries': ['SG', 'US']}}
        self.assertEqual(processing_countries(config, {'processing_country': 'GB'}), {'SG', 'US', 'GB'})
        self.assert_http(503, processing_countries, {}, {'processing_country': 'GB'})

    def test_revocation_and_delegation_reload_without_process_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'config.json'
            value = dict(version=2, mode='synthetic', role='api', deployment={'processing_countries': ['SG']},
                         principals={'test': valid_identity()})
            setup.write(path, value)
            config = configuration(path)
            with patch('pilot_common.time.time', return_value=200):
                self.assertEqual(registered_principal(config, 'test')['id'], 'test')
                value['principals']['test']['revoked'] = True
                setup.write(path, value)
                self.assert_http(403, registered_principal, config, 'test')
                self.assertTrue(live_configuration(config)['principals']['test']['revoked'])

    def test_production_and_unknown_configuration_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'config.json'
            value = dict(version=2, mode='synthetic', role='api', deployment={'processing_countries': ['SG']})
            setup.write(path, value)
            with patch.dict(os.environ, {'PILOT_ENVIRONMENT': 'production'}):
                with self.assertRaises(RuntimeError):
                    configuration(path)
            for change in ({'mode': 'production'}, {'version': 1}, {'deployment': {}},
                           {'deployment': {'processing_countries': ['US\n']}},
                           {'deployment': {'processing_countries': ['US']}}):
                setup.write(path, {**value, **change})
                with self.assertRaises(RuntimeError):
                    configuration(path)

    def test_hot_relocation_cannot_masquerade_as_identity_rotation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'config.json'
            value = dict(version=2, mode='synthetic', role='peer', store_id='STORE-GB-01',
                         deployment={'processing_countries': ['GB']})
            setup.write(path, value)
            config = configuration(path)
            setup.write(path, {**value, 'store_id': 'STORE-US-01', 'deployment': {'processing_countries': ['US']}})
            self.assert_http(503, live_configuration, config)

    def test_only_allowlisted_peer_conflict_marker_is_returned(self):
        for detail, expected in [({'code': 'projection_receipt_conflict'}, {'code': 'projection_receipt_conflict'}),
                                 ({'code': 'secret-url-and-payload'}, 'Current version not ready or request conflict')]:
            with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(409, json={'detail': detail}))) as client:
                with self.assertRaises(HTTPException) as caught:
                    remote(client, 'POST', 'https://synthetic.invalid/private', 'synthetic-token')
                self.assertEqual(caught.exception.detail, expected)


class SetupTests(unittest.TestCase):
    def test_legacy_upgrade_preserves_credentials_and_certificates_then_rotates_without_logging(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(setup, 'OUT', Path(temporary) / '.pilot'):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                setup.setup()
            api = setup.read('api')
            original_token = api['principals']['crm-sg']['token']
            original_cert = (setup.OUT / 'api/tls.crt').read_bytes()
            # Reconstruct the known v1 layout produced by the previous release.
            added = {'uk-contact-only', 'case-mdm-reader-sg', 'case-mdm-reader-uk'}
            for role in setup.BASE_ROLES:
                config = setup.read(role)
                config['version'] = 1
                for key in ('mode', 'deployment', 'import_credential', 'servicing_principals', 'servicing_url', 'servicing_token'):
                    config.pop(key, None)
                for group in ('principals', 'identities'):
                    for name in list(config.get(group, {})):
                        if name in added:
                            del config[group][name]
                            continue
                        for key in ('not_before', 'expires_at', 'revoked', 'command_grants'):
                            config[group][name].pop(key, None)
                setup.write(setup.OUT / role / 'config.json', config)
            shutil.rmtree(setup.OUT / 'servicing')
            setup.write(setup.OUT / 'ready.json', {'version': 1})
            with contextlib.redirect_stdout(output):
                setup.setup()
            upgraded = setup.read('api')
            self.assertEqual(upgraded['version'], 2)
            self.assertEqual(upgraded['principals']['crm-sg']['token'], original_token)
            self.assertEqual((setup.OUT / 'api/tls.crt').read_bytes(), original_cert)
            self.assertLessEqual(upgraded['principals']['crm-sg']['expires_at'], setup.certificate_expiry('api'))
            with contextlib.redirect_stdout(output):
                setup.change_identity('crm-sg')
            self.assertTrue(setup.read('owner')['principals']['crm-sg']['revoked'])
            self.assertTrue(setup.read('api')['principals']['crm-sg']['revoked'])
            with contextlib.redirect_stdout(output):
                setup.setup()  # Ordinary startup must not reactivate a revoked identity.
            self.assertTrue(setup.read('api')['principals']['crm-sg']['revoked'])
            with contextlib.redirect_stdout(output):
                setup.change_identity('crm-sg', rotate=True)
                setup.change_identity('peer-uk', rotate=True, workload=True)
                setup.change_identity('import-peer-uk', rotate=True, workload=True)
                setup.change_identity('case-export-uk', workload=True)
            self.assertTrue(setup.read('servicing')['export_identities']['peer-uk']['revoked'])
            with contextlib.redirect_stdout(output):
                setup.change_identity('case-export-uk', rotate=True, workload=True)
            rotated = setup.read('api')['principals']['crm-sg']
            self.assertNotEqual(rotated['token'], original_token)
            self.assertFalse(rotated['revoked'])
            self.assertEqual(setup.read('owner')['identities']['peer-uk']['token'], setup.read('peer-uk')['authority_token'])
            self.assertEqual(setup.read('owner')['peers']['STORE-GB-01']['import_token'], setup.read('peer-uk')['import_credential']['token'])
            self.assertEqual(setup.read('servicing')['export_identities']['peer-uk']['token'], setup.read('peer-uk')['servicing_token'])
            self.assertNotIn(original_token, output.getvalue())
            self.assertNotIn(rotated['token'], output.getvalue())
            self.assertEqual((setup.OUT / 'api/config.json').stat().st_mode & 0o777, 0o600)
            unknown = setup.read('owner')
            unknown['identities']['unexpected'] = copy.deepcopy(unknown['identities']['api'])
            setup.write(setup.OUT / 'owner/config.json', unknown)
            with self.assertRaises(SystemExit), contextlib.redirect_stdout(output):
                setup.setup()


if __name__ == '__main__':
    unittest.main()
