#!/usr/bin/env python3
"""Check the published release-2 drill evidence. Standard library plus ssh-keygen only.

Usage: python3 verify_evidence.py [evidence-dir]   (default: this script's directory)
Exit 0 only if every check passes.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

IDENTITY = 'aster-hive'
NAMESPACE = 'hive-release'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent)
    run = root/'run'
    failures = []

    def check(ok, label):
        print(('PASS ' if ok else 'FAIL ')+label)
        if not ok:
            failures.append(label)

    def signature(message, sig):
        if not shutil.which('ssh-keygen'):
            check(False, f'ssh-keygen not found; cannot verify {sig}')
            return
        with open(root/message, 'rb') as stdin:
            p = subprocess.run(['ssh-keygen', '-Y', 'verify', '-f', str(root/'allowed_signers'), '-I', IDENTITY,
                                '-n', NAMESPACE, '-s', str(root/sig)], stdin=stdin, capture_output=True, text=True)
        check(p.returncode == 0, f'signature {sig} ({(p.stdout or p.stderr).strip()})')

    signature('release-2/manifest.json', 'release-2/manifest.sig')
    signature('pin-manifest.json', 'pin-manifest.json.sig')

    release = json.loads((root/'release-2/manifest.json').read_bytes())
    pin = json.loads((root/'pin-manifest.json').read_bytes())
    check(release.get('project') == IDENTITY and release.get('sequence') == 2, 'release manifest is aster-hive sequence 2')
    check(pin.get('project') == IDENTITY and pin.get('action') == 'recovery-tested' and pin.get('sequence') == 1,
          'pin manifest is aster-hive recovery-tested sequence 1')
    check(pin.get('release') == sha(root/'release-2/manifest.json'), 'pin release == sha256(release-2/manifest.json)')
    check(pin.get('drill_sha256') == sha(run/'evidence-index.json'), 'pin drill_sha256 == sha256(run/evidence-index.json)')

    index = json.loads((run/'evidence-index.json').read_bytes())['files']
    withheld = json.loads((root/'withheld.json').read_bytes())['files']
    published = mismatched = 0
    for name, digest in sorted(index.items()):
        path = run/name
        if path.is_file():
            published += 1
            if sha(path) != digest:
                mismatched += 1
                check(False, f'hash mismatch: run/{name}')
        elif withheld.get(name, {}).get('sha256') != digest:
            check(False, f'missing and not listed as withheld: run/{name}')
    check(mismatched == 0, f'{published} published evidence files match their index hashes')
    check(set(withheld) <= set(index) and not any((run/n).exists() for n in withheld),
          f'{len(withheld)} withheld files are indexed and absent')
    extra = sorted(str(p.relative_to(run)) for p in run.rglob('*')
                   if p.is_file() and p.name != 'evidence-index.json' and str(p.relative_to(run)) not in index)
    check(not extra, 'no unindexed files in run/' + (f': {extra}' if extra else ''))
    for name in ('manifest.json', 'manifest.sig'):
        if (run/'release'/name).is_file():
            check((run/'release'/name).read_bytes() == (root/'release-2'/name).read_bytes(),
                  f'run/release/{name} is identical to release-2/{name}')

    report_path = run/'report.json'
    if report_path.is_file() and sha(report_path) == index.get('report.json'):
        report = json.loads(report_path.read_bytes())
        q = report['quality']
        print(f"report.json: status={report['status']} integrity={report['integrity']} unit_tests={report['unit_tests']} "
              f"pristine_final={report['pristine_final']} pin_eligible={report['pin_eligible']} counts={q['counts']} "
              f"target_pass={q['target_pass']} mac_off={report['mac_off']!r}")
    print('ALL CHECKS PASSED' if not failures else f'{len(failures)} CHECK(S) FAILED')
    raise SystemExit(1 if failures else 0)


if __name__ == '__main__':
    main()
