"""Local-only reproductions asserting current defects, without credentials."""
import json
import httpx
from sqlalchemy import create_engine, inspect, Table, Column, String, Integer, JSON
from sqlalchemy.orm import declarative_base
from backend.lark_adapter import LarkAdapter
from backend import storage
from scripts import backup_restore


def test_drive_folder_accepts_first_page_despite_duplicate_on_next():
    calls=[]
    def response(request):
        calls.append(str(request.url))
        second=request.url.params.get('page_token')=='next'
        return httpx.Response(200,json={'code':0,'data':{
            'files':[{'name':'Output','type':'folder','token':'second' if second else 'first'}],
            'has_more':not second,'next_page_token':'' if second else 'next'}})
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        assert LarkAdapter('synthetic',client).folder('parent','Output')=='first'
    assert len(calls)==1


def test_drive_folder_creates_after_incomplete_listing():
    calls=[]
    def response(request):
        calls.append(request.method)
        return httpx.Response(200,json={'code':0,'data':{} if request.method=='GET' else {'token':'created'}})
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        assert LarkAdapter('synthetic',client).folder('parent','Output')=='created'
    assert calls==['GET','POST']


def test_restore_drops_business_record_foreign_key(tmp_path):
    base=declarative_base()
    Table('workspaces',base.metadata,Column('id',String(120),primary_key=True),
          Column('version',Integer),Column('data',JSON))
    storage.models(base)
    original=create_engine('sqlite://')
    base.metadata.create_all(original)
    assert inspect(original).get_foreign_keys('business_records')[0]['referred_table']=='workspaces'
    # Produce an authentic empty archive from the normal application schema.
    archive=tmp_path/'backup.zip'
    backup_restore.backup(original,tmp_path/'uploads',archive)
    destination=create_engine('sqlite://')
    backup_restore.restore(destination,tmp_path/'restored',archive)
    # Startup create_all cannot repair a pre-existing table's missing constraint.
    base.metadata.create_all(destination)
    assert inspect(destination).get_foreign_keys('business_records')==[]
    original.dispose()
    destination.dispose()


def test_staging_deploy_accepts_unmanifested_private_file(tmp_path,monkeypatch):
    from scripts import workbench_cloud_setup as cloud
    from types import SimpleNamespace
    import hashlib
    monkeypatch.setattr(cloud,'ROOT',tmp_path)
    monkeypatch.setattr(cloud,'STATE',tmp_path/'.runtime/cloud-staging')
    stage=tmp_path/'.runtime/zeabur-stage-review';stage.mkdir(parents=True)
    (stage/'app.py').write_text('pass',encoding='utf-8')
    (stage/'backend').mkdir()
    (stage/'backend/private.json').write_text('{"synthetic":"not-real"}',encoding='utf-8')
    manifest={'directory':str(stage),'files':[{'path':'app.py','sha256':hashlib.sha256(b'pass').hexdigest()}]}
    (tmp_path/'.runtime/zeabur-stage-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    (tmp_path/'.runtime/zeabur-stage-review-smoke.json').write_text('{"ok":true}',encoding='utf-8')
    calls=[]
    def fake_run(command,**kwargs):
        calls.append((command,kwargs['cwd']))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(cloud.subprocess,'run',fake_run)
    cloud.deploy([{'_id':'synthetic-staging','name':cloud.APP}])
    assert len(calls)==1 and calls[0][1]==stage
    assert (stage/'backend/private.json').is_file()
