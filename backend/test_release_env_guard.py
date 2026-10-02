import json
import pytest
from scripts import prepare_release_settings as prepare
from scripts.release_env_guard import APP_SERVICE, REQUIRED_KEYS, validate_request


def full_environment():
    return {**dict.fromkeys(REQUIRED_KEYS,'configured'), 'DATABASE_URL':'postgresql://unit:fake@localhost/workspace',
        'SESSION_SECRET':'test-secret-never-print'*3,'DEMO_MODE':'true','ALLOW_CLOUD_DEMO':'true',
        'LARK_APP_ID':'cli_aa3cab98b2789e17','LARK_ALLOWED_TENANTS':'test-company',
        'CUSTOM_MUST_PRESERVE':'private-custom-never-print'}


def request(values):
    return {'query':'mutation($s:ObjectID!,$data:Map!){updateEnvironmentVariable(serviceID:$s,data:$data)}',
        'variables':{'s':APP_SERVICE,'data':values}}


def test_guard_rejects_delta_without_values_in_error():
    with pytest.raises(ValueError) as exc:
        validate_request(request({'LARK_WORKER_IDENTITY':'application','SECRET':'never-print-this'}))
    assert 'never-print' not in str(exc.value)


@pytest.mark.parametrize('key',sorted(REQUIRED_KEYS))
def test_guard_rejects_missing_or_empty_required_settings(key):
    for value in (None,'','  '):
        values=full_environment()
        if value is None: values.pop(key)
        else: values[key]=value
        with pytest.raises(ValueError): validate_request(request(values))


def test_guard_accepts_complete_map_and_read_queries():
    validate_request(request(full_environment()))
    validate_request({'query':'query{service{variables{key value}}}'})


def test_prepare_preserves_complete_map_and_rejects_incomplete_snapshot(tmp_path,monkeypatch,capsys):
    runtime=tmp_path/'.runtime';runtime.mkdir()
    deployment=tmp_path/'deployment';deployment.mkdir()
    (deployment/'source-tables.json').write_text(json.dumps([{'kind':'daily','base_token':'base1','table_id':'tbl1'}]))
    monkeypatch.setattr(prepare,'ROOT',tmp_path);monkeypatch.setattr(prepare,'RUNTIME',runtime)
    original=full_environment()
    snapshot=runtime/'release-current-env-response.json'
    def save(values): snapshot.write_text(json.dumps({'data':{'service':{'variables':[{'key':k,'value':v} for k,v in values.items()]}}}))
    save(original);prepare.main()
    actual=json.loads((runtime/'release-settings-request.json').read_text())['variables']['data']
    assert all(actual[k]==v for k,v in original.items() if k!='LARK_SOURCE_TABLES_JSON')
    assert actual['LARK_WORKER_IDENTITY']=='application'
    assert 'private-custom' not in capsys.readouterr().out
    snapshot_before=(runtime/'release-settings-request.json').read_bytes()
    broken=original.copy();broken.pop('DATABASE_URL');save(broken)
    with pytest.raises(SystemExit):prepare.main()
    assert (runtime/'release-settings-request.json').read_bytes()==snapshot_before
