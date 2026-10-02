import json
import pytest
from scripts import workbench_restore_setup as setup


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(setup,'STATE',tmp_path)
    return tmp_path


def test_manifest_private_pg_only():
    spec=setup.manifest('private-password')
    assert spec['source']=={'image':'postgres:17-alpine'}
    assert spec['portForwarding']=={'enabled':False}
    env={r['key']:r['default'] for r in spec['env']}
    assert env['POSTGRES_DB']=='workbench_restore_drill'
    assert env['POSTGRES_INITDB_ARGS']=='--auth-host=scram-sha-256'
    assert not any('LARK' in key or 'WORKER' in key for key in env)


def test_prepare_exact_target_marker_before_create(isolated,monkeypatch):
    monkeypatch.setattr(setup,'inventory',lambda:[])
    calls=[]
    def query(document,variables):
        calls.append((document,variables))
        assert (isolated/'create-attempt.json').exists()
        if document.startswith('mutation'):
            assert variables['p']==setup.PROJECT
            assert variables['s']['name']==setup.NAME
            return {'service':{'_id':'isolated-new-pg','name':setup.NAME}}
        assert variables=={'s':'isolated-new-pg','e':setup.ENV}
        return {'service':{'_id':'isolated-new-pg','name':setup.NAME,'status':'RUNNING'}}
    monkeypatch.setattr(setup,'query',query)
    result=setup.prepare()
    assert len(calls)==2 and result['restore_ready'] is False
    private=json.loads((isolated/'secrets.json').read_text())
    assert private['database_password'] not in json.dumps(result)
    assert len(private['database_password'])>=40


def test_unknown_outcome_never_recreates(isolated,monkeypatch):
    monkeypatch.setattr(setup,'inventory',lambda:[])
    setup.save('create-attempt.json',{'attempted':True})
    monkeypatch.setattr(setup,'query',lambda *args:pytest.fail('must not mutate'))
    with pytest.raises(RuntimeError,match='never recreate'):setup.prepare()


def test_existing_unknown_service_not_adopted(isolated,monkeypatch):
    monkeypatch.setattr(setup,'inventory',lambda:[{'_id':'existing','name':setup.NAME}])
    with pytest.raises(RuntimeError,match='never adopt'):setup.prepare()


def test_owned_service_is_idempotent(isolated,monkeypatch):
    monkeypatch.setattr(setup,'inventory',lambda:[{'_id':'existing','name':setup.NAME}])
    setup.save('created.json',{'service_id':'existing'})
    monkeypatch.setattr(setup,'query',lambda *args:pytest.fail('must not mutate'))
    assert setup.prepare()['service_id']=='existing'


@pytest.mark.parametrize('ident',sorted(setup.DENIED))
def test_formal_and_staging_never_targets(ident):
    with pytest.raises(RuntimeError,match='cannot be a restore target'):
        setup.exact([{'_id':ident,'name':setup.NAME}])


def test_duplicate_names_rejected():
    with pytest.raises(RuntimeError,match='Duplicate'):
        setup.exact([{'_id':'a','name':setup.NAME},{'_id':'b','name':setup.NAME}])
