import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from admin.registry import Registry, RegistryError


def competing_writer(folder, ready, release, results):
    registry = Registry(folder)
    plan = registry.plan('observability', {'desired_state': 'enabled'})
    ready.put(True)
    release.wait(10)
    try:
        registry.save(plan, str(uuid.uuid4()))
        results.put('saved')
    except RegistryError:
        results.put('conflict')


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.registry = Registry(self.folder.name)
        self.payload = {'id': 'STORE-DE-01', 'name': 'Germany', 'country': 'DE', 'node_count': 3}

    def save(self, action, payload):
        return self.registry.save(self.registry.plan(action, payload), str(uuid.uuid4()))

    def test_registration_persists_nodes_and_management_receipt(self):
        receipt = self.save('register_store', self.payload)
        current = Registry(self.folder.name).read()
        self.assertEqual(current['revision'], 1)
        self.assertEqual(current['history'][0]['request_id'], receipt['request_id'])
        self.assertEqual([n['id'] for n in current['stores'][-1]['nodes']], ['STORE-DE-01-N01', 'STORE-DE-01-N02', 'STORE-DE-01-N03'])
        self.assertEqual(current['stores'][-1]['desired_state'], 'enabled')
        self.assertEqual(self.registry.path.stat().st_mode & 0o777, 0o600)

    def test_invalid_requests_never_write(self):
        before = self.registry.read()
        invalid = [dict(self.payload, id='STORE-SG-01'), dict(self.payload, id='../escape'),
                   dict(self.payload, country='ZZ'), dict(self.payload, country=[]),
                   dict(self.payload, name='Germany\x1b[31m'), dict(self.payload, node_count=True),
                   dict(self.payload, node_count=0), dict(self.payload, node_count=10),
                   dict(self.payload, target_url='http://secret.invalid')]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(RegistryError):
                self.registry.plan('register_store', payload)
        for payload in ({'desired_state': []}, {'desired_state': 'enabled', 'business_audit': False}):
            with self.assertRaises(RegistryError):
                self.registry.plan('observability', payload)
        self.assertEqual(self.registry.read(), before)

    def test_node_reduction_retains_ids_and_growth_reuses_them(self):
        self.save('register_store', self.payload)
        self.save('configure_store', {'id': 'STORE-DE-01', 'desired_state': 'enabled', 'node_count': 1})
        nodes = self.registry.read()['stores'][-1]['nodes']
        self.assertEqual([n['desired_state'] for n in nodes], ['enabled', 'suspended', 'suspended'])
        self.save('configure_store', {'id': 'STORE-DE-01', 'desired_state': 'enabled', 'node_count': 3})
        self.assertEqual([n['id'] for n in nodes], [n['id'] for n in self.registry.read()['stores'][-1]['nodes']])

    def test_stale_review_and_uuid_conflict_are_rejected(self):
        plan = self.registry.plan('register_store', self.payload)
        self.save('observability', {'desired_state': 'suspended'})
        with self.assertRaisesRegex(RegistryError, 'since review'):
            self.registry.save(plan, str(uuid.uuid4()))
        plan = self.registry.plan('register_store', self.payload)
        request = str(uuid.uuid4())
        receipt = self.registry.save(plan, request)
        self.assertTrue(self.registry.save(plan, request)['replayed'])
        other = self.registry.plan('observability', {'desired_state': 'enabled'})
        with self.assertRaisesRegex(RegistryError, 'different input'):
            self.registry.save(other, request)
        self.assertEqual(len(self.registry.read()['history']), receipt['revision'])

    def test_real_process_lock_prevents_lost_updates(self):
        self.registry.read()
        context = multiprocessing.get_context('fork')
        ready, results, release = context.Queue(), context.Queue(), context.Event()
        workers = [context.Process(target=competing_writer, args=(self.folder.name, ready, release, results)) for _ in range(2)]
        for worker in workers:
            worker.start()
        try:
            for _ in workers:
                self.assertTrue(ready.get(timeout=10))
            release.set()
            self.assertEqual(sorted(results.get(timeout=10) for _ in workers), ['conflict', 'saved'])
        finally:
            release.set()
            for worker in workers:
                worker.join(10)
                if worker.is_alive():worker.terminate()
        self.assertEqual(self.registry.read()['revision'], 1)

    def test_corruption_unknown_version_and_symlink_do_not_reset(self):
        self.registry.read()
        for raw in ('{"schema_version":99}', '{"secret":"sensitive-canary","bad":', '{"schema_version":1,"schema_version":1}'):
            self.registry.path.write_text(raw)
            with self.assertRaises(RegistryError) as raised:
                self.registry.read()
            self.assertNotIn('sensitive-canary', str(raised.exception))
            self.assertEqual(self.registry.path.read_text(), raw)
        self.registry.path.unlink()
        target = Path(self.folder.name) / 'target'
        target.write_text('keep')
        self.registry.path.symlink_to(target)
        with self.assertRaises(RegistryError):self.registry.read()
        self.assertEqual(target.read_text(), 'keep')

    def test_failed_replace_keeps_prior_configuration_and_receipts(self):
        plan = self.registry.plan('register_store', self.payload)
        before = self.registry.path.read_bytes()
        with patch('admin.registry.os.replace', side_effect=OSError('private-error-canary')):
            with self.assertRaises(RegistryError):self.registry.save(plan, str(uuid.uuid4()))
        self.assertEqual(self.registry.path.read_bytes(), before)
        self.assertEqual(list(Path(self.folder.name).glob('.state-*')), [])

    def test_uncertain_post_replace_failure_can_replay_same_uuid(self):
        plan = self.registry.plan('register_store', self.payload)
        request = str(uuid.uuid4())
        import os
        real_fsync = os.fsync
        calls = []
        def fsync(fd):
            calls.append(fd)
            if len(calls) == 2:raise OSError('directory fsync interrupted')
            return real_fsync(fd)
        with patch('admin.registry.os.fsync', side_effect=fsync):
            with self.assertRaises(RegistryError):self.registry.save(plan, request)
        # Replays must complete fsync too; seeing the receipt alone cannot prove
        # durability after the original directory fsync failed.
        with patch('admin.registry.os.fsync', side_effect=OSError('storage still unavailable')):
            with self.assertRaises(RegistryError):self.registry.save(plan, request)
        self.assertTrue(self.registry.save(plan, request)['replayed'])
        self.assertEqual(self.registry.read()['revision'], 1)

    def test_observability_intent_is_independent_of_stores(self):
        stores = self.registry.read()['stores']
        self.save('observability', {'desired_state': 'suspended'})
        self.assertEqual(self.registry.read()['stores'], stores)
        self.assertEqual(self.registry.read()['observability'], {'desired_state': 'suspended'})

    def test_cli_json_persists_across_processes_and_requires_review_revision(self):
        command = [sys.executable, '-m', 'admin', '--state-dir', self.folder.name]
        output = subprocess.run(command + ['plan', 'register_store', '--payload', json.dumps(self.payload)], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(output.stdout)['base_revision'], 0)
        request = str(uuid.uuid4())
        save = command + ['save', 'register_store', '--payload', json.dumps(self.payload), '--expected-revision', '0', '--request-id', request]
        self.assertEqual(subprocess.run(save, capture_output=True).returncode, 0)
        self.assertTrue(json.loads(subprocess.check_output(save))['replayed'])
        current = json.loads(subprocess.check_output(command + ['config']))
        self.assertEqual(current['stores'][-1]['id'], 'STORE-DE-01')


if __name__ == '__main__':unittest.main()
