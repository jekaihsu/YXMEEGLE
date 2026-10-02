import hashlib,json,textwrap
import pytest
from scripts import formal_upload_permissions as repair


def fixture_plan():
    entries=[{'relative':'.','uid':0,'gid':0,'mode':511,'kind':'directory','inode':1,'device':2,'size':None}]
    digest=hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'ok':True,'manifest':entries,'manifest_sha256':digest,'entry_count':1,'applied':False}


def test_fixed_remote_programs_compile_and_boundaries():
    for program in (repair.PLAN,repair.APPLY,repair.STATUS):
        compile(repair.COMMON+'\nexpected_hash="hash"\n'+program,'repair','exec')
    assert "root=Path('/data/uploads')" in repair.COMMON
    assert 'ensure(len(children)==2)' in repair.COMMON
    assert 'ensure(len(files)==1)' in repair.COMMON
    assert 's.st_nlink==1' in repair.COMMON
    assert 'os.O_NOFOLLOW' in repair.APPLY
    assert repair.APPLY.index("write('original.json'")<repair.APPLY.index('os.fchown')
    assert repair.APPLY.index("write('attempt.json'")<repair.APPLY.index('os.fchown')
    assert 'os.fchown' not in repair.PLAN+repair.STATUS


def test_manifest_saved_privately_but_not_printed(tmp_path,monkeypatch):
    monkeypatch.setattr(repair,'STATE',tmp_path)
    monkeypatch.setattr(repair,'remote',lambda _:fixture_plan())
    result=repair.perform('plan')
    assert 'manifest' not in result
    assert json.loads((tmp_path/'plan.json').read_text())['manifest']


def test_unknown_apply_cannot_repeat(tmp_path,monkeypatch):
    monkeypatch.setattr(repair,'STATE',tmp_path)
    (tmp_path/'plan.json').write_text(json.dumps(fixture_plan()))
    def remote(source):
        assert (tmp_path/'dispatch.json').exists()
        raise RuntimeError('unknown')
    monkeypatch.setattr(repair,'remote',remote)
    with pytest.raises(RuntimeError):repair.perform('apply')
    monkeypatch.setattr(repair,'remote',lambda _:pytest.fail('must not repeat'))
    with pytest.raises(FileExistsError):repair.perform('apply')


def test_changed_plan_rejected_before_remote(tmp_path,monkeypatch):
    monkeypatch.setattr(repair,'STATE',tmp_path);plan=fixture_plan();plan['manifest'][0]['uid']=1
    (tmp_path/'plan.json').write_text(json.dumps(plan))
    monkeypatch.setattr(repair,'remote',lambda _:pytest.fail('must not dispatch'))
    with pytest.raises(RuntimeError,match='changed'):repair.perform('apply')


def test_root_permissions_are_changed_last():
    from pathlib import Path
    entries=[{'relative':'.'},{'relative':'namespace'},{'relative':'namespace/file'}]
    assert sorted(entries,key=lambda x:len(Path(x['relative']).parts),reverse=True)[-1]['relative']=='.'
