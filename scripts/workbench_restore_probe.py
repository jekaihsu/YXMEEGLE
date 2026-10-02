"""Fixed-target read-only restore transport probes. Never receives credentials."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
import zlib

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.runtime/cloud-restore'
STAGING='6abc0821454b8f31a5ef614a'
RESTORE='6abce665454b8f31a5efc37e'
ENV='6ab6168036d2a6cac409f0c6'
MARKER='YX_RESTORE_PROBE='
NONCE='YX_NONSECRET_STDIN_PROBE_20260930'

REMOTE_READINESS=r'''
import importlib.util,json,shutil,hashlib
from pathlib import Path
files={}
for name in ('scripts/backup_offsite_acceptance.py','scripts/restore_drill.py','scripts/backup_restore.py','scripts/backup_offsite.py'):
 p=Path('/app',name)
 files[name]={'exists':p.is_file(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None}
try:
 import psycopg
 psycopg_ok=True
except Exception:
 psycopg_ok=False
result={'files':files,'psycopg_importable':psycopg_ok,'tmp_free_bytes':shutil.disk_usage('/tmp').free}
print('YX_RESTORE_PROBE='+json.dumps(result))
'''
REMOTE_STDIN=r'''
import json,select,sys
ready,_,_=select.select([sys.stdin],[],[],12)
received=sys.stdin.readline(100) if ready else ''
print('YX_RESTORE_PROBE='+json.dumps({'stdin_received':received=='YX_NONSECRET_STDIN_PROBE_20260930\n','stdin_isatty':sys.stdin.isatty()}))
'''


def launcher(source):
    encoded=base64.b64encode(zlib.compress(source.encode())).decode()
    return 'import base64,zlib;exec(zlib.decompress(base64.b64decode('+repr(encoded)+')))'


def command(service,args,interactive=False):
    if service not in (STAGING,RESTORE):raise ValueError('Target outside fixed probe allowlist')
    return ['zeabur.cmd','service','exec','--id',service,'--env-id',ENV,
            '-i=true' if interactive else '-i=false','--',*args]


def run_probe(step):
    if step not in ('readiness','stdin','stdin-interactive','postgres'):raise ValueError('Unknown probe')
    if step=='postgres':
        # pg_isready is a readiness check, not an authenticated query or restore.
        script='pg_isready -h 127.0.0.1 -p 5432 -U restore_drill -d workbench_restore_drill -t 5 >/dev/null 2>&1; rc=$?; if [ "$rc" -eq 0 ]; then printf \'YX_RESTORE_PROBE={"postgres_accepting_connections":true}\\n\'; else printf \'YX_RESTORE_PROBE={"postgres_accepting_connections":false}\\n\'; fi'
        cmd=command(RESTORE,['sh','-c',script]);payload=None
    else:
        source=REMOTE_READINESS if step=='readiness' else REMOTE_STDIN
        cmd=command(STAGING,['python','-c',launcher(source)],interactive=step=='stdin-interactive')
        payload=None if step=='readiness' else NONCE+'\n'
    completed=subprocess.run(cmd,input=payload,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=75)
    lines=[line.split(MARKER,1)[1] for line in completed.stdout.splitlines() if line.startswith(MARKER)]
    if completed.returncode or len(lines)!=1:
        # Never forward arbitrary CLI stdout/stderr or future remote errors.
        return {'ok':False,'step':step,'transport_verified':False,'error':'No unique successful probe receipt'}
    data=json.loads(lines[0])
    if step=='readiness':
        ok=bool(data.get('psycopg_importable') and all(v.get('exists') for v in data.get('files',{}).values()) and data.get('tmp_free_bytes',0)>128*1024*1024)
    elif step=='postgres':ok=data.get('postgres_accepting_connections') is True
    else:ok=data.get('stdin_received') is True
    return {'ok':ok,'step':step,'transport_verified':True,**data,'database_empty_verified':False,'restore_performed':False}


def status():
    try:from .workbench_restore_setup import query
    except ImportError:from workbench_restore_setup import query
    data=query('query($s:ObjectID!,$e:ObjectID!){service(_id:$s){_id name status(environmentID:$e)}}',{'s':RESTORE,'e':ENV})['service']
    if data.get('_id')!=RESTORE or data.get('name')!='yongxiang-workbench-restore-drill':
        raise RuntimeError('Restore service identity mismatch')
    return {'ok':data.get('status')=='RUNNING','step':'status','service_id':RESTORE,'status':data.get('status'),'database_empty_verified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step',choices=['readiness','stdin','stdin-interactive','postgres','status'])
    step=parser.parse_args().step
    result=status() if step=='status' else run_probe(step)
    STATE.mkdir(parents=True,exist_ok=True)
    (STATE/('probe-'+step+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        print(json.dumps({'ok':False,'error':type(exc).__name__,'restore_performed':False}))
        sys.exit(1)
