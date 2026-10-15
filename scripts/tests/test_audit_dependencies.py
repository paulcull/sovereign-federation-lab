"""Audit orchestration regressions; scanner/CLI stubs never stand in for lab SQL."""
import contextlib
import importlib.util
import io
import json
import multiprocessing
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'audit_dependencies', Path(__file__).resolve().parents[1] / 'audit_dependencies.py')
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def overlapping_invocation(output, label, started, entered, release, results):
    """Separate process, real file lock; only the scanner body is substituted."""
    def scan(args, output, reports, summary):
        summary['commit'] = label
        entered.set()
        if not release.wait(10):
            raise RuntimeError('Test did not release the simulated scanner')
        return label == 'newer-failure'

    with patch.object(AUDIT, 'audit', side_effect=scan), contextlib.redirect_stdout(io.StringIO()):
        started.set()
        code = AUDIT.main(['--output', output])
    results.put((label, code))


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)
        self.python_code = 0
        self.python_report = {'dependencies': [{'name': 'example', 'version': '1', 'vulns': []}]}
        self.images = ['vendor:test', 'runtime:local']
        self.scan_code = 0
        self.vulnerabilities = []
        self.missing_image = False
        self.bad_image = False
        self.wrong_image = False
        self.empty_results = False
        self.no_packages = False
        self.omitted_vulnerabilities = False
        self.non_dict_result = False
        self.interrupt = False
        self.missing_tool = False
        self.initial_evidence_observed = False
        self.trivy_calls = []

    def output_command(self, command, **kwargs):
        if command[:2] == ['git', 'rev-parse']:
            current = json.loads((self.output / 'summary.json').read_text())
            self.assertFalse(current['passed'])
            self.assertFalse(current['completed'])
            self.assertEqual(current['status'], 'incomplete')
            self.initial_evidence_observed = True
            return 'current-commit\n'
        if command[:2] == ['git', 'status']:
            return ''
        if command[:2] == ['trivy', 'version']:
            self.trivy_calls.append((command, kwargs['env']))
            if self.missing_tool:
                raise FileNotFoundError('tool unavailable')
            return '{"Version":"test"}'
        if command[:2] == ['docker', 'compose']:
            return '\n'.join(self.images)
        if command[:3] == ['docker', 'image', 'inspect']:
            if self.missing_image:
                raise subprocess.CalledProcessError(1, command)
            return json.dumps([{'Id': 'sha256:' + command[-1], 'RepoDigests': []}])
        self.fail('Unexpected CLI command')

    def run_command(self, command, **kwargs):
        report = Path(command[command.index('--output') + 1])
        # Old filenames are deliberately not reused, including within one image
        # scan batch. This assertion also protects against command failure reuse.
        self.assertFalse(report.exists())
        if command[0] == 'pip-audit':
            if self.python_report is not None:
                report.write_text(json.dumps(self.python_report))
            return SimpleNamespace(returncode=self.python_code)
        self.trivy_calls.append((command, kwargs['env']))
        if self.interrupt:
            raise KeyboardInterrupt()
        if self.scan_code:
            return SimpleNamespace(returncode=self.scan_code)
        data = {'SchemaVersion': 2, 'ArtifactType': 'container_image',
                'Metadata': {'ImageID': 'wrong-image' if self.wrong_image else command[-1]},
                'Results': [{'Vulnerabilities': self.vulnerabilities,
                             'Packages': [{'Name': 'example', 'Version': '1'}]}]}
        if self.empty_results:
            data['Results'] = []
        if self.no_packages:
            del data['Results'][0]['Packages']
        if self.omitted_vulnerabilities:
            del data['Results'][0]['Vulnerabilities']
        if self.non_dict_result:
            data['Results'].append('invalid result')
        report.write_text('{' if self.bad_image else json.dumps(data))
        return SimpleNamespace(returncode=0)

    def invoke(self):
        with patch.object(AUDIT.subprocess, 'check_output', side_effect=self.output_command), \
             patch.object(AUDIT.subprocess, 'run', side_effect=self.run_command), \
             contextlib.redirect_stdout(io.StringIO()):
            code = AUDIT.main(['--output', str(self.output)])
        summary = json.loads((self.output / 'summary.json').read_text())
        self.assertTrue(self.initial_evidence_observed)
        self.assertFalse(list(self.output.glob('.summary-*.tmp')))
        return code, summary

    def test_clean_completed_scan_can_pass_and_reports_are_current(self):
        code, summary = self.invoke()
        self.assertEqual(code, 0)
        self.assertTrue(summary['passed'])
        self.assertTrue(summary['completed'])
        self.assertEqual(summary['commit'], 'current-commit')
        self.assertEqual(len(summary['images']), 2)
        for relative in [summary['python']['report']] + [image['report'] for image in summary['images']]:
            self.assertEqual(Path(relative).parts[0], 'run-' + summary['run_id'])
            self.assertTrue((self.output / relative).is_file())

    def test_execution_failure_replaces_old_pass_and_cannot_consume_old_report(self):
        self.assertEqual(self.invoke()[0], 0)
        # Also seed the former shared report path: failed pip-audit must not read it.
        (self.output / 'python.json').write_text(json.dumps(self.python_report))
        self.python_report = None
        self.python_code = 1
        code, summary = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertFalse(summary['passed'])
        self.assertFalse(summary['completed'])
        self.assertNotIn('python', summary)
        self.assertTrue(summary['errors'])

    def test_missing_scanner_replaces_old_pass_before_discovery(self):
        self.assertEqual(self.invoke()[0], 0)
        self.missing_tool = True
        code, summary = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertEqual(summary['status'], 'incomplete')
        self.assertFalse(summary['passed'])
        self.assertTrue(summary['errors'])

    def test_skipped_python_dependency_blocks_gate(self):
        self.python_report['dependencies'][0]['skip_reason'] = 'unsupported source'
        code, summary = self.invoke()
        self.assertEqual(code, 1)
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['python']['skipped_packages'], ['example'])

    def test_python_advisory_blocks_gate(self):
        self.python_report['dependencies'][0]['vulns'] = [{'id': 'CVE-example'}]
        self.python_code = 1
        code, summary = self.invoke()
        self.assertEqual(code, 1)
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['python']['advisory_records'], 1)

    def test_missing_python_package_evidence_cannot_mean_no_advisories(self):
        for dependency in [{'name': 'example', 'version': '1'},
                           {'name': 'example', 'vulns': []}]:
            with self.subTest(dependency=dependency):
                self.python_report = {'dependencies': [dependency]}
                code, summary = self.invoke()
                self.assertNotEqual(code, 0)
                self.assertFalse(summary['passed'])
                self.assertFalse(summary['completed'])

    def test_fixable_high_blocks_and_unfixed_findings_remain_visible(self):
        self.vulnerabilities = [
            {'VulnerabilityID': 'CVE-fixable', 'Severity': 'HIGH', 'FixedVersion': '2'},
            {'VulnerabilityID': 'CVE-unfixed', 'Severity': 'CRITICAL'}]
        code, summary = self.invoke()
        self.assertEqual(code, 1)
        self.assertFalse(summary['passed'])
        self.assertTrue(summary['completed'])
        self.assertEqual(summary['images'][0]['fixable_high_critical'], 1)
        self.assertEqual(summary['images'][0]['unfixed_advisory_ids'], ['CVE-unfixed'])
        self.assertEqual(summary['images'][0]['counts'], {'HIGH': 1, 'CRITICAL': 1})

    def test_failed_missing_or_invalid_image_scans_cannot_pass(self):
        for attribute, value in [('scan_code', 1), ('missing_image', True),
                                 ('bad_image', True), ('wrong_image', True)]:
            with self.subTest(failure=attribute):
                setattr(self, attribute, value)
                code, summary = self.invoke()
                self.assertNotEqual(code, 0)
                self.assertFalse(summary['passed'])
                self.assertFalse(summary['completed'])
                self.assertTrue(summary['errors'])
                setattr(self, attribute, False if isinstance(value, bool) else 0)

    def test_empty_compose_image_inventory_cannot_pass(self):
        self.images = []
        code, summary = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertFalse(summary['passed'])
        self.assertFalse(summary['completed'])

    def test_successful_scanner_with_no_package_inventory_cannot_pass(self):
        for attribute in ('empty_results', 'no_packages'):
            with self.subTest(failure=attribute):
                setattr(self, attribute, True)
                code, summary = self.invoke()
                self.assertNotEqual(code, 0)
                self.assertFalse(summary['passed'])
                self.assertFalse(summary['completed'])
                self.assertTrue(summary['errors'])
                setattr(self, attribute, False)

    def test_present_malformed_vulnerabilities_cannot_mean_no_findings(self):
        for vulnerabilities in ({}, '', None):
            with self.subTest(vulnerabilities=vulnerabilities):
                self.vulnerabilities = vulnerabilities
                code, summary = self.invoke()
                self.assertNotEqual(code, 0)
                self.assertFalse(summary['passed'])
                self.assertFalse(summary['completed'])
                self.assertIn('malformed vulnerability evidence', summary['errors'][0])

    def test_every_image_result_must_be_an_object(self):
        self.non_dict_result = True
        code, summary = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertFalse(summary['passed'])
        self.assertFalse(summary['completed'])
        self.assertIn('malformed vulnerability evidence', summary['errors'][0])

    def test_malformed_vulnerability_fields_cannot_bypass_severity_gate(self):
        for vulnerability in [None, {},
                {'VulnerabilityID': 'CVE-test', 'Severity': None, 'FixedVersion': '2'},
                {'VulnerabilityID': 'CVE-test', 'Severity': 'high', 'FixedVersion': '2'},
                {'VulnerabilityID': '', 'Severity': 'HIGH', 'FixedVersion': '2'},
                {'VulnerabilityID': 'CVE-test', 'Severity': 'HIGH', 'FixedVersion': False}]:
            with self.subTest(vulnerability=vulnerability):
                self.vulnerabilities = [vulnerability]
                code, summary = self.invoke()
                self.assertNotEqual(code, 0)
                self.assertFalse(summary['passed'])
                self.assertFalse(summary['completed'])
                self.assertIn('malformed vulnerability fields', summary['errors'][0])

    def test_omitted_vulnerabilities_is_valid_for_clean_package_inventory(self):
        self.omitted_vulnerabilities = True
        code, summary = self.invoke()
        self.assertEqual(code, 0)
        self.assertTrue(summary['passed'])
        self.assertTrue(summary['completed'])
        self.assertTrue(all(image['counts'] == {} for image in summary['images']))

    def test_overlapping_invocations_serialize_through_final_publication(self):
        context = multiprocessing.get_context('spawn')
        results = context.Queue()
        started = [context.Event(), context.Event()]
        entered = [context.Event(), context.Event()]
        release = [context.Event(), context.Event()]
        labels = ['older-success', 'newer-failure']
        processes = [context.Process(target=overlapping_invocation,
            args=(str(self.output), labels[index], started[index], entered[index], release[index], results))
            for index in range(2)]
        try:
            processes[0].start()
            self.assertTrue(entered[0].wait(10))
            original = json.loads((self.output / 'summary.json').read_text())
            self.assertFalse(original['passed'])
            processes[1].start()
            self.assertTrue(started[1].wait(10))
            self.assertFalse(entered[1].wait(.5), 'Second audit entered before the first released its lock')
            # A waiter cannot even publish its initial incomplete summary yet.
            self.assertEqual(json.loads((self.output / 'summary.json').read_text())['run_id'], original['run_id'])
            release[0].set()
            self.assertTrue(entered[1].wait(10))
            processes[0].join(10)
            self.assertEqual(processes[0].exitcode, 0)
            current = json.loads((self.output / 'summary.json').read_text())
            self.assertNotEqual(current['run_id'], original['run_id'])
            self.assertFalse(current['passed'])
            release[1].set()
            processes[1].join(10)
            self.assertEqual(processes[1].exitcode, 0)
            self.assertEqual(dict(results.get(timeout=5) for _ in range(2)),
                             {'older-success': 0, 'newer-failure': 1})
            final = json.loads((self.output / 'summary.json').read_text())
            self.assertEqual(final['commit'], 'newer-failure')
            self.assertFalse(final['passed'])
            self.assertTrue(final['completed'])
            self.assertEqual(final['status'], 'failed')
            self.assertFalse(list(self.output.glob('.summary-*.tmp')))
        finally:
            for event in release:
                event.set()
            for process in processes:
                if process.pid is not None:
                    process.join(10)
                    if process.is_alive():
                        process.terminate()
                        process.join(10)
            results.close()
            results.join_thread()

    def test_interruption_persists_current_failed_evidence(self):
        self.interrupt = True
        code, summary = self.invoke()
        self.assertEqual(code, 130)
        self.assertFalse(summary['passed'])
        self.assertFalse(summary['completed'])
        self.assertIn('interrupted', summary['errors'][0])

    def test_ambient_filters_cannot_narrow_scanner_coverage(self):
        supplied = {'TRIVY_SEVERITY': 'LOW', 'TRIVY_IGNORE_UNFIXED': 'true',
                    'TRIVY_SKIP_FILES': '**', 'TRIVY_SKIP_DIRS': '**',
                    'TRIVY_CONFIG': '/untrusted/filters.yaml', 'TRIVY_IGNORE_STATUS': 'affected',
                    'TRIVY_IGNORE_POLICY': '/untrusted/ignore.rego',
                    'TRIVY_CACHE_DIR': '/test/cache', 'TRIVY_DB_REPOSITORY': 'test.example/db:2',
                    'TRIVY_PASSWORD': 'synthetic-secret', 'TRIVY_CACERT': '/test/ca.pem',
                    'HTTPS_PROXY': 'http://test.proxy', 'SSL_CERT_FILE': '/test/ca.pem',
                    'DOCKER_CONFIG': '/test/docker'}
        with patch.dict(AUDIT.os.environ, supplied, clear=True):
            code, summary = self.invoke()
        self.assertEqual(code, 0)
        self.assertTrue(summary['passed'])
        self.assertEqual(len(self.trivy_calls), 3)
        for command, environment in self.trivy_calls:
            self.assertEqual(command[command.index('--config') + 1], '')
            self.assertEqual(environment, {key: value for key, value in supplied.items()
                if not key.startswith('TRIVY_') or key in AUDIT.TRIVY_ENVIRONMENT})
            if command[1] == 'image':
                self.assertEqual(command[command.index('--severity') + 1], 'UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL')
                self.assertEqual(command[command.index('--ignorefile') + 1], '')
                self.assertEqual(command[command.index('--pkg-types') + 1], 'os,library')
                self.assertIn('--ignore-unfixed=false', command)
                self.assertIn('--ignore-status=', command)
                self.assertIn('--list-all-pkgs=true', command)
        self.assertNotIn('synthetic-secret', (self.output / 'summary.json').read_text())


if __name__ == '__main__':
    unittest.main()
