"""Named pre-release recovery point; never overwrites the earlier restored backup.

Targets the same fixed formal service and reviewed snapshot implementation.
Only a new explicit pre-release attempt is prepared; unknown outcomes recover.
"""
import argparse,json,sys
from pathlib import Path
try:from . import workbench_snapshot as snapshot
except ImportError:import workbench_snapshot as snapshot
DIRECTORY=snapshot.ROOT/'.runtime/workbench-release-snapshot'
PURPOSE='formal-release-20260930'


def execute(operation):
    if operation=='prepare':
        DIRECTORY.mkdir(parents=True,exist_ok=True)
        if DIRECTORY.is_symlink():raise snapshot.SnapshotError('invalid_release_directory')
        attempt={'id':snapshot.secrets.token_hex(16),'purpose':PURPOSE,'source_service_id':snapshot.SERVICE,
            'source_environment_id':snapshot.ENVIRONMENT,'started_at':snapshot.stamp(),
            'module_hashes':{p:snapshot.hashlib.sha256((snapshot.ROOT/p).read_bytes()).hexdigest() for p in snapshot.MODULES}}
        snapshot.exclusive_json(DIRECTORY/'attempt.json',attempt)
        return {'ok':True,'prepared':True,'purpose':PURPOSE,'attempt_id':attempt['id'],'remote_created':False}
    if operation not in ('capture','recover','status','diagnose','repair-preflight','repair-reviewed-helper'):
        raise snapshot.SnapshotError('invalid_release_operation')
    attempt=json.loads((DIRECTORY/'attempt.json').read_text(encoding='utf-8'))
    snapshot.check(attempt.get('purpose')==PURPOSE,'release_purpose_mismatch')
    previous=snapshot.DIRECTORY
    try:
        snapshot.DIRECTORY=DIRECTORY
        if operation=='capture':
            if (DIRECTORY/'receipt.json').exists():
                result=snapshot.execute('status')
            else:
                snapshot.exclusive_json(DIRECTORY/'capture-dispatched.json',{'id':attempt['id'],'at':snapshot.stamp()})
                snapshot.validated_metadata(snapshot.run_remote('create',attempt),attempt)
                result=snapshot.execute('recover')
        else:
            result=snapshot.execute(operation)
    finally:snapshot.DIRECTORY=previous
    return {'purpose':PURPOSE,**result}


def main():
    global DIRECTORY,PURPOSE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['prepare','capture','diagnose','repair-preflight','repair-reviewed-helper','recover','status'])
    parser.add_argument('--release',choices=['original','company-cockpit'],default='original')
    args=parser.parse_args()
    if args.release=='company-cockpit':
        DIRECTORY=snapshot.ROOT/'.runtime/workbench-company-cockpit-snapshot'
        PURPOSE='company-cockpit-20260930'
    result=execute(args.operation)
    print(json.dumps(result))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc) if isinstance(exc,snapshot.SnapshotError) else type(exc).__name__}));sys.exit(1)
