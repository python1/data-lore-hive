#!/usr/bin/env python3
"""Mac-only, offline baseline/trusted-kit generator. No production memory writes."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import code_release as c
import replication as r
import cross_machine_recovery
import recovery_drill as d
from recovery_drill_worker import source_rows

SIGNER = '<release-signing-key-fingerprint>'
HOST = '<replica-host-key-fingerprint>'


def fingerprint(blob):
    return 'SHA256:'+base64.b64encode(hashlib.sha256(base64.b64decode(blob, validate=True)).digest()).decode().rstrip('=')


def generate(checkpoint, release, signers, known_host, pin_status, destination, review=None):
    d.require(sys.platform == 'darwin', 'Generate baseline on the Mac')
    checkpoint = Path(checkpoint)
    # This takes a downloaded copy, never opens the configured production DB.
    actual = r.manifest_for(checkpoint, d.CHECKPOINT['database_id'])
    d.require(actual == d.CHECKPOINT, 'Checkpoint differs from fixed drill criteria')
    manifest = c.validate(release, signers)
    d.require(manifest['commit'] == d.COMMIT and manifest['sequence'] == 2 and d.sha(Path(release)/'manifest.json') == d.RELEASE, 'Wrong approved release')
    signer_text = Path(signers).read_text().strip()
    parts = signer_text.split()
    d.require(len(signer_text.splitlines()) == 1 and parts[:3] == ['aster-hive', 'namespaces="hive-release"', 'ssh-ed25519'] and fingerprint(parts[3]) == SIGNER, 'Unexpected signing trust')
    host_parts = known_host.strip().split()
    d.require(len(host_parts) == 3 and host_parts[:2] == ['replica-host', 'ssh-ed25519'] and fingerprint(host_parts[2]) == HOST, 'Unexpected CT host key')
    state = json.loads(Path(pin_status).read_bytes())
    d.require(state['sequence'] == 2 and state['current'] == d.RELEASE and state['pin'] is None and state['pin_sequence'] == 0, 'Unexpected publisher state; freeze a new plan')
    out = Path(destination); out.mkdir(mode=0o700)
    repo = Path(__file__).resolve().parent
    for name in d.TOOLS:
        shutil.copyfile(signers if name == 'allowed_signers' else repo/name, out/name)
    hashes = {name: d.sha(out/name) for name in d.TOOLS}
    review_record = {'status': 'pending', 'reviewer': 'Claude'}
    if review:
        review_record = json.loads(Path(review).read_bytes())
        d.require(review_record.get('reviewer') == 'Claude' and review_record.get('status') == 'approved', 'Review must record Claude approval')
        for name in ('recovery_drill.py', 'recovery_drill_worker.py'):
            d.require(review_record.get('tools', {}).get(name) == hashes[name], 'Review is for different runner bytes')
        d.require(bool(review_record.get('notes')), 'Review record needs notes/reference')
    baseline = {'format': 1, 'generated_at': datetime.now(timezone.utc).isoformat(), 'generated_on': 'Mac',
                'release': {'sequence': 2, 'manifest_sha256': d.RELEASE, 'commit': d.COMMIT},
                'checkpoint': actual, 'sources': source_rows(checkpoint),
                'findings': cross_machine_recovery.linked_findings(checkpoint),
                'criteria': d.CRITERIA, 'model': d.MODEL, 'known_host': known_host.strip()+'\n',
                'signing_fingerprint': SIGNER, 'pin_sequence': state['pin_sequence'],
                'tools': hashes, 'review': review_record}
    d.save(out/'baseline.json', baseline)
    digest = d.sha(out/'baseline.json')
    (out/'BASELINE-SHA256.txt').write_text(digest+'  baseline.json\n')
    return {'directory': str(out), 'baseline_sha256': digest, 'review': review_record['status'], 'checkpoint': actual}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('checkpoint', 'release', 'signers', 'known-host', 'pin-status', 'destination'):p.add_argument('--'+name, required=True)
    p.add_argument('--claude-review')
    a = p.parse_args()
    print(json.dumps(generate(a.checkpoint, a.release, a.signers, Path(a.known_host).read_text(), a.pin_status, a.destination, a.claude_review), indent=2))

if __name__ == '__main__':main()
