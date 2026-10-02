"""Deploy exactly the reviewed ced7de7d workbench package, at most once."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from workbench_login_cutover import environment

ROOT=Path(__file__).resolve().parents[1]
STAGE='zeabur-stage-ced7de7d'
SERVICE='6ab61834a4c05a5bcb57ad69'
ENV='6ab6168036d2a6cac409f0c6'
PROJECT='6ab61680a4c05a5bcb57ace9'
STATE=ROOT/'.runtime/formal-release-ced7de7d'

def read(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8-sig'))

def run():
    STATE.mkdir(parents=True,exist_ok=True)
    if (STATE/'attempt.json').exists():
        raise RuntimeError('Deployment already dispatched; inspect remote status instead of resending')
    manifest=read('.runtime/'+STAGE+'-manifest.json')
    stage=(ROOT/'.runtime'/STAGE).resolve()
    if Path(manifest['directory']).resolve()!=stage:raise RuntimeError('Stage path mismatch')
    for entry in manifest['files']:
        path=(stage/entry['path']).resolve()
        if not path.is_relative_to(stage) or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
            raise RuntimeError('Frozen package mismatch')
    if not read('.runtime/'+STAGE+'-smoke.json').get('ok'):raise RuntimeError('Package smoke unavailable')
    proof=read('.runtime/release-source-staging-ced7de7d.json')
    if not proof.get('ok') or not proof.get('runtime_uid_10001_verified') or proof.get('stage')!=STAGE:
        raise RuntimeError('Staging source or UID verification missing')
    if (datetime.now(timezone.utc)-datetime.fromisoformat(proof['observed_at'])).total_seconds()>3600:
        raise RuntimeError('Staging verification stale')
    public=read('.runtime/cloud-staging/verification.json')
    if not public.get('checks') or not all(public['checks'].values()):raise RuntimeError('Public staging checks failed')
    snapshot=read('.runtime/workbench-company-cockpit-snapshot/receipt.json')
    archive=ROOT/'.runtime/workbench-company-cockpit-snapshot/snapshot.zip'
    expected='97f5adf2256091762083aa7b70971c4b62cb73a3a0bc73e7bf75d67b76bd9367'
    if snapshot.get('sha256')!=expected:raise RuntimeError('Recovery receipt mismatch')
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise RuntimeError('Recovery snapshot mismatch')
    current=environment(SERVICE)
    if (current.get('PUBLIC_ORIGIN')!='https://yongxiang-projects-20260925.zeabur.app'
        or current.get('LARK_APP_ID')!='cli_aa3cab98b2789e17'
        or any(current.get(k)!='false' for k in ('DEMO_MODE','ALLOW_CLOUD_DEMO'))
        or current.get('LARK_NATIVE_APPROVAL_SUBMIT_ENABLED','false')!='false'
        or current.get('FEATURE_LEARNING','false')!='false'):
        raise RuntimeError('Formal identity or disabled gates changed')
    marker={'stage':STAGE,'service_id':SERVICE,'snapshot_sha256':expected,
            'attempted_at':datetime.now(timezone.utc).isoformat()}
    with (STATE/'attempt.json').open('x',encoding='utf-8') as out:
        json.dump(marker,out);out.flush();os.fsync(out.fileno())
    result=subprocess.run(['zeabur.cmd','deploy','--project-id',PROJECT,'--environment-id',ENV,
        '--service-id',SERVICE,'--interactive=false'],cwd=stage,capture_output=True,
        text=True,encoding='utf-8',errors='replace',timeout=240)
    receipt={**marker,'cli_exit_code':result.returncode,'accepted':result.returncode==0,
             'live_verified':False,'environment_modified':False,'database_restored':False}
    (STATE/'dispatch.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    if result.returncode:raise RuntimeError('Dispatch unverified; inspect existing deployment')
    return receipt

if __name__=='__main__':
    try:print(json.dumps(run()))
    except Exception as exc:print(json.dumps({'ok':False,'error_type':type(exc).__name__}));sys.exit(1)
