"""Audit locked Python dependencies and actual Compose images, without payloads.

All findings are retained. Python findings, scan errors, skipped Python packages
and unaccepted fixable HIGH/CRITICAL image findings fail the gate. Strict mode
accepts no risks. The explicit synthetic-lab context can apply exact, unexpired
repository risk records without filtering scanner output.

Ambient Trivy filters/configuration cannot narrow the audit. Only its cache,
database repositories, CA and registry authentication variables are inherited;
all non-Trivy variables (including proxy/CA and Docker authentication) remain.
The scanner receives an explicit full-severity/status/package reporting policy
and does not load trivy.yaml or an ignore file.

Unix/WSL2 hosts serialize complete invocations with an advisory file lock in the
output directory. Its stable lock file is never removed: removing it could let
waiters lock different inodes and publish evidence concurrently.
"""
import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone
import uuid

ROOT = Path(__file__).resolve().parents[1]
RISK_POLICY = ROOT / 'docs/security/risk-acceptances.json'
TRIVY_ENVIRONMENT = frozenset({
    'TRIVY_CACHE_DIR', 'TRIVY_DB_REPOSITORY', 'TRIVY_JAVA_DB_REPOSITORY',
    'TRIVY_CACERT', 'TRIVY_USERNAME', 'TRIVY_PASSWORD', 'TRIVY_TOKEN',
    'TRIVY_REGISTRY_TOKEN',
})


class AuditFailure(Exception):
    """Fixed diagnostic authored here, safe to include in public evidence."""


def utc_now():
    return datetime.now(timezone.utc)


def risk_timestamp(value):
    if not isinstance(value, str):
        raise AuditFailure('Risk acceptance has an invalid timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise AuditFailure('Risk acceptance has an invalid timestamp') from None
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise AuditFailure('Risk acceptance timestamps must specify UTC')
    return parsed


def risk_state(record):
    now = utc_now()
    if now < risk_timestamp(record['approved_at']):
        return 'not_yet_active'
    return 'active' if now < risk_timestamp(record['expires_at']) else 'expired'


def load_risk_acceptances(context):
    if context == 'strict':
        return []
    try:
        policy = json.loads(RISK_POLICY.read_text())
    except (OSError, ValueError):
        raise AuditFailure('Risk acceptance policy is missing or malformed') from None
    if (not isinstance(policy, dict) or set(policy) != {'schema_version', 'acceptances'}
            or type(policy['schema_version']) is not int or policy['schema_version'] != 1
            or not isinstance(policy['acceptances'], list)):
        raise AuditFailure('Risk acceptance policy has an invalid schema')
    fields = {'id', 'context', 'image', 'cve', 'package', 'installed_version',
              'severity', 'owner', 'approved_by', 'approved_at', 'expires_at',
              'rationale', 'conditions', 'remediation'}
    ids, scopes, records = set(), set(), []
    for record in policy['acceptances']:
        if (not isinstance(record, dict) or set(record) != fields
                or any(not isinstance(value, str) or not value.strip()
                       for value in record.values())
                or not re.fullmatch(r'SFL-RA-[0-9]{4}', record['id'])
                or record['context'] != 'synthetic-lab'
                or not re.fullmatch(r'[^\s@]+:[^\s@]+@sha256:[0-9a-f]{64}', record['image'])
                or not re.fullmatch(r'CVE-[0-9]{4}-[0-9]{4,}', record['cve'])
                or record['severity'] not in {'HIGH', 'CRITICAL'}):
            raise AuditFailure('Risk acceptance has incomplete or invalid scope')
        if risk_timestamp(record['expires_at']) <= risk_timestamp(record['approved_at']):
            raise AuditFailure('Risk acceptance expiry must follow approval')
        scope = tuple(record[key] for key in ('context', 'image', 'cve', 'package',
                                              'installed_version', 'severity'))
        if record['id'] in ids or scope in scopes:
            raise AuditFailure('Risk acceptance has a duplicate ID or scope')
        ids.add(record['id'])
        scopes.add(scope)
        records.append({**record, 'state': risk_state(record)})
    return records


def accepted_risk(image, vulnerability, records):
    for record in records:
        record['state'] = risk_state(record)
        reference, digest = record['image'].split('@', 1)
        repository = reference.rsplit(':', 1)[0]
        if (record['state'] == 'active'
                and record['image'] in image['tags']
                and repository + '@' + digest in image['repo_digests']
                and vulnerability.get('VulnerabilityID') == record['cve']
                and vulnerability.get('PkgName') == record['package']
                and vulnerability.get('InstalledVersion') == record['installed_version']
                and vulnerability.get('Severity') == record['severity']):
            return record['id']
    return None


def trivy_environment():
    """Retain connectivity/auth settings, never ambient scan/filter overrides."""
    return {key: value for key, value in os.environ.items()
            if not key.upper().startswith('TRIVY_') or key in TRIVY_ENVIRONMENT}


def save_summary(output, summary):
    """Replace evidence atomically; interruption must never expose a partial JSON."""
    temporary = output / ('.summary-' + summary['run_id'] + '.tmp')
    temporary.write_text(json.dumps(summary, indent=2) + '\n')
    temporary.replace(output / 'summary.json')


def audit(args, output, reports, summary):
    summary['trivy'] = json.loads(subprocess.check_output(
        [args.trivy, 'version', '--config', '', '--format', 'json'],
        text=True, env=trivy_environment()))
    failed = False
    # Every invocation owns a new directory. Neither a failed command nor a
    # command that exits without writing output can consume a previous report.
    python_report = reports / 'python.json'
    command = [args.pip_audit, '--vulnerability-service', 'pypi', '--require-hashes',
               '--progress-spinner', 'off', '--format', 'json', '--output', str(python_report)]
    for requirements in ['poc/requirements.txt', 'scale/requirements.txt', 'requirements-dev.txt', 'requirements-admin.txt']:
        command.extend(['-r', str(ROOT / requirements)])
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode not in (0, 1) or not python_report.exists():
        raise AuditFailure('Python dependency audit did not produce a complete report')
    python = json.loads(python_report.read_text())
    if not isinstance(python, dict) or not isinstance(python.get('dependencies'), list) or not python['dependencies']:
        raise AuditFailure('Invalid or empty Python dependency report')
    if any(not isinstance(package, dict)
           or not isinstance(package.get('name'), str) or not package['name']
           or (not package.get('skip_reason')
               and (not isinstance(package.get('version'), str) or not package['version']
                    or not isinstance(package.get('vulns'), list)))
           for package in python['dependencies']):
        raise AuditFailure('Python dependency report has incomplete package evidence')
    skipped = [p['name'] for p in python['dependencies'] if p.get('skip_reason')]
    findings = [v for p in python['dependencies'] for v in p.get('vulns', [])]
    summary['python'] = {'report': str(python_report.relative_to(output)),
                         'advisory_records': len(findings), 'skipped_packages': skipped}
    if result.returncode and not findings and not skipped:
        raise AuditFailure('Python dependency audit failed without an advisory or skip result')
    failed |= bool(findings or skipped or result.returncode)
    images = subprocess.check_output(
        ['docker', 'compose', '--profile', 'tools', '-f', 'compose.yaml', '-f', 'compose.pilot.yaml',
         'config', '--images'], cwd=ROOT, text=True).splitlines()
    if not images or any(not image.strip() for image in images):
        raise AuditFailure('Compose did not enumerate images to audit')
    summary['configured_image_count'] = len(set(images))
    groups = {}
    for image in sorted(set(images)):
        try:
            metadata = json.loads(subprocess.check_output(['docker', 'image', 'inspect', image], text=True))[0]
        except subprocess.CalledProcessError:
            summary['errors'].append(f'Missing image: {image}; pull/build the lab and tools first.')
            failed = True
            continue
        group = groups.setdefault(metadata['Id'], {'image_id': metadata['Id'], 'tags': [],
                                                  'repo_digests': metadata.get('RepoDigests', [])})
        group['tags'].append(image)
    for index, image in enumerate(groups.values(), 1):
        report = reports / f'image-{index:02}.json'
        command = [args.trivy, 'image', '--config', '', '--image-src', 'docker', '--scanners', 'vuln',
                   '--skip-java-db-update', '--ignorefile', '', '--ignore-policy', '',
                   '--severity', 'UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL',
                   '--ignore-unfixed=false', '--ignore-status=', '--list-all-pkgs=true',
                   '--pkg-types', 'os,library',
                   '--pkg-relationships', 'unknown,root,workspace,direct,indirect',
                   '--show-suppressed', '--parallel', '2',
                   '--timeout', '10m', '--no-progress', '--format', 'json', '--exit-code', '0',
                   '--output', str(report), image['image_id']]
        with (reports / f'image-{index:02}.log').open('w') as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=log,
                                    check=False, env=trivy_environment())
        if result.returncode or not report.exists():
            summary['errors'].append(f"Image scan failed: {image['tags']}; see {reports.name}/image-{index:02}.log")
            failed = True
            continue
        data = json.loads(report.read_text())
        if (not isinstance(data, dict) or data.get('SchemaVersion') != 2
                or data.get('ArtifactType') != 'container_image'
                or data.get('Metadata', {}).get('ImageID') != image['image_id']
                or not isinstance(data.get('Results'), list)):
            raise AuditFailure('Invalid or mismatched container image report')
        if any(not isinstance(result, dict)
               or ('Vulnerabilities' in result and not isinstance(result['Vulnerabilities'], list))
               for result in data['Results']):
            raise AuditFailure('Container image report has malformed vulnerability evidence')
        if not any(isinstance(result, dict) and isinstance(result.get('Packages'), list)
                   and any(isinstance(package, dict)
                           and isinstance(package.get('Name'), str) and package['Name']
                           and isinstance(package.get('Version'), str) and package['Version']
                           for package in result['Packages']) for result in data['Results']):
            raise AuditFailure('Container image scan has no recognised package inventory')
        vulnerabilities = [v for r in data['Results'] for v in r.get('Vulnerabilities', [])]
        if any(not isinstance(vulnerability, dict)
               or not isinstance(vulnerability.get('VulnerabilityID'), str)
               or not vulnerability['VulnerabilityID']
               or vulnerability.get('Severity') not in ('UNKNOWN', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
               or ('FixedVersion' in vulnerability and not isinstance(vulnerability['FixedVersion'], str))
               for vulnerability in vulnerabilities):
            raise AuditFailure('Container image report has malformed vulnerability fields')
        fixable = [v for v in vulnerabilities if v.get('FixedVersion')
                   and v['Severity'] in {'HIGH', 'CRITICAL'}]
        accepted = []
        for finding in fixable:
            risk_id = accepted_risk(image, finding, summary['risk_acceptances'])
            if risk_id:
                accepted.append({key: finding[key] for key in (
                    'VulnerabilityID', 'PkgName', 'InstalledVersion', 'Severity', 'FixedVersion')}
                                | {'risk_acceptance_id': risk_id})
        blocking = len(fixable) - len(accepted)
        image.update(report=str(report.relative_to(output)), counts=dict(Counter(v['Severity'] for v in vulnerabilities)),
                     fixable_high_critical=len(fixable),
                     accepted_high_critical=len(accepted),
                     unaccepted_fixable_high_critical=blocking,
                     accepted_findings=accepted,
                     unfixed_advisory_ids=sorted({v['VulnerabilityID'] for v in vulnerabilities
                                                 if not v.get('FixedVersion')}))
        summary['images'].append(image)
        failed |= bool(blocking)
        print(f"{', '.join(image['tags'])}: {image['counts']}; fixable HIGH/CRITICAL={len(fixable)}; "
              f"accepted={len(accepted)}; blocking={blocking}", flush=True)
    summary['accepted_high_critical'] = sum(image['accepted_high_critical'] for image in summary['images'])
    summary['unaccepted_fixable_high_critical'] = sum(
        image['unaccepted_fixable_high_critical'] for image in summary['images'])
    used = {finding['risk_acceptance_id'] for image in summary['images']
            for finding in image['accepted_findings']}
    for record in summary['risk_acceptances']:
        record['state'] = risk_state(record)
        if record['id'] in used and record['state'] != 'active':
            raise AuditFailure('Risk acceptance expired during audit; rerun without that acceptance')
    return failed


def run_locked_audit(args, output):
    """Caller holds the output lock through initial and final publication."""
    summary = {'run_id': uuid.uuid4().hex,
               'scanned_at': datetime.now(timezone.utc).isoformat(),
               'gate': 'Python: all known findings; images: unaccepted fixable HIGH/CRITICAL; scan errors fail',
               'risk_context': args.risk_context, 'risk_acceptances': [],
               'status': 'incomplete', 'passed': False, 'completed': False,
               'images': [], 'errors': []}
    # Publish failed/incomplete evidence before Git, scanner discovery or network
    # I/O. Even a hard interruption leaves this invocation marked incomplete.
    save_summary(output, summary)
    failed, exit_code = True, 2
    try:
        reports = output / ('run-' + summary['run_id'])
        reports.mkdir()
        summary['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        summary['working_tree_dirty'] = bool(subprocess.check_output(
            ['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
        summary['risk_acceptances'] = load_risk_acceptances(args.risk_context)
        failed = audit(args, output, reports, summary)
        summary['completed'] = not summary['errors']
        exit_code = int(failed or not summary['completed'])
    except KeyboardInterrupt:
        summary['errors'].append('Dependency audit interrupted; acceptance is blocked.')
        exit_code = 130
    except AuditFailure as error:
        summary['errors'].append(str(error) + '; acceptance is blocked.')
    except Exception as error:
        # External exception strings can contain registry URLs/connection details.
        summary['errors'].append(f'Dependency audit could not complete ({type(error).__name__}); acceptance is blocked.')
    finally:
        summary['passed'] = summary['completed'] and not failed and not summary['errors']
        summary['status'] = ('passed_with_risk_acceptance'
                             if summary['passed'] and summary.get('accepted_high_critical') else
                             'passed' if summary['passed'] else
                             'failed' if summary['completed'] else 'incomplete')
        summary['finished_at'] = datetime.now(timezone.utc).isoformat()
        save_summary(output, summary)
    label = 'PASS WITH ACCEPTED RISK' if summary['status'] == 'passed_with_risk_acceptance' else (
        'PASS' if summary['passed'] else 'FAIL')
    print(f"{label} dependency gate; evidence retained in {output}")
    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pip-audit', default='pip-audit')
    parser.add_argument('--trivy', default='trivy')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/security')
    parser.add_argument('--risk-context', choices=('strict', 'synthetic-lab'), default='strict',
                        help='Explicit synthetic lab risk acceptance; strict applies no exceptions (default).')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Lock before even the initial summary write. A waiting invocation must not
    # overwrite the active run, and an older success cannot replace its failure.
    # The OS releases this advisory lock on process death as well as normal exit.
    with (output / '.audit.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return run_locked_audit(args, output)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


if __name__ == '__main__':
    raise SystemExit(main())
