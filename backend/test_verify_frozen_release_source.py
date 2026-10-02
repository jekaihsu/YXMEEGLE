import json
from types import SimpleNamespace
import pytest
from scripts import verify_frozen_release_source as verifier


def test_frozen_manifest_hashes_match():
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


def test_fixed_service_dispatch_suppresses_raw_output(monkeypatch):
 def run(command,**kwargs):
  assert command[command.index('--id')+1]==verifier.SERVICES['staging']
  assert command[command.index('--env-id')+1]==verifier.ENV
  return SimpleNamespace(returncode=1,stdout='PRIVATE',stderr='PRIVATE')
 monkeypatch.setattr(verifier.subprocess,'run',run)
 with pytest.raises(RuntimeError) as error:verifier.verify('staging')
 assert 'PRIVATE' not in str(error.value)

@pytest.mark.parametrize('uids,expected',[( [10001,10001,10001],True),([0,10001,10001],False),([10001,10001,0],False),([10001,10001],False)])
def test_success_requires_all_three_runtime_processes_at_uid_10001(tmp_path,monkeypatch,uids,expected):
 hashes=verifier.expected_hashes()
 monkeypatch.setattr(verifier,'expected_hashes',lambda:hashes)
 monkeypatch.setattr(verifier,'ROOT',tmp_path);(tmp_path/'.runtime').mkdir()
 receipt={'checks':[{'path':p,'expected_sha256':h,'actual_sha256':h,'match':True}for p,h in hashes.items()],
          'files_match':True,'web_and_worker_present':True,
          'processes':[{'name':name,'pid':i+1,'effective_uid':uid}for i,(name,uid)in enumerate(zip(['run_service','web','worker'],uids))]}
 monkeypatch.setattr(verifier.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=verifier.MARKER+json.dumps(receipt),stderr=''))
 result=verifier.verify('staging')
 assert result['ok'] is expected
 assert result['runtime_uid_10001_verified'] is expected
 assert (tmp_path/'.runtime'/('release-source-staging-'+verifier.STAGE.name.removeprefix('zeabur-stage-')+'.json')).exists()
