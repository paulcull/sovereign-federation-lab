"""Audit orchestration regressions; scanner/CLI stubs never stand in for lab SQL."""
import contextlib
from datetime import datetime, timezone
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
        self.repo_digests = {}
        self.risk_context = None
        self.policy_path = AUDIT.RISK_POLICY
        self.now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)

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
            return json.dumps([{'Id': 'sha256:' + command[-1],
                                'RepoDigests': self.repo_digests.get(command[-1], [])}])
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
             patch.object(AUDIT, 'RISK_POLICY', self.policy_path), \
             patch.object(AUDIT, 'utc_now', side_effect=lambda: self.now), \
             contextlib.redirect_stdout(io.StringIO()):
            arguments = ['--output', str(self.output)]
            if self.risk_context is not None:
                arguments += ['--risk-context', self.risk_context]
            code = AUDIT.main(arguments)
        summary = json.loads((self.output / 'summary.json').read_text())
        self.assertTrue(self.initial_evidence_observed)
        self.assertFalse(list(self.output.glob('.summary-*.tmp')))
        return code, summary

    def prepare_risk(self):
        self.policy = json.loads(AUDIT.RISK_POLICY.read_text())
        self.record = self.policy['acceptances'][0]
        self.assertEqual(self.record['cve'], 'CVE-2025-68121')
        # Isolate one record for classifier/expiry failure-path tests. The
        # complete shipped register is verified against the observed inventory below.
        self.policy['acceptances'] = [self.record]
        self.policy_path = self.output / 'risk-acceptances.json'
        self.write_policy()
        self.risk_context = 'synthetic-lab'
        self.images = [self.record['image']]
        reference, digest = self.record['image'].split('@', 1)
        self.repo_digests[self.record['image']] = [reference.rsplit(':', 1)[0] + '@' + digest]
        self.vulnerabilities = [{'VulnerabilityID': self.record['cve'],
            'PkgName': self.record['package'], 'InstalledVersion': self.record['installed_version'],
            'Severity': self.record['severity'], 'FixedVersion': '1.26.9'}]

    def write_policy(self):
        self.policy_path.write_text(json.dumps(self.policy))

    def prepare_full_cockroach_risk(self):
        self.prepare_risk()
        self.policy = json.loads(AUDIT.RISK_POLICY.read_text())
        self.write_policy()
        snapshot = json.loads((AUDIT.ROOT / 'docs/security/dependency-recheck-2026-10-16.json').read_text())
        image = next(i for i in snapshot['images'] if self.record['image'] in i['tags'])
        self.vulnerabilities = image['blocking_findings']

    def test_shipped_register_accepts_exactly_the_observed_cockroach_findings(self):
        self.prepare_full_cockroach_risk()
        expected = {(v['VulnerabilityID'], v['PkgName'], v['InstalledVersion'], v['Severity'])
                    for v in self.vulnerabilities}
        records = [r for r in self.policy['acceptances'] if r['image'] == self.record['image']]
        self.assertEqual(len(records), 34)
        self.assertEqual({(r['cve'], r['package'], r['installed_version'], r['severity'])
                          for r in records}, expected)
        self.assertEqual({r['expires_at'] for r in self.policy['acceptances']}, {'2026-11-15T00:00:00Z'})
        code, summary = self.invoke()
        self.assertEqual(code, 0)
        self.assertTrue(summary['passed'])
        self.assertEqual(summary['status'], 'passed_with_risk_acceptance')
        self.assertEqual(summary['accepted_high_critical'], 34)
        self.assertEqual(summary['unaccepted_fixable_high_critical'], 0)
        self.assertEqual(summary['images'][0]['counts'], {'HIGH': 33, 'CRITICAL': 1})
        raw = json.loads((self.output / summary['images'][0]['report']).read_text())
        self.assertEqual(raw['Results'][0]['Vulnerabilities'], self.vulnerabilities)

    def observability_requests(self):
        return json.loads((AUDIT.ROOT / 'docs/security/'
            'non-cockroach-exception-requests-2026-10-16.json').read_text())['requests']

    def prepare_observability_risk(self, request):
        self.risk_context = 'synthetic-lab'
        self.now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
        self.images = [request['image']]
        self.repo_digests = {request['image']: request['repo_digests'][:]}
        self.vulnerabilities = [dict(finding) for finding in request['findings']]

    def test_shipped_observability_register_matches_only_the_approved_scopes(self):
        policy = json.loads(AUDIT.RISK_POLICY.read_text())['acceptances']
        self.assertEqual(len(policy), 57)
        requests = self.observability_requests()
        records = [r for r in policy if not r['image'].startswith('cockroachdb/')]
        expected = {(request['image'], finding['VulnerabilityID'], finding['PkgName'],
                     finding['InstalledVersion'], finding['Severity'])
                    for request in requests for finding in request['findings']}
        self.assertEqual(len(expected), 23)
        self.assertEqual(len(records), 23)
        self.assertEqual({(r['image'], r['cve'], r['package'], r['installed_version'], r['severity'])
                          for r in records}, expected)
        self.assertEqual({r['id'] for r in records},
                         {f'SFL-RA-{number:04d}' for number in range(35, 58)})
        self.assertEqual({r['id'] for r in records},
                         {risk_id for request in requests for risk_id in request['active_acceptance_ids']})
        self.assertEqual({r['context'] for r in records}, {'synthetic-lab'})
        self.assertEqual({r['owner'] for r in records}, {'paulcull'})
        self.assertEqual({r['expires_at'] for r in records}, {'2026-11-15T00:00:00Z'})

    def test_observability_acceptances_retain_all_64_raw_finding_instances(self):
        accepted = 0
        for request in self.observability_requests():
            with self.subTest(component=request['component']):
                self.prepare_observability_risk(request)
                code, summary = self.invoke()
                self.assertEqual(code, 0)
                self.assertTrue(summary['passed'])
                self.assertEqual(summary['status'], 'passed_with_risk_acceptance')
                self.assertEqual(summary['accepted_high_critical'], request['finding_instances'])
                self.assertEqual(summary['unaccepted_fixable_high_critical'], 0)
                image = summary['images'][0]
                self.assertEqual(image['counts'], {'HIGH': request['finding_instances']})
                self.assertEqual({f['risk_acceptance_id'] for f in image['accepted_findings']},
                                 set(request['active_acceptance_ids']))
                raw = json.loads((self.output / image['report']).read_text())
                self.assertEqual(raw['Results'][0]['Vulnerabilities'], self.vulnerabilities)
                accepted += summary['accepted_high_critical']
        self.assertEqual(accepted, 64)

    def test_observability_acceptances_reject_new_findings_versions_and_images(self):
        for request in self.observability_requests():
            for change in ('new_cve', 'version', 'package', 'digest', 'reference'):
                with self.subTest(component=request['component'], change=change):
                    self.prepare_observability_risk(request)
                    if change == 'new_cve':
                        self.vulnerabilities.append(self.vulnerabilities[0] |
                                                   {'VulnerabilityID': 'CVE-2099-99999'})
                    elif change == 'version':
                        self.vulnerabilities[0]['InstalledVersion'] = 'unapproved-version'
                    elif change == 'package':
                        self.vulnerabilities[0]['PkgName'] = 'unapproved-package'
                    elif change == 'digest':
                        self.repo_digests[request['image']] = [
                            request['component'] + '@sha256:' + '0' * 64]
                    else:
                        image = request['component'] + ':unapproved'
                        self.images = [image]
                        self.repo_digests[image] = request['repo_digests'][:]
                    code, summary = self.invoke()
                    self.assertEqual(code, 1)
                    self.assertFalse(summary['passed'])
                    self.assertGreater(summary['unaccepted_fixable_high_critical'], 0)
                    if change in ('digest', 'reference'):
                        self.assertEqual(summary['accepted_high_critical'], 0)

    def test_observability_acceptances_require_lab_context_and_unexpired_approval(self):
        for request in self.observability_requests():
            for mode in ('strict', 'expired', 'not_yet_approved'):
                with self.subTest(component=request['component'], mode=mode):
                    self.prepare_observability_risk(request)
                    if mode == 'strict':
                        self.risk_context = None
                    elif mode == 'expired':
                        self.now = datetime(2026, 11, 15, tzinfo=timezone.utc)
                    else:
                        self.now = datetime(2026, 10, 15, tzinfo=timezone.utc)
                    code, summary = self.invoke()
                    self.assertEqual(code, 1)
                    self.assertFalse(summary['passed'])
                    self.assertEqual(summary['accepted_high_critical'], 0)
                    self.assertEqual(summary['unaccepted_fixable_high_critical'],
                                     request['finding_instances'])

    def test_full_register_cannot_accept_a_new_cockroach_finding(self):
        self.prepare_full_cockroach_risk()
        self.vulnerabilities.append({'VulnerabilityID': 'CVE-2099-99999', 'PkgName': 'stdlib',
            'InstalledVersion': self.record['installed_version'], 'Severity': 'HIGH', 'FixedVersion': 'future'})
        code, summary = self.invoke()
        self.assertEqual(code, 1)
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['accepted_high_critical'], 34)
        self.assertEqual(summary['unaccepted_fixable_high_critical'], 1)

    def test_full_register_cannot_accept_shared_cves_in_other_vendor_images(self):
        self.prepare_full_cockroach_risk()
        other = 'grafana/loki:synthetic@sha256:' + '1' * 64
        self.images.append(other)
        self.repo_digests[other] = ['grafana/loki@sha256:' + '1' * 64]
        code, summary = self.invoke()
        self.assertEqual(code, 1)
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['accepted_high_critical'], 34)
        self.assertEqual(summary['unaccepted_fixable_high_critical'], 34)
        other_image = next(i for i in summary['images'] if other in i['tags'])
        self.assertEqual(other_image['accepted_findings'], [])

    def test_exact_lab_risk_is_visible_in_success_and_original_report(self):
        self.prepare_risk()
        code, summary = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(summary['status'], 'passed_with_risk_acceptance')
        self.assertTrue(summary['passed'])
        self.assertTrue(summary['completed'])
        self.assertEqual(summary['accepted_high_critical'], 1)
        self.assertEqual(summary['unaccepted_fixable_high_critical'], 0)
        image = summary['images'][0]
        self.assertEqual(image['counts'], {'CRITICAL': 1})
        self.assertEqual(image['fixable_high_critical'], 1)
        self.assertEqual(image['accepted_findings'][0]['risk_acceptance_id'], 'SFL-RA-0001')
        raw = json.loads((self.output / image['report']).read_text())
        self.assertEqual(raw['Results'][0]['Vulnerabilities'], self.vulnerabilities)
        self.assertEqual(summary['risk_acceptances'][0]['expires_at'], self.record['expires_at'])

    def test_strict_default_never_applies_the_lab_acceptance(self):
        self.prepare_risk()
        self.risk_context = None
        code, summary = self.invoke()
        self.assertEqual(code, 1)
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['accepted_high_critical'], 0)
        self.assertEqual(summary['unaccepted_fixable_high_critical'], 1)
        self.assertEqual(summary['risk_acceptances'], [])

    def test_expired_or_future_acceptance_cannot_allow_a_finding(self):
        self.prepare_risk()
        for now, state in [(datetime(2026, 11, 15, tzinfo=timezone.utc), 'expired'),
                           (datetime(2026, 10, 15, tzinfo=timezone.utc), 'not_yet_active')]:
            with self.subTest(state=state):
                self.now = now
                code, summary = self.invoke()
                self.assertEqual(code, 1)
                self.assertFalse(summary['passed'])
                self.assertTrue(summary['completed'])
                self.assertEqual(summary['accepted_high_critical'], 0)
                self.assertEqual(summary['risk_acceptances'][0]['state'], state)

    def test_scope_cannot_expand_to_another_cve_package_version_or_severity(self):
        self.prepare_risk()
        for key, changed in [('VulnerabilityID', 'CVE-2026-78667'), ('PkgName', 'other'),
                             ('InstalledVersion', 'v1.23.13'), ('Severity', 'HIGH')]:
            with self.subTest(field=key):
                original = self.vulnerabilities[0][key]
                self.vulnerabilities[0][key] = changed
                code, summary = self.invoke()
                self.assertEqual(code, 1)
                self.assertFalse(summary['passed'])
                self.assertEqual(summary['accepted_high_critical'], 0)
                self.vulnerabilities[0][key] = original

    def test_scope_requires_both_exact_configured_image_and_observed_digest(self):
        self.prepare_risk()
        original = self.images[0]
        for image, digests in [(original, []), (original, ['cockroachdb/cockroach@sha256:' + '0' * 64]),
                               ('cockroachdb/cockroach:other', self.repo_digests[original])]:
            with self.subTest(image=image, digests=digests):
                self.images = [image]
                self.repo_digests[image] = digests
                code, summary = self.invoke()
                self.assertEqual(code, 1)
                self.assertFalse(summary['passed'])
                self.assertEqual(summary['accepted_high_critical'], 0)

    def test_additional_cockroach_finding_remains_blocking(self):
        self.prepare_risk()
        self.vulnerabilities.append({'VulnerabilityID': 'CVE-2026-78667', 'PkgName': 'stdlib',
            'InstalledVersion': self.record['installed_version'], 'Severity': 'HIGH', 'FixedVersion': '1.26.9'})
        code, summary = self.invoke()
        self.assertEqual(code, 1)
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['accepted_high_critical'], 1)
        self.assertEqual(summary['unaccepted_fixable_high_critical'], 1)

    def test_accepted_risk_does_not_mask_python_advisory_or_failed_image_scan(self):
        self.prepare_risk()
        self.python_report['dependencies'][0]['vulns'] = [{'id': 'CVE-other'}]
        self.python_code = 1
        code, summary = self.invoke()
        self.assertEqual(code, 1)
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['accepted_high_critical'], 1)
        self.scan_code = 1
        code, summary = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertFalse(summary['passed'])
        self.assertFalse(summary['completed'])
        self.assertTrue(summary['errors'])

    def test_missing_or_malformed_risk_policy_fails_closed(self):
        self.prepare_risk()
        for document in [None, '{', '{"schema_version":1,"acceptances":{}}']:
            with self.subTest(document=document):
                if document is None:
                    self.policy_path.unlink(missing_ok=True)
                else:
                    self.policy_path.write_text(document)
                code, summary = self.invoke()
                self.assertNotEqual(code, 0)
                self.assertFalse(summary['passed'])
                self.assertFalse(summary['completed'])
                self.assertTrue(summary['errors'])

    def test_incomplete_broad_or_duplicate_risk_policy_fails_closed(self):
        self.prepare_risk()
        original = dict(self.record)
        changes = [{'cve': '*'}, {'image': 'cockroachdb/cockroach:latest'},
                   {'context': 'production'}, {'expires_at': '2026-11-15'},
                   {'expires_at': '2026-10-01T00:00:00Z'}, {'expires_at': None},
                   {'owner': ''}, {'unexpected': 'field'}]
        for change in changes:
            with self.subTest(change=change):
                self.policy['acceptances'] = [original | change]
                self.write_policy()
                code, summary = self.invoke()
                self.assertNotEqual(code, 0)
                self.assertFalse(summary['passed'])
                self.assertFalse(summary['completed'])
        self.policy['acceptances'] = [original, original | {'id': 'SFL-RA-0002'}]
        self.write_policy()
        code, summary = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertFalse(summary['passed'])

    def test_acceptance_expiring_during_scan_cannot_publish_success(self):
        self.prepare_risk()
        original_match = AUDIT.accepted_risk

        def expires_after_match(*args):
            result = original_match(*args)
            # The first check permits the match; the final lifetime check must
            # still revoke success if the acceptance expires before publication.
            self.now = datetime(2026, 11, 15, tzinfo=timezone.utc)
            return result

        with patch.object(AUDIT, 'accepted_risk', side_effect=expires_after_match):
            code, summary = self.invoke()
        self.assertNotEqual(code, 0)
        self.assertFalse(summary['passed'])
        self.assertFalse(summary['completed'])
        self.assertIn('expired during audit', summary['errors'][0])

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
