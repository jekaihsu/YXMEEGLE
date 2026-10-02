"""Read-only Drive reconciliation; --apply-receipt only updates local evidence.

Never upload/delete files or clear an ambiguous attempted flag. A missing result
stays unknown; an exact unique name/root/hash match recovers a lost response.
"""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.backup_offsite import settings,listing,backup_adapter,atomic_json


def reconcile(receipt,cfg,adapter,apply=False):
    receipt=Path(receipt)
    if receipt.is_symlink() or receipt.parent.is_symlink():raise ValueError('Unsafe receipt path')
    state=json.loads(receipt.read_text(encoding='utf-8'))
    root,_=settings(cfg)
    if state.get('root')!=root:raise ValueError('Receipt destination mismatch')
    current=listing(adapter,root)
    results=[]
    for item in state['files']:
        matches=[f for f in current if f.get('parent_token')==root and f.get('name')==item['name'] and f.get('type')=='file']
        status='duplicate' if len(matches)>1 else 'unknown' if item.get('attempted') else 'not_attempted'
        if len(matches)==1:
            token=matches[0]['token']
            if item.get('token') and item['token']!=token:status='token_changed'
            else:
                adapter.verify_file(token,item['sha256'])
                status='verified'
                if apply:item.update(token=token,verified=True)
        results.append({'name':item['name'],'status':status})
    if apply:atomic_json(receipt,state)
    return {'remote_read_only':True,'local_receipt_updated':apply,'files':results,
            'can_resume_without_unknown':all(r['status'] in ('verified','not_attempted') for r in results)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt',required=True,type=Path)
    parser.add_argument('--apply-receipt',action='store_true')
    args=parser.parse_args()
    adapter=None
    try:
        settings(os.environ)
        adapter=backup_adapter(os.environ)
        print(json.dumps(reconcile(args.receipt,os.environ,adapter,args.apply_receipt)))
    except Exception as exc:
        print(json.dumps({'ok':False,'error_type':type(exc).__name__}))
        raise SystemExit(1)
    finally:
        if adapter is not None:adapter.client.close()
