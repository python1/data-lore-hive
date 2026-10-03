"""Real signatures, Git bundles, storage transactions; no remote hosts or model calls."""
import io
import builtins
from contextlib import contextmanager, ExitStack
import stat
import sys
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import code_release as c
import code_publisher as p
import code_builder as b
import code_sync
import build_code_installer
import replication as r

@contextmanager
def installer_filesystem_guard(sandbox):
 """Reject host filesystem access, including metadata probes and symlink escapes.

 Only active around emulated installer execution. External commands must already
 be mocked; Popen is blocked as a backstop. This is a test tripwire, not an OS
 security boundary for hostile Python code.
 """
 root=os.path.abspath(sandbox)
 real_lstat=os.lstat
 opened={}
 def identity(fd):
  info=os.fstat(fd);return info.st_dev,info.st_ino
 def check(path):
  if isinstance(path,int):
   if path not in opened or identity(path)!=opened[path]:
    raise AssertionError('Installer filesystem escape: descriptor path')
   return
  path=os.path.abspath(os.fsdecode(path))
  if os.path.commonpath((root,path))!=root:
   raise AssertionError('Installer filesystem escape: '+path)
  # Reject symlinks even when their targets happen to be inside the sandbox.
  relative=os.path.relpath(path,root)
  current=root
  for part in (() if relative=='.' else relative.split(os.sep)):
   current=os.path.join(current,part)
   try:mode=real_lstat(current).st_mode
   except FileNotFoundError:break
   if stat.S_ISLNK(mode):raise AssertionError('Installer symlink escape: '+current)
 def guarded(original,positions):
  def call(*args,**kwargs):
   if any(v is not None for k,v in kwargs.items() if k.endswith('dir_fd')):
    raise AssertionError('Installer filesystem escape: dir_fd')
   for position,name in positions:
    check(args[position] if len(args)>position else kwargs[name])
   result=original(*args,**kwargs)
   if original is real_open:opened[result]=identity(result)
   return result
  return call
 real_open=os.open
 with ExitStack() as stack:
  for module,name in [(builtins,'open'),(io,'open')]:
   stack.enter_context(patch.object(module,name,guarded(getattr(module,name),[(0,'file')])))
  for name in ('open','stat','lstat','access','scandir','listdir','mkdir','rmdir',
               'remove','unlink','chmod','chown','readlink','truncate','utime'):
   stack.enter_context(patch.object(os,name,guarded(getattr(os,name),[(0,'path')])))
  for name in ('rename','replace','link','symlink'):
   stack.enter_context(patch.object(os,name,guarded(getattr(os,name),[(0,'src'),(1,'dst')])))
  stack.enter_context(patch.object(subprocess,'Popen',side_effect=AssertionError('Installer subprocess escaped emulation')))
  yield

class CodeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.repo=self.root/'repo';self.repo.mkdir();c.git('init','-b','master',str(self.repo))
  c.git('config','user.email','test@example.invalid',cwd=self.repo);c.git('config','user.name','Test',cwd=self.repo)
  (self.repo/'test_ok.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_ok(self):self.assertTrue(True)\n')
  c.git('add','.',cwd=self.repo);c.git('commit','-m','baseline',cwd=self.repo)
  self.commit=c.git('rev-parse','HEAD',cwd=self.repo).decode().strip()
  self.key=self.root/'signing';subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(self.key)],check=True)
  self.signers=self.root/'signers';self.signers.write_text('aster-hive namespaces="hive-release" '+self.key.with_suffix('.pub').read_text())
  self.store=self.root/'budget';self.store.mkdir();self.code=self.store/'code';self.code.mkdir()
  self.config={'store':str(self.code),'budget_root':str(self.store),'signers':str(self.signers),'reserve':0,'budget':32*1024**2}
  self.candidate=self.root/'candidate';self.fixture(self.candidate)
 def fixture(self,out,sequence=0,passed=True):
  out.mkdir();c.git('bundle','create',str(out/'hive.bundle'),'refs/heads/master',cwd=self.repo)
  evidence=c.canonical({'commit':self.commit,'tests_passed':passed,'smoke_passed':passed})
  (out/'evidence.json').write_bytes(evidence)
  m={'format':1,'project':c.PROJECT,'sequence':sequence,'commit':self.commit,'bundle_sha256':c.digest((out/'hive.bundle').read_bytes()),'bundle_bytes':(out/'hive.bundle').stat().st_size,'evidence_sha256':c.digest(evidence),'compatibility':{'memory_protocol':1,'receiver_protocol':2,'minimum_ollama':'0.32.14'}}
  (out/'manifest.json').write_bytes(c.canonical(m));(out/'manifest.sig').write_bytes(b'')
  if sequence:self.sign(out)
  return out
 def sign(self,out,key=None):
  signature=out/'manifest.json.sig'
  if signature.exists():signature.unlink()
  subprocess.run(['ssh-keygen','-Y','sign','-f',str(key or self.key),'-n',c.NAMESPACE,str(out/'manifest.json')],check=True,capture_output=True)
  signature.replace(out/'manifest.sig')
 def approval(self,n=1,passed=True):return self.fixture(self.root/('release-'+str(n)),n,passed)
 def wire(self,command,package=None,pin=None):
  f=io.BytesIO();p.send(f,command,package,pin);f.seek(0);return f
 def accept(self,package,command='approve',**kw):return p.publish(self.config,self.wire(command,package),**kw)
 def pin(self,h,seq=1):
  raw=c.canonical({'project':c.PROJECT,'action':'recovery-tested','sequence':seq,'release':h,'drill_sha256':'d'*64})
  f=self.root/'pin';f.write_bytes(raw)
  if f.with_suffix('.sig').exists():f.with_suffix('.sig').unlink()
  subprocess.run(['ssh-keygen','-Y','sign','-f',str(self.key),'-n',c.NAMESPACE,str(f)],check=True,capture_output=True)
  return {'manifest':raw.decode(),'signature':f.with_suffix('.sig').read_text()}
 def test_unsigned_wrong_key_modified_and_incomplete_refused(self):
  with self.assertRaises(ValueError):self.accept(self.candidate)
  approved=self.approval();other=self.root/'other'
  subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(other)],check=True)
  self.sign(approved,other)
  with self.assertRaises(ValueError):self.accept(approved)
  self.sign(approved);(approved/'hive.bundle').write_bytes((approved/'hive.bundle').read_bytes()+b'changed')
  with self.assertRaises(ValueError):self.accept(approved)
  (approved/'evidence.json').unlink()
  with self.assertRaises((ValueError,FileNotFoundError)):c.validate(approved,self.signers)
  self.assertIsNone(p.state(self.code)['current'])
 def test_duplicate_and_rollback_conflicting_sequence(self):
  one=self.approval();first=self.accept(one);self.assertEqual(first,self.accept(one))
  self.accept(self.approval(2))
  with self.assertRaises(ValueError):self.accept(one)
  two=self.root/'release-2';m=c.decode((two/'manifest.json').read_bytes());m['evidence_sha256']='f'*64;(two/'manifest.json').write_bytes(c.canonical(m));self.sign(two)
  with self.assertRaises(ValueError):self.accept(two)
  self.assertEqual(p.state(self.code)['sequence'],2)
 def test_interrupted_transfer_and_every_publication_boundary_preserve_current(self):
  first=self.accept(self.approval());two=self.approval(2)
  wire=self.wire('approve',two).read()
  with self.assertRaises(ValueError):p.publish(self.config,io.BytesIO(wire[:-10]))
  for stage in ('received','stored','before_index'):
   def fail(point):
    if point==stage:raise RuntimeError('simulated power interruption')
   with self.assertRaises(RuntimeError):self.accept(two,fault=fail)
   self.assertEqual(p.state(self.code),first)
  self.assertEqual(self.accept(two)['sequence'],2)
 def test_shared_lock_serializes_memory_and_code(self):
  package=self.approval();done=threading.Event();errors=[]
  def worker():
   try:self.accept(package)
   except Exception as e:errors.append(e)
   finally:done.set()
  with r.locked(self.store):
   thread=threading.Thread(target=worker);thread.start();time.sleep(.1);self.assertFalse(done.is_set())
   (self.store/'memory-generation').write_bytes(b'memory' * 100)
  thread.join(10);self.assertTrue(done.is_set());self.assertEqual(errors,[])
 def test_oversized_and_budget_refusal_preserve_memory(self):
  memory=self.store/'memory';memory.write_bytes(b'protected')
  header=c.canonical({'command':'candidate','lengths':{n:c.MAX_BUNDLE+1 for n in c.FILES},'pin':None})
  import struct
  with self.assertRaises(ValueError):p.publish(self.config,io.BytesIO(struct.pack('!I',len(header))+header))
  with self.assertRaises(ValueError):p.publish({**self.config,'budget':1},self.wire('candidate',self.candidate))
  self.assertEqual(memory.read_bytes(),b'protected')
 def test_bad_valid_candidates_and_signed_broken_release_preserve_pin(self):
  good=self.accept(self.approval(),now=1_700_000_000);h=good['current']
  p.publish(self.config,self.wire('pin',pin=self.pin(h)),now=1_700_000_001)
  # Signed functional bug: claimed tests pass, actual code fails recovery. Signatures cannot detect this.
  (self.repo/'recover.py').write_text('raise SystemExit("deliberately broken recovery")\n');c.git('add','.',cwd=self.repo);c.git('commit','-m','bad but structurally valid',cwd=self.repo)
  self.commit=c.git('rev-parse','HEAD',cwd=self.repo).decode().strip()
  for n in range(2,13):self.accept(self.approval(n),now=1_700_000_000+n*86400*32)
  for n in range(4):self.accept(self.fixture(self.root/('bad-candidate-'+str(n))),command='candidate',now=1_740_000_000+n)
  index=p.state(self.code);self.assertEqual(index['pin'],h);self.assertIn(h,index['releases']);self.assertLessEqual(len(index['releases']),8);self.assertLessEqual(len(index['candidates']),2)
  gooddir=self.code/'objects'/h;c.validate(gooddir,self.signers)
  clone=self.root/'restored-good';c.git('clone',str(gooddir/'hive.bundle'),str(clone));self.assertFalse((clone/'recover.py').exists())
  result=subprocess.run(['python3','-m','unittest','discover'],cwd=clone,capture_output=True);self.assertEqual(result.returncode,0)
  broken=self.root/'restored-bad';c.git('clone',str(self.code/'objects'/index['current']/'hive.bundle'),str(broken))
  self.assertNotEqual(subprocess.run(['python3','recover.py'],cwd=broken,capture_output=True).returncode,0)
 def test_failing_evidence_cannot_be_approved(self):
  with self.assertRaises(ValueError):self.accept(self.approval(passed=False))
 def test_readonly_api_rejects_writes_shell_retention_and_path_escape(self):
  index=self.accept(self.approval());h=index['current']
  for command in ('rm -rf /','pin','approve','code-fetch ../../etc/passwd manifest.json','code-fetch '+h+' ../../etc/passwd','code-fetch '+h+' allowed_signers'):
   with self.assertRaises(ValueError):p.read(self.config,command,io.BytesIO())
  self.assertEqual((self.code/'index.json').stat().st_mode & 0o777,0o644)
  out=io.BytesIO();p.read(self.config,'code-fetch '+h+' manifest.json',out);self.assertEqual(out.getvalue(),(self.code/'objects'/h/'manifest.json').read_bytes())
  for command in ('shell','retention','keys','delete'):
   with self.assertRaises(ValueError):p.publish(self.config,self.wire(command))
  self.assertEqual(p.state(self.code),index)
 def test_clean_bootstrap_receipt_and_rollback(self):
  one=self.approval();self.accept(one);receipt=self.root/'phone.json';receipt.write_bytes(c.canonical({'sequence':1,'manifest_sha256':c.digest((one/'manifest.json').read_bytes())}))
  state=self.root/'client-state';self.assertTrue(c.bootstrap_verify(one,self.signers,receipt,state)['verified'])
  two=self.approval(2);c.bootstrap_verify(two,self.signers,receipt,state)
  with self.assertRaises(ValueError):c.bootstrap_verify(one,self.signers,receipt,state)
  self.assertEqual(json.loads(state.read_text())['sequence'],2)
 def test_installer_build_compiles_and_has_separate_credentials(self):
  out=self.root/'installer';lines=build_code_installer.build(out)
  compile((out/'install-replica-ct-code.py').read_text(),'installer','exec');self.assertEqual(len(lines),8)
  text=(out/'install-replica-ct-code.py').read_text();self.assertIn('Signing and transport keys must differ',text);self.assertIn('NoNewPrivileges=true',text)
 def test_auto_sync_idempotence_and_failure_status(self):
  state=self.root/'sync';state.mkdir();approvals=self.root/'approvals';approvals.mkdir()
  config={'repo':str(self.repo),'state_dir':str(state),'approvals':str(approvals),'signers':str(self.signers),'ssh':{}}
  calls=[]
  def transport(conf,command,package=None,pin=None):
   calls.append(command);return p.publish(self.config,self.wire(command,package,pin))
  def builder(repo,dest):shutil.copytree(self.candidate,dest)
  with patch('code_sync.code_builder.build',side_effect=builder),patch('code_sync.code_transport.upload',side_effect=transport):
   self.assertEqual(code_sync.tick(config,now=0)['status'],'ok');self.assertEqual(code_sync.tick(config,now=1)['status'],'ok')
  self.assertEqual(calls.count('candidate'),1);messages=[]
  with patch('code_sync.code_transport.upload',side_effect=OSError('offline')):
   code_sync.tick(config,now=2,notifier=messages.append);status=code_sync.tick(config,now=1803,notifier=messages.append)
  self.assertEqual(status['status'],'failed');self.assertEqual(len(messages),1)
 def test_valid_same_number_conflict_and_signed_pin_replay(self):
  release=self.approval();index=self.accept(release);h=index['current']
  pin=self.pin(h);p.publish(self.config,self.wire('pin',pin=pin))
  with self.assertRaises(ValueError):p.publish(self.config,self.wire('pin',pin=pin))
  evidence=c.decode((release/'evidence.json').read_bytes());evidence['comment']='different valid manifest'
  raw=c.canonical(evidence);(release/'evidence.json').write_bytes(raw)
  m=c.decode((release/'manifest.json').read_bytes());m['evidence_sha256']=c.digest(raw);(release/'manifest.json').write_bytes(c.canonical(m));self.sign(release)
  with self.assertRaises(ValueError):self.accept(release)
  self.assertEqual(p.state(self.code)['pin'],h)
 def test_explicit_pinned_rescue_does_not_lower_high_watermark(self):
  one=self.approval();two=self.approval(2);receipt=self.root/'receipt'
  receipt.write_bytes(c.canonical({'sequence':1,'manifest_sha256':c.digest((one/'manifest.json').read_bytes())}))
  state=self.root/'high';c.bootstrap_verify(two,self.signers,receipt,state);original=state.read_bytes()
  self.assertTrue(c.bootstrap_verify(one,self.signers,receipt,state,rescue=True)['rescue'])
  self.assertEqual(state.read_bytes(),original)
  with self.assertRaises(ValueError):c.bootstrap_verify(two,self.signers,receipt,state,rescue=True)
 def test_upload_bridge_refuses_shell_before_opening_socket(self):
  import code_transport
  with patch.dict(os.environ,{'SSH_ORIGINAL_COMMAND':'sh'}),patch('code_transport.socket.socket') as sock:
   with self.assertRaises(ValueError):code_transport.bridge({'socket':'unused'})
   sock.assert_not_called()
 def test_orphan_after_crash_cleaned_without_dropping_current(self):
  self.accept(self.approval());orphan=self.code/'objects'/('a'*64);orphan.mkdir();(orphan/'junk').write_bytes(b'x')
  self.accept(self.approval(2));self.assertFalse(orphan.exists());self.assertEqual(p.state(self.code)['sequence'],2)
 def test_builder_exact_master_with_isolated_tests_smoke_and_sensitive_history(self):
  # Copy production modules, not this test file, so the nested suite cannot recurse.
  source=Path(__file__).resolve().parent
  for module in source.glob('*.py'):
   if not module.name.startswith('test_'):(self.repo/module.name).write_bytes(module.read_bytes())
  c.git('add','.',cwd=self.repo);c.git('commit','-m','smoke-capable fixture',cwd=self.repo)
  built=self.root/'built';m=b.build(self.repo,built)
  evidence=c.decode((built/'evidence.json').read_bytes())
  self.assertTrue(evidence['tests_passed']);self.assertTrue(evidence['smoke_passed'],evidence)
  self.assertEqual(m['commit'],c.git('rev-parse','master',cwd=self.repo).decode().strip())
  (self.repo/'accidental.key').write_text('not a real key');c.git('add','.',cwd=self.repo);c.git('commit','-m','forbidden fixture',cwd=self.repo)
  with self.assertRaises(ValueError):b.build(self.repo,self.root/'sensitive')
 def test_independent_bootstrap_fetches_all_files_before_verification(self):
  release=self.approval();index=self.accept(release);h=index['current'];download=self.root/'download';download.mkdir()
  for name in c.FILES:
   with (download/name).open('wb') as output:p.read(self.config,'code-fetch '+h+' '+name,output)
  receipt=self.root/'phone';receipt.write_bytes(c.canonical({'sequence':1,'manifest_sha256':h}))
  result=c.bootstrap_verify(download,self.signers,receipt,self.root/'fresh-trust-state')
  self.assertEqual(result['commit'],self.commit)
 def test_fake_upload_cannot_sign_approve_or_change_pin(self):
  self.accept(self.candidate,'candidate')
  forged={'manifest':c.canonical({'project':c.PROJECT,'action':'recovery-tested','sequence':1,'release':'0'*64,'drill_sha256':'a'*64}).decode(),'signature':'fake'}
  with self.assertRaises(ValueError):p.publish(self.config,self.wire('pin',pin=forged))
  self.assertIsNone(p.state(self.code)['pin']);self.assertIsNone(p.state(self.code)['current'])
 def test_unsupported_compatibility_and_wrong_namespace_fail_closed(self):
  release=self.approval();signature=release/'manifest.json.sig'
  subprocess.run(['ssh-keygen','-Y','sign','-f',str(self.key),'-n','unrelated',str(release/'manifest.json')],capture_output=True,check=True)
  signature.replace(release/'manifest.sig')
  with self.assertRaises(ValueError):self.accept(release)
  m=c.decode((release/'manifest.json').read_bytes());m['compatibility']['memory_protocol']=999
  (release/'manifest.json').write_bytes(c.canonical(m));self.sign(release)
  with self.assertRaises(ValueError):self.accept(release)
 def test_source_branch_and_experimental_refs_excluded(self):
  c.git('branch','experimental',cwd=self.repo)
  heads=c.git('bundle','list-heads',str(self.candidate/'hive.bundle')).decode()
  self.assertEqual(heads.strip(),self.commit+' refs/heads/master')
 def test_reserve_refusal_and_clock_rollback_preserve_approved(self):
  first=self.accept(self.approval(),now=100)
  with self.assertRaises(ValueError):self.accept(self.approval(2),now=99)
  with self.assertRaises(ValueError):p.publish({**self.config,'reserve':10**18},self.wire('candidate',self.candidate),now=101)
  self.assertEqual(p.state(self.code),first)
 def test_receive_never_executes_bundle_code(self):
  marker=self.root/'execution-marker'
  (self.repo/'setup.py').write_text('from pathlib import Path\nPath('+repr(str(marker))+').touch()\n')
  c.git('add','.',cwd=self.repo);c.git('commit','-m','execution trap',cwd=self.repo)
  self.commit=c.git('rev-parse','HEAD',cwd=self.repo).decode().strip()
  self.accept(self.approval());self.assertFalse(marker.exists())
 def test_installer_files_and_service_emulated_without_root(self):
  import base64,types,install_code_publisher as installer
  sandbox=self.root.resolve()/'install-emulation';sandbox.mkdir()
  real_path=Path
  def mapped(value):
   value=real_path(value)
   if value.is_absolute() and value.is_relative_to(sandbox):return value
   return sandbox/str(value).lstrip('/')
  base=mapped('/usr/local/lib/hive-code');base.parent.mkdir(parents=True)
  config=mapped('/etc/hive-code');config.parent.mkdir(parents=True)
  store=mapped('/var/lib/hive-replica');store.mkdir(parents=True);(store/'receiver.lock').touch()
  recovery=mapped('/var/lib/hive-recovery/.ssh/authorized_keys');recovery.parent.mkdir(parents=True)
  original='restrict,command="/usr/bin/python3 /usr/local/lib/hive-recovery/recovery_server.py" ssh-ed25519 unrelated-key\n';recovery.write_text(original)
  mapped('/etc/systemd/system').mkdir(parents=True)
  receiver_config=mapped('/etc/hive-replica/config.json');receiver_config.parent.mkdir(parents=True)
  receiver_config.write_text(json.dumps({'store':str(store),'retention_policy':'recent3-hourly6-daily7-pin1-v2'}))
  wrapper=mapped('/usr/local/lib/hive-replica/replication.py');wrapper.parent.mkdir(parents=True);wrapper.write_text('# previous wrapper\n')
  upload=self.root/'uploadkey';subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(upload)],check=True)
  signing_public=sandbox/'signing.pub';shutil.copyfile(str(self.key)+'.pub',signing_public)
  upload_public=sandbox/'upload.pub';shutil.copyfile(str(upload)+'.pub',upload_public)
  root_auth=mapped('/root/.ssh/authorized_keys');root_auth.parent.mkdir(parents=True)
  root_auth.write_text('ssh-ed25519 unrelated-root-key\n')
  replica_auth=mapped('/etc/hive-replica/authorized_keys')
  replica_auth.write_text('ssh-ed25519 unrelated-replica-key\n')
  commands=[];created=set();uid=os.getuid();gid=os.getgid()
  def run(*args):
   commands.append(args)
   if args[:2]==('sshd','-T'):return b'forcecommand none\nauthorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2\n'
   if args[0]=='useradd':created.add(args[-1])
   if args[:2]==('systemctl','is-active'):return b'active\n'
   return b'local emulation only\n'
  def user(name):
   if name not in created:raise KeyError(name)
   return types.SimpleNamespace(pw_uid=uid,pw_gid=gid)
  # Avoid argparse's host locale-file lookup; keep real argument parsing.
  with patch.object(installer,'Path',side_effect=mapped),patch.object(installer,'BASE',base),patch.object(installer,'CONFIG',config),patch.object(installer,'STORE',store),patch.object(installer,'PAYLOAD',{'stub.py':base64.b64encode(b'pass\n').decode()}),patch.object(installer,'run',side_effect=run),patch.object(installer.os,'geteuid',return_value=0),patch.object(installer.os,'uname',return_value=types.SimpleNamespace(nodename='replica-host')),patch.object(installer.shutil,'which',return_value='/test/tool'),patch.object(installer.pwd,'getpwnam',side_effect=user),patch('sys.argv',['installer','--signing-public-key',str(signing_public),'--upload-public-key',str(upload_public)]),patch.object(sys,'path',sys.path.copy()),patch.object(installer.argparse,'_',side_effect=lambda message:message),installer_filesystem_guard(sandbox):
   installer.main()
  self.assertEqual(root_auth.read_text(),'ssh-ed25519 unrelated-root-key\n')
  self.assertEqual((config/'backups/authorized_keys').read_text(),original)
  self.assertEqual((config/'backups/memory-wrapper.py').read_text(),'# previous wrapper\n')
  self.assertTrue(json.loads(receiver_config.read_text())['code_budget_reader'])
  self.assertIn('code_transport.py reader',recovery.read_text())
  upload_auth=mapped('/var/lib/hive-code-upload/.ssh/authorized_keys').read_text()
  self.assertIn('restrict,command=',upload_auth);self.assertIn(' bridge ',upload_auth)
  unit=mapped('/etc/systemd/system/hive-code-publisher.service').read_text()
  for fragment in ('User=hive-code-publisher','ProtectSystem=strict','NoNewPrivileges=true','RestrictAddressFamilies=AF_UNIX','ReadWritePaths='):self.assertIn(fragment,unit)
  self.assertTrue(any(v[:3]==('systemctl','enable','--now') for v in commands))
  self.assertTrue(any(v[0]=='setfacl' and 'u:hive-code-publisher:rw-,u:hive-recovery:r--' in v for v in commands))
 def test_installer_emulation_guard_rejects_real_paths_and_bypasses(self):
  sandbox=self.root.resolve()/'guard';sandbox.mkdir()
  # Existing outside sentinel makes an accidental read visible on every OS.
  outside=self.root.resolve()/'host-sentinel';outside.write_text('must not read')
  alias=sandbox/'escape';alias.symlink_to(outside)
  with installer_filesystem_guard(sandbox):
   for name,operation in [
    ('linux root metadata',lambda:Path('/root/.ssh/authorized_keys').exists()),
    ('unmapped Path read',lambda:outside.read_text()),
    ('parent traversal',lambda:(sandbox/'..'/'host-sentinel').read_text()),
    ('builtin open',lambda:open(outside)),
    ('raw descriptor',lambda:os.open(outside,os.O_RDONLY)),
    ('directory scan',lambda:os.listdir(outside.parent)),
    ('write',lambda:outside.write_text('changed')),
    ('rename destination',lambda:os.replace(sandbox/'missing',outside)),
    ('symlink',lambda:alias.read_text()),
    ('process',lambda:subprocess.run(['true']))]:
    with self.subTest(operation=name),self.assertRaisesRegex(AssertionError,'Installer'):
     operation()
  self.assertEqual(outside.read_text(),'must not read')

 def test_real_memory_retention_and_code_publish_concurrently(self):
  import hive,retention
  db=self.root/'memory.sqlite3';hive.initialize(db);hive.append(db,'r','test','claim',{'n':1})
  package=self.root/'snapshot';manifest=r.snapshot(db,package,'shared-test')
  memory_config={'store':str(self.store),'database_id':'shared-test','pins':[manifest['sha256']],'budget':32*1024**2,'reserve':0,'code_budget_reader':True}
  def wire():
   stream=io.BytesIO();r.send(package,stream);stream.seek(0);return stream
  retention.accept(memory_config,wire())
  hive.append(db,'r','test','claim',{'n':2});new=self.root/'next';r.snapshot(db,new,'shared-test')
  mem=io.BytesIO();r.send(new,mem);mem.seek(0);release=self.approval();barrier=threading.Barrier(2);errors=[]
  def task(fn):
   try:barrier.wait();fn()
   except Exception as e:errors.append(e)
  workers=[threading.Thread(target=task,args=(lambda:retention.accept(memory_config,mem),)),threading.Thread(target=task,args=(lambda:self.accept(release),))]
  for worker in workers:worker.start()
  for worker in workers:worker.join(15);self.assertFalse(worker.is_alive())
  self.assertEqual(errors,[]);self.assertEqual(retention.status(memory_config)['manifest']['event_count'],2)
  self.assertEqual(p.state(self.code)['sequence'],1)
  self.assertTrue((self.store/'generations'/manifest['sha256']).is_dir())
  self.assertEqual((self.store/'generations'/manifest['sha256']).stat().st_mode & 0o777,0o750)
 def test_unreadable_budget_tree_is_not_silently_ignored(self):
  def unreadable(root,onerror):
   onerror(PermissionError('protected directory'))
   yield
  with patch('code_publisher.os.walk',side_effect=unreadable):
   with self.assertRaisesRegex(ValueError,'Cannot account'):p.budget(self.config,0)
 def test_budget_symlink_refuses_publication(self):
  (self.store/'unaccounted').symlink_to(self.root/'repo',target_is_directory=True)
  with self.assertRaisesRegex(ValueError,'symlink'):self.accept(self.approval())
