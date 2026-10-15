"""Audit locked Python dependencies and actual Compose images, without payloads.

All findings are retained. Python findings, scan errors, skipped Python packages
and fixable HIGH/CRITICAL image findings fail the gate. Unfixed image findings
remain visible in summary.json and the complete Trivy reports.

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
import subprocess
from datetime import datetime, timezone
import uuid

ROOT = Path(__file__).resolve().parents[1]
TRIVY_ENVIRONMENT = frozenset({
    'TRIVY_CACHE_DIR', 'TRIVY_DB_REPOSITORY', 'TRIVY_JAVA_DB_REPOSITORY',
    'TRIVY_CACERT', 'TRIVY_USERNAME', 'TRIVY_PASSWORD', 'TRIVY_TOKEN',
    'TRIVY_REGISTRY_TOKEN',
})


class AuditFailure(Exception):
    """Fixed diagnostic authored here, safe to include in public evidence."""


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
    summary['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    summary['working_tree_dirty'] = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    summary['trivy'] = json.loads(subprocess.check_output(
        [args.trivy, 'version', '--config', '', '--format', 'json'],
        text=True, env=trivy_environment()))
    failed = False
    # Every invocation owns a new directory. Neither a failed command nor a
    # command that exits without writing output can consume a previous report.
    python_report = reports / 'python.json'
    command = [args.pip_audit, '--vulnerability-service', 'pypi', '--require-hashes',
               '--progress-spinner', 'off', '--format', 'json', '--output', str(python_report)]
    for requirements in ['poc/requirements.txt', 'scale/requirements.txt', 'requirements-dev.txt']:
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
        image.update(report=str(report.relative_to(output)), counts=dict(Counter(v['Severity'] for v in vulnerabilities)),
                     fixable_high_critical=len(fixable),
                     unfixed_advisory_ids=sorted({v['VulnerabilityID'] for v in vulnerabilities
                                                 if not v.get('FixedVersion')}))
        summary['images'].append(image)
        failed |= bool(fixable)
        print(f"{', '.join(image['tags'])}: {image['counts']}; fixable HIGH/CRITICAL={len(fixable)}", flush=True)
    return failed


def run_locked_audit(args, output):
    """Caller holds the output lock through initial and final publication."""
    summary = {'run_id': uuid.uuid4().hex,
               'scanned_at': datetime.now(timezone.utc).isoformat(),
               'gate': 'Python: all known findings; images: fixable HIGH/CRITICAL; scan errors fail',
               'status': 'incomplete', 'passed': False, 'completed': False,
               'images': [], 'errors': []}
    # Publish failed/incomplete evidence before Git, scanner discovery or network
    # I/O. Even a hard interruption leaves this invocation marked incomplete.
    save_summary(output, summary)
    failed, exit_code = True, 2
    try:
        reports = output / ('run-' + summary['run_id'])
        reports.mkdir()
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
        summary['status'] = ('passed' if summary['passed'] else
                             'failed' if summary['completed'] else 'incomplete')
        summary['finished_at'] = datetime.now(timezone.utc).isoformat()
        save_summary(output, summary)
    print(f"{'PASS' if summary['passed'] else 'FAIL'} dependency gate; evidence retained in {output}")
    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pip-audit', default='pip-audit')
    parser.add_argument('--trivy', default='trivy')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/security')
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
