import json
from types import SimpleNamespace
import pytest
from scripts import formal_rollout_status as probe


def test_health_program_is_readonly_and_no_application_import():
 compile(probe.REMOTE,'remote','exec')
 assert 'SET TRANSACTION READ ONLY' in probe.REMOTE
 assert 'isolation_level=\'REPEATABLE READ\'' in probe.REMOTE
 assert 'backend.app' not in probe.REMOTE
 assert 'baseline_required' in probe.REMOTE
 for mutation in ('INSERT ','UPDATE ','DELETE ','create_all','migration'):
  assert mutation not in probe.REMOTE


def test_status_returns_only_fixed_deployment_metadata(monkeypatch):
 def run(command,**kwargs):
  assert command[command.index('--service-id')+1]==probe.SERVICE
  assert command[command.index('--env-id')+1]==probe.ENV
  return SimpleNamespace(returncode=0,stdout=json.dumps({'ID':'deployment','serviceID':probe.SERVICE,'environmentID':probe.ENV,'status':'RUNNING','secret':'HIDDEN'}))
 monkeypatch.setattr(probe.subprocess,'run',run)
 result=probe.status();assert result['status']=='RUNNING' and 'secret'not in result


def test_wrong_service_response_rejected(monkeypatch):
 monkeypatch.setattr(probe.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=json.dumps({'serviceID':'other'})))
 with pytest.raises(RuntimeError):probe.status()
