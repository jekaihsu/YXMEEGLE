"""Prepare scoped Zeabur requests and a source-only deployment directory.

This script never reads account credentials or performs network operations.
Secrets stay in ignored .runtime request files, never in deployment staging.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import secrets
import shutil

try:
    from .stage_inventory import inventory_digest
except ImportError:
    from stage_inventory import inventory_digest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
PROJECT = '6ab61680a4c05a5bcb57ace9'
ENVIRONMENT = '6ab6168036d2a6cac409f0c6'
DOMAIN = 'yongxiang-projects-20260925.zeabur.app'


def write(name, value):
    target = RUNTIME / name
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


def prepare_services():
    secret_file = RUNTIME / 'zeabur-deploy-secrets.json'
    if secret_file.exists():
        values = json.loads(secret_file.read_text(encoding='utf-8'))
    else:
        values = {'postgres_password': secrets.token_urlsafe(36), 'session_secret': secrets.token_urlsafe(48)}
        write(secret_file.name, values)
    schema = {
        'name': 'yx-workspace-postgres',
        'source': {'image': 'postgres:17-alpine'},
        'ports': [{'id': 'postgres', 'port': 5432, 'type': 'TCP'}],
        'volumes': [{'id': 'data', 'dir': '/var/lib/postgresql/data'}],
        'portForwarding': {'enabled': False},
        'env': [{'key': key, 'default': value} for key, value in {
            'POSTGRES_USER': 'workspace', 'POSTGRES_PASSWORD': values['postgres_password'], 'POSTGRES_DB': 'workspace'
        }.items()],
    }
    write('zeabur-create-services-request.json', {
        'query': 'mutation($project:ObjectID!,$schema:ServiceSpecSchemaInput!){ postgres:createPrebuiltService(projectID:$project,schema:$schema){_id name} app:createService(projectID:$project,name:"yx-project-workspace",template:GIT){_id name}}',
        'variables': {'project': PROJECT, 'schema': schema},
    })
    print('Prepared scoped service creation request; secret values not printed.')


def prepare_settings():
    result = json.loads((RUNTIME / 'zeabur-create-services-response.json').read_text(encoding='utf-8'))
    if result.get('errors'): raise SystemExit('Creation response contains errors; inspect safely before continuing')
    pg, app = result['data']['postgres']['_id'], result['data']['app']['_id']
    values = json.loads((RUNTIME / 'zeabur-deploy-secrets.json').read_text(encoding='utf-8'))
    # Use Zeabur's private service DNS; no public database endpoint is created.
    private_dns = json.loads((RUNTIME / 'zeabur-service-details.json').read_text(encoding='utf-8'))['data']['service']['dnsName'] + '.zeabur.internal'
    database = f"postgresql://workspace:{values['postgres_password']}@{private_dns}:5432/workspace"
    env = {
        'APP_ENV': 'production', 'DEMO_MODE': 'false', 'ALLOW_CLOUD_DEMO': 'false',
        'DATABASE_URL': database, 'SESSION_SECRET': values['session_secret'],
        'UPLOAD_DIR': '/data/uploads', 'PORT': '8080', 'PUBLIC_ORIGIN': 'https://' + DOMAIN,
        'LARK_SOURCE_TABLES_JSON': (ROOT / 'deployment/source-tables.json').read_text(encoding='utf-8'),
        'LARK_ROLE_MAP_JSON': '{}',
    }
    write('zeabur-settings-request.json', {
        'query': 'mutation($service:ObjectID!,$environment:ObjectID!,$data:Map!,$domain:String!){ variables:updateEnvironmentVariable(serviceID:$service,environmentID:$environment,data:$data) volume:mountVolume(serviceID:$service,id:"uploads",dir:"/data/uploads") domain:addDomain(serviceID:$service,environmentID:$environment,domain:$domain,isGenerated:true){__typename}}',
        'variables': {'service': app, 'environment': ENVIRONMENT, 'data': env, 'domain': DOMAIN.removesuffix('.zeabur.app')},
    })
    write('zeabur-deployment-ids.json', {'project_id': PROJECT, 'environment_id': ENVIRONMENT, 'postgres_service_id': pg, 'app_service_id': app, 'domain': DOMAIN, 'upload_mount': '/data/uploads', 'database_image': 'postgres:17-alpine'})
    print(json.dumps({'project_id': PROJECT, 'environment_id': ENVIRONMENT, 'postgres_service_id': pg, 'app_service_id': app, 'domain': DOMAIN}))


def prepare_lark():
    incoming = json.loads((RUNTIME / 'lark-new.json').read_text(encoding='utf-8'))
    expected = ('LARK_APP_ID', 'LARK_APP_SECRET', 'LARK_ALLOWED_TENANTS')
    if not all(incoming.get(key) for key in expected):
        raise SystemExit('New-app secret file must provide required uppercase Lark environment keys')
    if incoming['LARK_APP_ID'] != 'cli_aa3cab98b2789e17':
        raise SystemExit('Only the dedicated workbench Lark app is accepted')
    original = json.loads((RUNTIME / 'zeabur-settings-request.json').read_text(encoding='utf-8'))
    env = original['variables']['data'].copy()
    # Historical request files may have enabled anonymous preview mode.
    # Connecting the company app must never restore that old access path.
    env.update(APP_ENV='production',DEMO_MODE='false',ALLOW_CLOUD_DEMO='false')
    env.update({key: incoming[key] for key in expected})
    env['LARK_ROLE_MAP_JSON'] = incoming.get('LARK_ROLE_MAP_JSON', '{}')
    env['LARK_REDIRECT_URI'] = 'https://' + DOMAIN + '/api/auth/lark/callback'
    env['LARK_OAUTH_SCOPES'] = 'bitable:app:readonly approval:approval:readonly'
    env['LARK_SOURCE_TABLES_JSON'] = (ROOT / 'deployment/source-tables.json').read_text(encoding='utf-8')
    ids = json.loads((RUNTIME / 'zeabur-deployment-ids.json').read_text(encoding='utf-8'))
    write('zeabur-lark-settings-request.json', {
        'query': 'mutation($s:ObjectID!,$e:ObjectID!,$data:Map!){updateEnvironmentVariable(serviceID:$s,environmentID:$e,data:$data)}',
        'variables': {'s': ids['app_service_id'], 'e': ENVIRONMENT, 'data': env},
    })
    print(json.dumps({'prepared': True, 'dedicated_app_id': incoming['LARK_APP_ID'], 'callback': env['LARK_REDIRECT_URI'], 'source_tables': len(json.loads(env['LARK_SOURCE_TABLES_JSON'])), 'secret_values_printed': False}))


def validate_source_tables(path):
    """Only resource identifiers and field metadata belong in this source file."""
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    allowed={'name','base_token','table_id','kind','department','cost_table_id','field_names'}
    if not isinstance(value,list): raise SystemExit('Source table configuration must be a list')
    for table in value:
        if not isinstance(table,dict) or set(table)-allowed:
            raise SystemExit('Source table configuration contains unsupported keys; credentials are not staging inputs')
        for key in ('base_token','table_id'):
            if not isinstance(table.get(key),str) or not re.fullmatch(r'[A-Za-z0-9]+',table[key]):
                raise SystemExit('Invalid source resource identifier')
        if table.get('kind') not in ('quote','quote_confirmation','confirmation','contract','reporting','cost','daily'):
            raise SystemExit('Unexpected source kind')
        for key in ('name','department','cost_table_id'):
            if key in table and not isinstance(table[key],str): raise SystemExit('Invalid source metadata')
        if 'field_names' in table and (not isinstance(table['field_names'],list) or not all(isinstance(x,str) for x in table['field_names'])):
            raise SystemExit('Invalid field metadata')
    return value


def staging():
    validate_source_tables(ROOT/'deployment/source-tables.json')
    folder = RUNTIME / ('zeabur-stage-' + secrets.token_hex(4))
    folder.mkdir(parents=True)
    exact = ['Dockerfile', '.dockerignore', 'backend/requirements.txt', 'scripts/backup_restore.py', 'scripts/backup_live_legacy.py', 'scripts/restore_drill.py',
             'scripts/run_service.py', 'scripts/run_worker.py', 'scripts/backup_schedule.py', 'scripts/backup_offsite.py', 'deployment/source-tables.json',
             'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html',
             'frontend/tsconfig.json', 'frontend/vite.config.ts']
    exact.append('backend/sop_source_contracts.json')
    exact += ['scripts/backup_publish.py','scripts/backup_reconcile.py',
              'scripts/backup_offsite_acceptance.py','backend/requirements.lock']
    files = [ROOT / x for x in exact]
    files += [p for p in (ROOT/'backend').glob('*.py') if not p.name.startswith('test_')]
    for part in ('frontend/src', 'frontend/public'):
        source = ROOT / part
        if source.exists(): files += [p for p in source.rglob('*') if p.is_file()]
    manifest = []
    for source in sorted(set(files)):
        if not source.is_file(): raise SystemExit('Missing expected deployment source: ' + str(source.relative_to(ROOT)))
        if source.is_symlink(): raise SystemExit('Deployment symlinks not permitted')
        if not source.resolve().is_relative_to(ROOT.resolve()): raise SystemExit('Deployment source escapes workspace')
        relative = source.relative_to(ROOT)
        if any(part in ('.runtime', 'node_modules', 'uploads', '__pycache__', '.git') for part in relative.parts):
            raise SystemExit('Forbidden staging path')
        if source.suffix.lower() in ('.db', '.sqlite', '.zip') or source.name.startswith('.env'):
            raise SystemExit('Forbidden staging file')
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        manifest.append({'path': relative.as_posix(), 'size': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    manifest_value = {'directory': str(folder), 'files': manifest}
    write('zeabur-stage-manifest.json', manifest_value)
    write(folder.name + '-manifest.json', manifest_value)
    try:
        from .verify_stage_package import verify_stage
    except ImportError:
        from verify_stage_package import verify_stage
    smoke = verify_stage(folder)
    write(folder.name + '-smoke.json', dict(smoke, stage=str(folder), inventory_sha256=inventory_digest(manifest)))
    if not smoke.get('ok'):
        raise SystemExit('Deployment package verification failed: ' + smoke.get('reason', 'unknown'))
    print(json.dumps({'staging_directory': str(folder), 'files': len(manifest), 'bytes': sum(f['size'] for f in manifest), 'runtime_smoke_passed': True}))
    return folder


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('step', choices=['services', 'settings', 'staging', 'lark'])
    args = parser.parse_args()
    RUNTIME.mkdir(exist_ok=True)
    {'services': prepare_services, 'settings': prepare_settings, 'staging': staging, 'lark': prepare_lark}[args.step]()
