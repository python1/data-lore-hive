#!/usr/bin/env python3
"""Reviewed, independently transferred drill controller; never signs or uploads.

Bootstrap imports are standard library only. Verify baseline with the phone hash
and every trusted-tool hash before importing verification/transport helpers.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

RELEASE = '1b8a64fccf29289967d532ae323f52922d81dce0b94c4a9569050dc842f5e13b'
COMMIT = 'c8a784e9a0084559bd71524f07b9ab8478141fba'
CHECKPOINT = {
    'version': 1, 'database_id': '2fe11788-7e0e-4591-9373-c01c214f8ce7',
    'bytes': 86016, 'sha256': '13911c3542a3f68ace538c9c21c42d0b5c45f0bb04b970742ec06bc962f8a025',
    'event_count': 26, 'first_sequence': 1, 'last_sequence': 26,
    'chain_head': 'e51439da5b89dfbcd3902736f21c1933395cffd5f05c1dfe0196a73db4760f67',
    'source_snapshots': 4,
}
MODEL = {'name': 'gemma4:e4b', 'digest': 'c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb', 'minimum_ollama': '0.32.14'}
CASES = [
    ['What happens when the model calculation disagrees?', 'supported_answer', 'needs_review'],
    ['What is the minimum Python version required?', 'supported_answer', 'Python 3.10 or newer'],
    ['Who manufactured the reservoir?', 'not_found_in_source', None],
]
CRITERIA = {'unit_tests': 212, 'seeds': [11, 29, 47], 'temperature': 0.2,
            'cases': CASES, 'quality_target_correct': 9,
            'pin_requires': 'integrity_pass_and_tests_pass_and_9_trials_zero_false_accepts_zero_errors',
            'abstentions_allowed_for_pin': True}
TOOLS = ('recovery_drill.py', 'recovery_drill_worker.py', 'code_release.py', 'replication.py', 'allowed_signers')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    # Each artifact is written once; repeated runs use a new directory.
    with Path(path).open('xb') as f:
        f.write(canonical(value))


def verify_kit(kit, phone_hash, require_review=True):
    kit = Path(kit).resolve()
    require(re.fullmatch('[0-9a-f]{64}', phone_hash) is not None, 'Full baseline phone SHA-256 required')
    require(sha(kit/'baseline.json') == phone_hash, 'Baseline does not match phone hash')
    baseline = json.loads((kit/'baseline.json').read_bytes())
    require(baseline['format'] == 1 and baseline['checkpoint'] == CHECKPOINT, 'Wrong frozen checkpoint')
    require(baseline['release'] == {'sequence': 2, 'manifest_sha256': RELEASE, 'commit': COMMIT}, 'Wrong frozen release')
    require(baseline['criteria'] == CRITERIA and baseline['model'] == MODEL, 'Criteria changed')
    require(set(baseline['tools']) == set(TOOLS), 'Wrong trusted tool inventory')
    for name, digest in baseline['tools'].items():
        p = kit/name
        require(p.is_file() and not p.is_symlink() and sha(p) == digest, 'Trusted tool hash mismatch: '+name)
    review = baseline['review']
    if require_review:
        require(review.get('status') == 'approved' and review.get('reviewer') == 'Claude', 'Claude review still pending')
        for name in ('recovery_drill.py', 'recovery_drill_worker.py'):
            require(review.get('tools', {}).get(name) == baseline['tools'][name], 'Review does not bind current runner')
    return baseline


def helper(kit, name):
    spec = importlib.util.spec_from_file_location('trusted_drill_'+name, Path(kit)/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def new_run(parent, run_id=None):
    parent = Path(parent).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_id = run_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:12]
    require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,100}', run_id) is not None, 'Invalid run ID')
    dest = parent/run_id
    dest.mkdir(mode=0o700)  # Existing success OR failure must never be overwritten.
    return dest


def command(args, dest, label, cwd=None, timeout=300):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'GIT_'))}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0', GIT_TEMPLATE_DIR='')
    with (dest/(label+'.stdout')).open('xb') as out, (dest/(label+'.stderr')).open('xb') as err:
        try:
            result = subprocess.run(args, stdout=out, stderr=err, cwd=cwd, env=env, timeout=timeout)
        except BaseException as e:
            save(dest/(label+'.command.json'), {'args': args, 'error': repr(e)})
            raise
    save(dest/(label+'.command.json'), {'args': args, 'exit': result.returncode})
    return result.returncode


def ssh_args(key, hosts, remote_command):
    require(remote_command in {'code-status', 'status', 'release', 'fetch '+CHECKPOINT['sha256']} or
            re.fullmatch('code-fetch '+RELEASE+r' (manifest.json|manifest.sig|hive.bundle|evidence.json)', remote_command),
            'Non-read-only command refused')
    return ['ssh', '-F', '/dev/null', '-T', '-i', str(Path(key).expanduser().resolve()),
            '-o', 'ForwardAgent=no', '-o', 'IdentitiesOnly=yes',
            '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlgorithms=ssh-ed25519',
            '-o', 'UserKnownHostsFile='+str(hosts), '-o', 'GlobalKnownHostsFile=/dev/null',
            '-o', 'ConnectTimeout=10', 'hive-recovery@replica-host', remote_command]


def fetch(key, dest, command_text, label):
    require(command(ssh_args(key, dest/'known_hosts', command_text), dest, label) == 0, 'CT read failed: '+label)
    return dest/(label+'.stdout')


def inventory(root):
    files = {}
    for p in sorted(Path(root).rglob('*')):
        require(not p.is_symlink(), 'Symlink in evidence: '+str(p))
        if p.is_file() and p != Path(root)/'evidence-index.json':
            files[p.relative_to(root).as_posix()] = sha(p)
    return files


def seal(dest):
    index = {'format': 1, 'files': inventory(dest)}
    save(dest/'evidence-index.json', index)
    return sha(dest/'evidence-index.json')


def quality_summary(rows, preflight_ok):
    counts = {k: sum(row['verdict'] == k for row in rows) for k in ('correct', 'false_accept', 'abstention', 'error')}
    expected = [(seed, case[0]) for seed in CRITERIA['seeds'] for case in CRITERIA['cases']]
    observed = [(row.get('seed'), row.get('question')) for row in rows]
    completed = preflight_ok and observed == expected and sum(counts.values()) == 9
    expected_status = {case[0]: case[1] for case in CASES}
    correct_positive = sum(row['verdict'] == 'correct' and expected_status.get(row.get('question')) == 'supported_answer' for row in rows)
    confirmed_absence = sum(row['verdict'] == 'correct' and expected_status.get(row.get('question')) == 'not_found_in_source' for row in rows)
    return {'counts': counts, 'correct_positive': correct_positive, 'confirmed_absence': confirmed_absence, 'complete': completed,
            'target_pass': completed and counts['correct'] == 9,
            'safety_pass': completed and counts['false_accept'] == counts['error'] == 0}


def run(kit, phone_hash, receipt_path, key, parent, mac_off, run_id=None):
    require(mac_off, 'Operator must confirm Mac is off')
    require(os.geteuid() != 0, 'Run as normal recovery-host user, never root')
    dest = new_run(parent, run_id)
    report = {'format': 1, 'run_id': dest.name, 'started': datetime.now(timezone.utc).isoformat(),
              'mac_off': 'operator-confirmed; not remotely measured', 'integrity': 'not_run',
              'unit_tests': 'not_run', 'quality': 'not_run', 'pristine_final': 'not_run', 'pin_eligible': False}
    r = None
    try:
        baseline = verify_kit(kit, phone_hash)
        require(sha(Path(__file__)) == baseline['tools']['recovery_drill.py'], 'Running runner differs from reviewed tool')
        kit = Path(kit).resolve()
        receipt = json.loads(Path(receipt_path).read_bytes())
        require(receipt == {'sequence': 2, 'manifest_sha256': RELEASE}, 'Release phone receipt mismatch')
        shutil.copyfile(kit/'baseline.json', dest/'baseline.json')
        save(dest/'release-phone-receipt.json', receipt)
        (dest/'known_hosts').write_text(baseline['known_host'])
        report['baseline_sha256'] = phone_hash
        c = helper(kit, 'code_release'); r = helper(kit, 'replication')
        remote = json.loads(fetch(key, dest, 'code-status', 'ct-code-status').read_bytes())
        require(remote['sequence'] == 2 and remote['current'] == RELEASE, 'Current release changed; stop for new plan')
        require(remote['pin_sequence'] == baseline['pin_sequence'], 'Pin sequence changed; stop for new baseline')
        require(remote['releases'][RELEASE]['commit'] == COMMIT, 'CT release entry mismatch')
        package = dest/'release'; package.mkdir()
        for name in c.FILES:
            shutil.copyfile(fetch(key, dest, 'code-fetch '+RELEASE+' '+name, 'download-'+name), package/name)
        require(sha(package/'manifest.json') == RELEASE, 'Manifest versus receipt mismatch')
        manifest = c.validate(package, kit/'allowed_signers')
        require(manifest['sequence'] == 2 and manifest['commit'] == COMMIT, 'Signed release mismatch')
        save(dest/'code-verification.json', {'verified': True, 'manifest': manifest, 'receipt': receipt})
        status = json.loads(fetch(key, dest, 'status', 'ct-memory-status').read_bytes())
        require(status.get('read_only') is True and status['manifest'] == baseline['checkpoint'], 'Recovery export checkpoint mismatch')
        wire = fetch(key, dest, 'fetch '+CHECKPOINT['sha256'], 'checkpoint-wire')
        memory = dest/'memory'; memory.mkdir()
        with wire.open('rb') as f:
            r.receive(f, memory, max_snapshot=CHECKPOINT['bytes'])
        require(r.validate(memory, CHECKPOINT['database_id']) == CHECKPOINT, 'Checkpoint integrity mismatch')
        repo = dest/'recovered-code'
        require(command(['git', '-c', 'core.hooksPath=/dev/null', 'clone', '--no-checkout', str(package/'hive.bundle'), str(repo)], dest, 'clone') == 0, 'Clone failed')
        require(command(['git', '-c', 'core.hooksPath=/dev/null', 'checkout', '--detach', COMMIT], dest, 'checkout', cwd=repo) == 0, 'Checkout failed')
        # Only now may authenticated release code execute, in a separate process.
        worker = [sys.executable, '-B', '-I', str(kit/'recovery_drill_worker.py'), '--repo', str(repo), '--run', str(dest)]
        require(command(worker+['--phase', 'integrity'], dest, 'integrity-worker', timeout=120) == 0, 'Integrity worker failed')
        require(json.loads((dest/'integrity.json').read_bytes())['passed'] is True, 'Integrity report refused')
        report['integrity'] = 'passed'
        rc = command([sys.executable, '-B', '-I', '-m', 'unittest', 'discover'], dest, 'unit-tests', cwd=repo, timeout=600)
        logs = (dest/'unit-tests.stdout').read_text(errors='replace')+(dest/'unit-tests.stderr').read_text(errors='replace')
        require(rc == 0 and re.search(r'Ran 212 tests in [\d.]+s\s+OK(?:\s|$)', logs), 'Expected 212 passing release tests')
        report['unit_tests'] = 'passed'
        require(command(worker+['--phase', 'quality'], dest, 'quality-worker', timeout=1800) == 0, 'Quality worker incomplete')
        quality = json.loads((dest/'quality.json').read_bytes())
        summary = quality_summary(quality['trials'], quality['preflight_ok'])
        report['quality'] = summary
        report['pin_eligible'] = summary['safety_pass']
        report['status'] = 'completed'
    except BaseException as e:
        report['status'] = 'failed'; report['error'] = repr(e)
        report['pin_eligible'] = False
        if report['integrity'] == 'not_run':report['integrity'] = 'failed_or_incomplete'
    if r is not None and (dest/'memory/knowledge.sqlite3').exists():
        try:
            require(r.manifest_for(dest/'memory/knowledge.sqlite3', CHECKPOINT['database_id']) == CHECKPOINT, 'Pristine checkpoint changed')
            report['pristine_final'] = 'passed'
        except Exception as e:
            report.update(status='failed', integrity='failed', pristine_final='failed', pin_eligible=False, pristine_error=repr(e))
    report['finished'] = datetime.now(timezone.utc).isoformat()
    save(dest/'report.json', report)
    digest = seal(dest)
    print(json.dumps({'run': str(dest), 'report': report, 'evidence_index_sha256': digest}, indent=2))
    return report


def prepare_pin(run_dir, output):
    """Produce UNSIGNED canonical bytes only; operator signs separately."""
    root = Path(run_dir).resolve(); output = Path(output).resolve()
    require(not output.is_relative_to(root), 'Pin output must be outside sealed evidence')
    index = json.loads((root/'evidence-index.json').read_bytes())
    require(index == {'format': 1, 'files': inventory(root)}, 'Sealed evidence changed')
    report = json.loads((root/'report.json').read_bytes())
    require(report['status'] == 'completed' and report['integrity'] == report['unit_tests'] == report.get('pristine_final') == 'passed'
            and report['pin_eligible'] is True, 'Run is not eligible for pin')
    baseline = json.loads((root/'baseline.json').read_bytes())
    require(sha(root/'baseline.json') == report['baseline_sha256'], 'Baseline changed')
    quality = json.loads((root/'quality.json').read_bytes())
    require(quality_summary(quality['trials'], quality['preflight_ok'])['safety_pass'], 'Quality safety gate failed')
    require(baseline['release']['manifest_sha256'] == RELEASE, 'Wrong release')
    require(type(baseline['pin_sequence']) is int and baseline['pin_sequence'] >= 0, 'Invalid pin sequence')
    pin = {'project': 'aster-hive', 'action': 'recovery-tested', 'sequence': baseline['pin_sequence']+1,
           'release': RELEASE, 'drill_sha256': sha(root/'evidence-index.json')}
    save(output, pin)
    return pin


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='action', required=True)
    q = sub.add_parser('run')
    for name in ('kit', 'baseline-sha256', 'receipt', 'key', 'run-root'):q.add_argument('--'+name, required=True)
    q.add_argument('--run-id'); q.add_argument('--mac-off-confirmed', action='store_true')
    q = sub.add_parser('prepare-pin'); q.add_argument('--run', required=True); q.add_argument('--output', required=True)
    a = p.parse_args()
    if a.action == 'prepare-pin':print(json.dumps(prepare_pin(a.run, a.output), indent=2))
    else:
        result = run(a.kit, a.baseline_sha256, a.receipt, a.key, a.run_root, a.mac_off_confirmed, a.run_id)
        raise SystemExit(0 if result['status'] == 'completed' and result['pin_eligible'] else 1)

if __name__ == '__main__':main()
