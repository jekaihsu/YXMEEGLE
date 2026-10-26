import json
import subprocess
from datetime import datetime
from fastapi.testclient import TestClient
from .app import create_app
from scripts import deploy_prepare


def test_stage_identity_tracks_commit_branch_dirty_and_utc(tmp_path):
    subprocess.run(['git','init','-b','qa-build',str(tmp_path)],check=True,capture_output=True)
    source=tmp_path/'source.txt';source.write_text('first')
    subprocess.run(['git','add','.'],cwd=tmp_path,check=True)
    subprocess.run(['git','-c','user.name=QA','-c','user.email=qa@example.test','commit','-m','fixture'],cwd=tmp_path,check=True,capture_output=True)
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=tmp_path,text=True).strip()
    manifest=deploy_prepare.build_identity(tmp_path)
    assert manifest['git_sha']==sha and manifest['branch']=='qa-build'
    assert manifest['dirty'] is False
    assert datetime.fromisoformat(manifest['built_at']).utcoffset().total_seconds()==0
    source.write_text('changed')
    assert deploy_prepare.build_identity(tmp_path)['dirty'] is True


def test_health_has_null_build_without_manifest_and_safe_fields_with_manifest(tmp_path,monkeypatch):
    from . import build_identity
    path=tmp_path/'build-manifest.json'
    monkeypatch.setattr(build_identity,'MANIFEST_PATH',path)
    app=create_app({'DATABASE_URL':f'sqlite:///{tmp_path}/build.db','UPLOAD_DIR':str(tmp_path/'uploads'),'DEMO_MODE':'true','APP_ENV':'development'})
    client=TestClient(app)
    assert client.get('/api/health').json()['build'] is None
    value={'git_sha':'a'*40,'dirty':False,'built_at':'2026-10-26T00:00:00+00:00','branch':'qa-build'}
    path.write_text(json.dumps(dict(value,secret='NEVER_RETURN')))
    assert client.get('/api/health').json()['build']==value
    path.write_text('{bad json')
    assert client.get('/api/health').json()['build'] is None
