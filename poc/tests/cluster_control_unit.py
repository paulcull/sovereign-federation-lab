"""Controller failure-path units. SQL integration evidence is a separate gate."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
import unittest
import uuid
from fastapi import HTTPException
from cluster_control.service import CANARY, ClusterControl, Operation, STEPS

class Receipt:
    def fetchone(self): return (1234567890123456789,)
    def fetchall(self): return CANARY

class FailureControl(ClusterControl):
    def __init__(self, failure):
        super().__init__(); self.failure = failure; self.records = []; self.sql_statements = []
    def snapshot(self, key): return {'status':'healthy', 'locality_matches':True, 'recovery_ready':True}
    @contextmanager
    def connect(self, key, **kwargs): yield self
    def cursor(self): return self
    def executemany(self, *args): pass
    def execute(self, *args):
        # Worker execute is invoked explicitly below; this is the native SQL port.
        raise AssertionError('Use SQL facade')
    def update(self, key, job, state, steps, result=None, **kwargs):
        receipt = 'backup_job_id' if self.failure == 'lost_backup_journal' else 'restore_job_id'
        if self.failure in ('lost_backup_journal', 'lost_restore_journal') and receipt in (result or {}):
            raise ConnectionError('simulated journal outage after receipt')
        self.records.append((state,deepcopy(steps),deepcopy(result)))

class SQL:
    def __init__(self, controller): self.controller = controller
    def cursor(self): return self
    def executemany(self, *args): pass
    def execute(self, query, *args):
        text = str(query)
        self.controller.sql_statements.append(text)
        if 'BACKUP DATABASE' in text and self.controller.failure == 'stop_after_backup':
            self.controller.stop.set()
        if 'RESTORE DATABASE' in text and self.controller.failure == 'lost_restore_response':
            raise ConnectionError('simulated lost response; no business database involved')
        if 'SELECT id,value' in text and self.controller.failure == 'validation_read_failure':
            raise ConnectionError('simulated lost verification response')
        return Receipt()

class RecoveryFailureTests(unittest.TestCase):
    def run_failure(self, failure):
        control = FailureControl(failure)
        @contextmanager
        def connect(*args, **kwargs): yield SQL(control)
        control.connect = connect
        steps = [{'label':label,'state':'pending'} for label in STEPS['recovery_rehearsal']]
        ClusterControl.execute(control,'in',uuid.uuid4(),'recovery_rehearsal',steps)
        return control
    def test_stop_after_native_backup_requires_inspection_and_retains_receipt(self):
        c = self.run_failure('stop_after_backup')
        self.assertEqual(c.records[-1][0], 'interrupted')
        self.assertEqual(c.records[-1][2]['backup_job_id'], '1234567890123456789')
    def test_lost_restore_response_requires_inspection_and_retains_backup_receipt(self):
        c = self.run_failure('lost_restore_response')
        self.assertEqual(c.records[-1][0], 'interrupted')
        self.assertEqual(c.records[-1][2]['backup_job_id'], '1234567890123456789')
        self.assertEqual(c.records[-1][1][3]['state'], 'interrupted')
    def test_preflight_failure_is_retryable_without_mutation(self):
        c = FailureControl('preflight')
        c.snapshot = lambda key: {'status':'unreachable'}
        steps = [{'label':label,'state':'pending'} for label in STEPS['recovery_rehearsal']]
        ClusterControl.execute(c,'in',uuid.uuid4(),'recovery_rehearsal',steps)
        self.assertEqual(c.records[-1][0], 'failed')
    def test_validation_failure_retains_both_native_job_receipts(self):
        c = self.run_failure('validation_read_failure')
        self.assertEqual(c.records[-1][0], 'interrupted')
        self.assertEqual(c.records[-1][2]['backup_job_id'], '1234567890123456789')
        self.assertEqual(c.records[-1][2]['restore_job_id'], '1234567890123456789')
    def test_low_disk_headroom_rejects_recovery_before_mutation(self):
        c = FailureControl('disk')
        c.snapshot = lambda key: {'status':'healthy','locality_matches':True,'recovery_ready':False}
        steps = [{'label':label,'state':'pending'} for label in STEPS['recovery_rehearsal']]
        ClusterControl.execute(c,'in',uuid.uuid4(),'recovery_rehearsal',steps)
        self.assertEqual(c.records[-1][0], 'failed')
        self.assertEqual(c.records[-1][1][1]['state'], 'pending')

    def test_failed_step_and_terminal_journaling_retry_receipts_without_native_replay(self):
        for failure in ('lost_backup_journal', 'lost_restore_journal'):
            with self.subTest(failure=failure):
                c = self.run_failure(failure)
                pending = c.pending_updates['in']
                self.assertEqual(pending['state'], 'interrupted')
                self.assertEqual(pending['result']['backup_job_id'], '1234567890123456789')
                if failure == 'lost_restore_journal':
                    self.assertEqual(pending['result']['restore_job_id'], '1234567890123456789')
                native = list(c.sql_statements)
                self.assertEqual(sum('BACKUP DATABASE' in s for s in native), 1)
                self.assertEqual(sum('RESTORE DATABASE' in s for s in native), int(failure == 'lost_restore_journal'))
                with self.assertRaises(ConnectionError):
                    c.flush_pending_update('in')
                self.assertIn('in', c.pending_updates)
                c.failure = 'recovered'
                c.flush_pending_update('in')
                self.assertNotIn('in', c.pending_updates)
                self.assertEqual(c.records[-1][0], 'interrupted')
                self.assertEqual(c.records[-1][2], pending['result'])
                self.assertEqual(c.sql_statements, native)

    def test_failed_health_checks_retain_observed_values_without_success_claim(self):
        for nodes, locality in [([], False), ([{'status':'live'}], False), ([{'status':'not-live'}], True)]:
            with self.subTest(nodes=nodes, locality=locality):
                c = FailureControl('health')
                c.snapshot = lambda key: {'sql':True, 'status':'attention', 'nodes':nodes, 'locality_matches':locality}
                steps = [{'label':label, 'state':'pending'} for label in STEPS['health_check']]
                ClusterControl.execute(c, 'sg', uuid.uuid4(), 'health_check', steps)
                state, _, result = c.records[-1]
                self.assertEqual(state, 'failed')
                self.assertEqual(result['live_nodes'], sum(n['status']=='live' for n in nodes))
                self.assertEqual(result['locality_matches'], locality)
                self.assertTrue(all('summary' not in (r or {}) for _, _, r in c.records))

    def test_health_summary_follows_all_successful_checks(self):
        c = FailureControl('health')
        c.snapshot = lambda key: {'sql':True, 'status':'healthy', 'nodes':[{'status':'live'}], 'locality_matches':True}
        steps = [{'label':label, 'state':'pending'} for label in STEPS['health_check']]
        ClusterControl.execute(c, 'sg', uuid.uuid4(), 'health_check', steps)
        self.assertEqual(c.records[-1][0], 'succeeded')
        self.assertIn('summary', c.records[-1][2])
        for _, observed_steps, result in c.records:
            if 'summary' in (result or {}):
                self.assertTrue(all(s['state']=='succeeded' for s in observed_steps))

    def test_lost_enqueue_commit_acknowledgement_reports_uncertainty(self):
        committed = []
        class Connection:
            @contextmanager
            def transaction(self):
                yield
                committed.append(True)
                raise ConnectionError('simulated lost COMMIT acknowledgement')
            def execute(self, query, *args):
                value = None if 'SELECT id,kind' in query else (0,)
                return SimpleNamespace(fetchone=lambda: value)
        c = ClusterControl()
        @contextmanager
        def connect(*args, **kwargs):
            yield Connection()
        c.connect = connect
        with self.assertRaises(HTTPException) as caught:
            c.enqueue('sg', Operation(kind='health_check', request_id=uuid.uuid4()))
        self.assertEqual(committed, [True])
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn('uncertain', caught.exception.detail)
        self.assertIn('same request identifier', caught.exception.detail)

if __name__ == '__main__': unittest.main()
