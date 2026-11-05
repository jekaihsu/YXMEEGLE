import json
from types import SimpleNamespace
import pytest
from scripts import verify_frozen_release_source as verifier


@pytest.fixture
def frozen_release(tmp_path,monkeypatch):
 root=tmp_path
 stage=root/'.runtime/zeabur-stage-ced7de7d'
 stage.mkdir(parents=True)
 entries=[]
 for name in verifier.FILES:
  path=stage/name
  path.parent.mkdir(parents=True,exist_ok=True)
  path.write_text('synthetic release source: '+name,encoding='utf-8')
  entries.append({'path':name,'sha256':verifier.hashlib.sha256(path.read_bytes()).hexdigest()})
 manifest=root/'.runtime/zeabur-stage-ced7de7d-manifest.json'
 manifest.write_text(json.dumps({'directory':str(stage),'files':entries}),encoding='utf-8')
 monkeypatch.setattr(verifier,'ROOT',root)
 monkeypatch.setattr(verifier,'STAGE',stage)
 return verifier.expected_hashes()


def test_frozen_manifest_hashes_match(frozen_release):
 assert set(verifier.expected_hashes())==set(verifier.FILES)


def test_unknown_target_never_dispatches(monkeypatch):
 monkeypatch.setattr(verifier.subprocess,'run',lambda *a,**kw:pytest.fail('no dispatch'))
 with pytest.raises(ValueError):verifier.verify('other')


def test_remote_program_never_reads_environment_or_prints_cmdline():
 compile('expected={}\n'+verifier.REMOTE,'remote','exec')
 assert 'environ' not in verifier.REMOTE
 assert "'processes':processes" in verifier.REMOTE
 assert "b'-c' in arguments" in verifier.REMOTE
 assert 'effective_uid' in verifier.REMOTE


def test_fixed_service_dispatch_suppresses_raw_output(monkeypatch,frozen_release):
 def run(command,**kwargs):
  assert command[command.index('--id')+1]==verifier.SERVICES['staging']
  assert command[command.index('--env-id')+1]==verifier.ENV
  return SimpleNamespace(returncode=1,stdout='PRIVATE',stderr='PRIVATE')
 monkeypatch.setattr(verifier.subprocess,'run',run)
 with pytest.raises(RuntimeError) as error:verifier.verify('staging')
 assert 'PRIVATE' not in str(error.value)

@pytest.mark.parametrize('uids,expected',[( [10001,10001,10001],True),([0,10001,10001],False),([10001,10001,0],False),([10001,10001],False)])
def test_success_requires_all_three_runtime_processes_at_uid_10001(tmp_path,monkeypatch,frozen_release,uids,expected):
 hashes=frozen_release
 monkeypatch.setattr(verifier,'expected_hashes',lambda:hashes)
 monkeypatch.setattr(verifier,'ROOT',tmp_path);(tmp_path/'.runtime').mkdir(exist_ok=True)
 receipt={'checks':[{'path':p,'expected_sha256':h,'actual_sha256':h,'match':True}for p,h in hashes.items()],
          'files_match':True,'web_and_worker_present':True,
          'processes':[{'name':name,'pid':i+1,'effective_uid':uid}for i,(name,uid)in enumerate(zip(['run_service','web','worker'],uids))]}
 monkeypatch.setattr(verifier.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=verifier.MARKER+json.dumps(receipt),stderr=''))
 result=verifier.verify('staging')
 assert result['ok'] is expected
 assert result['runtime_uid_10001_verified'] is expected
 assert (tmp_path/'.runtime'/('release-source-staging-'+verifier.STAGE.name.removeprefix('zeabur-stage-')+'.json')).exists()
