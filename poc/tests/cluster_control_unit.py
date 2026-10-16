"""Controller failure-path units. SQL integration evidence is a separate gate."""
from contextlib import contextmanager
from copy import deepcopy
import unittest
import uuid
from cluster_control.service import CANARY, ClusterControl, STEPS

class Receipt:
    def fetchone(self): return (1234567890123456789,)
    def fetchall(self): return CANARY

class FailureControl(ClusterControl):
    def __init__(self, failure):
        super().__init__(); self.failure = failure; self.records = []
    def snapshot(self, key): return {'status':'healthy', 'locality_matches':True, 'recovery_ready':True}
    @contextmanager
    def connect(self, key, **kwargs): yield self
    def cursor(self): return self
    def executemany(self, *args): pass
    def execute(self, *args):
        # Worker execute is invoked explicitly below; this is the native SQL port.
        raise AssertionError('Use SQL facade')
    def update(self, key, job, state, steps, result=None, **kwargs):
        self.records.append((state,deepcopy(steps),deepcopy(result)))

class SQL:
    def __init__(self, controller): self.controller = controller
    def cursor(self): return self
    def executemany(self, *args): pass
    def execute(self, query, *args):
        text = str(query)
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

if __name__ == '__main__': unittest.main()
