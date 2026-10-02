import json
from copy import deepcopy
import pytest
from scripts import workbench_company_grant_scope as tool

def fixture():
    return {'LARK_APP_ID':tool.APP,'PUBLIC_ORIGIN':tool.ORIGIN,'DEMO_MODE':'false','ALLOW_CLOUD_DEMO':'false',
        'LARK_WORKER_ORGANIZATION':'tenant','LARK_ALLOWED_TENANTS':'tenant','DATABASE_URL':'secret-db',
        tool.KEY:json.dumps([{'app_id':tool.APP,'tenant':'tenant','open_id':tool.OPEN_ID,'enabled':True,'role':'manager',
            'grant_id':'grant','authorized_at':'2026-09-29T00:00:00Z','authorized_by':'owner','decision_ref':'approved',
            'reason':'explicit authorization','scopes':['preserved']}])}

def test_changes_only_scope_preserves_every_other_value():
    before=fixture();after=tool.intended(before)
    assert {k for k in before if before[k]!=after[k]}=={tool.KEY}
    assert json.loads(after[tool.KEY])[0]['scopes']==['preserved',tool.SCOPE]
    assert tool.intended(after)==after

def test_whole_map_cas_and_unknown_no_retry(tmp_path,monkeypatch):
    monkeypatch.setattr(tool,'STATE',tmp_path);before=fixture();reads=[];calls=[]
    def env(service):reads.append(service);return deepcopy(before)
    monkeypatch.setattr(tool,'environment',env)
    def query(*args):calls.append(args);raise RuntimeError('unknown')
    monkeypatch.setattr(tool,'query',query)
    with pytest.raises(RuntimeError):tool.run()
    assert len(reads)==2 and len(calls)==1 and (tmp_path/'attempt.json').exists()
    with pytest.raises(ValueError,match='Prior mutation'):tool.run()
    assert len(calls)==1

def test_concurrent_change_prevents_update(tmp_path,monkeypatch):
    monkeypatch.setattr(tool,'STATE',tmp_path);before=fixture();responses=iter([before,{**before,'OTHER':'new'}])
    monkeypatch.setattr(tool,'environment',lambda service:next(responses))
    monkeypatch.setattr(tool,'query',lambda *args:pytest.fail('must not update'))
    with pytest.raises(ValueError,match='Concurrent'):tool.run()
    assert not (tmp_path/'attempt.json').exists()
