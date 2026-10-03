"""Build installer and offline bootstrap verifier kit; never installs or connects."""
import argparse,base64,hashlib,json
from pathlib import Path
FILES=['code_release.py','code_publisher.py','code_transport.py','replication.py','retention.py']
def build(destination):
    out=Path(destination);out.mkdir();repo=Path(__file__).resolve().parent
    payload={n:base64.b64encode((repo/n).read_bytes()).decode() for n in FILES}
    script=(repo/'install_code_publisher.py').read_text().replace('PAYLOAD = None','PAYLOAD = '+repr(payload))
    compile(script,'install-replica-ct-code.py','exec');(out/'install-replica-ct-code.py').write_text(script)
    (out/'rollback-replica-ct-code.py').write_bytes((repo/'rollback_code_publisher.py').read_bytes())
    # Bootstrap kit is copied/verified independently, never trusted from code download.
    for n in FILES+['code_builder.py']:(out/n).write_bytes((repo/n).read_bytes())
    lines=[hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name for p in sorted(out.iterdir())]
    (out/'SHA256SUMS').write_text('\n'.join(lines)+'\n');return lines
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination');a=p.parse_args();print('\n'.join(build(a.destination)))
