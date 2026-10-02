"""Fixed backup app/folder operator. No arbitrary targets or secret output."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
STATE=ROOT/'.runtime/workbench-backup-setup'
APP='cli_aa361fea3678de13'
OWNER='cli_aa3cab98b2789e17'
FOLDER='S6lqfyItLlr42OdCidWjgkLEpic'

def save(name,value,exclusive=False):
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/name).open('x' if exclusive else 'w',encoding='utf-8') as handle:
        json.dump(value,handle,ensure_ascii=False,indent=2);handle.flush();os.fsync(handle.fileno())

def profile(backup):
    if not backup:
        path=ROOT/'.runtime/lark-input-cli'
        data=json.loads((path/'config.json').read_text(encoding='utf-8-sig'))
        matches=[a for a in data['apps'] if a.get('name')=='workbench-input']
        if len(matches)!=1 or matches[0].get('appId')!=OWNER:raise ValueError('Owner profile mismatch')
        return path,'workbench-input'
    cfg=json.loads((ROOT/'.runtime/backup-independent-app-private.json').read_text(encoding='utf-8-sig'))
    if cfg.get('BACKUP_LARK_APP_ID')!=APP or not cfg.get('BACKUP_LARK_APP_SECRET'):raise ValueError('Backup identity mismatch')
    path=STATE/'cli';path.mkdir(parents=True,exist_ok=True)
    desired={'currentApp':'workbench-backup','apps':[{'name':'workbench-backup','appId':APP,
        'appSecret':cfg['BACKUP_LARK_APP_SECRET'],'brand':'lark','defaultAs':'bot','users':[]}]}
    target=path/'config.json'
    if target.exists():
        if json.loads(target.read_text(encoding='utf-8'))!=desired:raise ValueError('Existing backup profile mismatch')
    else:
        with target.open('x',encoding='utf-8') as out:json.dump(desired,out)
    return path,'workbench-backup'

def call(args,backup=False):
    path,name=profile(backup)
    env=dict(os.environ,LARKSUITE_CLI_CONFIG_DIR=str(path),LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1',LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')
    env.pop('LARKSUITE_CLI_PROFILE',None)
    binary=Path(os.environ['APPDATA'])/'npm/node_modules/@larksuite/cli/bin/lark-cli.exe'
    process=subprocess.run([str(binary),'--profile',name,*args,'--as','bot','--json'],env=env,capture_output=True,text=True,encoding='utf-8',timeout=90)
    if process.returncode:
        try:
            failed=json.loads(process.stdout or process.stderr)
            err=failed.get('error',{})
            save('last-error.json',{'command':args[:3],'exit_code':process.returncode,
                 'code':err.get('code'),'subtype':err.get('subtype'),'type':err.get('type')})
        except (ValueError,AttributeError):
            import re
            message=(process.stdout+'\n'+process.stderr)[:3000]
            for profile_path in (ROOT/'.runtime/lark-input-cli/config.json', STATE/'cli/config.json'):
                for app in json.loads(profile_path.read_text(encoding='utf-8')).get('apps',[]):
                    if app.get('appSecret'):message=message.replace(app['appSecret'],'[REDACTED]')
            message=re.sub(r'(?i)(Bearer\s+|(?:access_token|refresh_token|token|secret)[\s"=:]+)[A-Za-z0-9_.-]+',r'\1[REDACTED]',message)
            save('last-error.json',{'command':args[:3],'exit_code':process.returncode,'json_error':True,'diagnostic':message})
        raise RuntimeError('CLI request failed; outcome requires readback')
    reply=json.loads(process.stdout)
    # Only structural keys/types; never persist raw auth/error payloads.
    def shape(value,depth=0):
        if depth>4:return type(value).__name__
        if isinstance(value,dict):return {k:shape(v,depth+1) for k,v in value.items()}
        if isinstance(value,list):return [shape(value[0],depth+1)] if value else []
        return type(value).__name__
    save('last-response-shape.json',{'command':args[:3],'shape':shape(reply)})
    if reply.get('ok') is not True:raise RuntimeError('API request not confirmed')
    return reply.get('data',{})

def backup_bot_identity():
    # bot/v3/info returns top-level bot; the generic CLI data wrapper drops it.
    from scripts.backup_offsite import backup_adapter
    from backend.lark_adapter import API
    cfg=json.loads((ROOT/'.runtime/backup-independent-app-private.json').read_text(encoding='utf-8-sig'))
    if cfg.get('BACKUP_LARK_APP_ID')!=APP:raise ValueError('Backup identity mismatch')
    adapter=backup_adapter(cfg)
    try:
        response=adapter.client.get(API+'/bot/v3/info',headers={'Authorization':'Bearer '+adapter.token})
        body=response.json()
        if response.status_code!=200 or not isinstance(body,dict) or body.get('code')!=0:
            raise ValueError('Backup bot lookup unverified')
        bot=body.get('bot')
        identity=bot.get('open_id') if isinstance(bot,dict) else None
    finally:adapter.client.close()
    if not isinstance(identity,str) or not identity.startswith('ou_'):raise ValueError('Backup bot identity malformed')
    save('bot-identity.json',{'app_id':APP,'bot_open_id':identity})
    return identity

def facts():
    identity=backup_bot_identity()
    proof=json.loads((STATE/'ui-acl.json').read_text(encoding='utf-8'))
    observed=datetime.fromisoformat(proof.get('observed_at','').replace('Z','+00:00'))
    age=(datetime.now(timezone.utc)-observed).total_seconds() if observed.tzinfo else -1
    if proof.get('folder')!=FOLDER or proof.get('list_complete') is not True or not 0<=age<=3600:
        raise ValueError('Fresh complete UI ACL evidence required')
    public=call(['drive','+permission-get-setting','--token',FOLDER,'--type','folder'])
    rows=proof.get('members')
    setting=public.get('permission_public')
    if not isinstance(rows,list) or not rows or not isinstance(setting,dict):raise ValueError('Incomplete folder evidence')
    if any(not isinstance(m,dict) or m.get('member_type')!='openid' or not isinstance(m.get('member_id'),str)
           or not m['member_id'].startswith('ou_') or m.get('perm') not in ('view','edit','full_access','owner') for m in rows):
        raise ValueError('Exact UI member identities and roles required')
    if len({m['member_id'] for m in rows})!=len(rows):raise ValueError('Duplicate UI member identities')
    if setting.get('external_access_entity')!='closed' or setting.get('link_share_entity')!='closed':raise ValueError('Folder privacy changed')
    return {'app_id':APP,'folder':FOLDER,'bot_open_id':identity,'members':rows,'public':setting}

def granted(fact):
    return any(m.get('member_type')=='openid' and m.get('member_id')==fact['bot_open_id'] and m.get('perm')=='full_access' for m in fact['members'])

def run(command):
    current=facts()
    if command=='inspect':
        save('inspection.json',current)
        return {'ok':True,'app_id':APP,'folder':FOLDER,'backup_member_present':granted(current),'privacy_closed':True}
    if command=='grant':
        prior=json.loads((STATE/'inspection.json').read_text(encoding='utf-8'))
        if not granted(current):
            if current!=prior:raise ValueError('Folder changed since inspection')
            # Exclusive/fsynced marker precedes mutation. Unknown outcomes never retry.
            save('grant-attempt.json',{'target':FOLDER,'app_id':APP,'bot_open_id':current['bot_open_id'],'before':current,
                'at':datetime.now(timezone.utc).isoformat()},True)
            payload={'member_type':'openid','member_id':current['bot_open_id'],'perm':'full_access','type':'user'}
            save('grant-body.json',payload)
            call(['drive','permission.members','create','--token',FOLDER,'--type','folder','--data','@'+str(STATE/'grant-body.json'),'--yes'])
            save('grant-response.json',{'status':'pending_ui_readback','app_id':APP,'folder':FOLDER,
                'at':datetime.now(timezone.utc).isoformat()})
            return {'ok':True,'status':'pending_ui_readback','app_id':APP,'folder':FOLDER,'acl_verified':False}
        after=facts()
        if not granted(after) or after['public']!=current['public']:raise ValueError('Grant readback differs')
        original={(m.get('member_type'),m.get('member_id'),m.get('perm')) for m in current['members']}
        actual={(m.get('member_type'),m.get('member_id'),m.get('perm')) for m in after['members']}
        if not original.issubset(actual):raise ValueError('Existing folder members changed')
        save('grant-readback.json',after)
    elif command!='verify':raise ValueError('Unknown operation')
    if not granted(current):raise ValueError('Fresh UI evidence must include backup bot full_access')
    attempt=STATE/'grant-attempt.json'
    if attempt.exists():
        attempted=json.loads(attempt.read_text(encoding='utf-8'));before=attempted['before']
        expected={(m['member_type'],m['member_id'],m['perm']) for m in before['members']}
        actual={(m['member_type'],m['member_id'],m['perm']) for m in current['members']}
        if not expected.issubset(actual) or current['public']!=before['public']:raise ValueError('Original ACL or privacy changed')
        response=STATE/'grant-response.json'
        issued=json.loads(response.read_text(encoding='utf-8'))['at'] if response.exists() else attempted.get('at')
        if issued:
            proof=json.loads((STATE/'ui-acl.json').read_text(encoding='utf-8'))
            if datetime.fromisoformat(proof['observed_at'].replace('Z','+00:00'))<=datetime.fromisoformat(issued):
                raise ValueError('Post-grant UI observation required')
    listing=call(['drive','files','list','--folder-token',FOLDER,'--page-size','1'],True)
    if not isinstance(listing.get('files'),list):raise ValueError('Backup listing not verified')
    save('listing-receipt.json',{'ok':True,'app_id':APP,'folder':FOLDER,'returned_count':len(listing['files'])})
    return {'ok':True,'app_id':APP,'folder':FOLDER,'backup_listing_verified':True,'backup_member_present':granted(facts())}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['inspect','grant','verify'])
    args=parser.parse_args()
    try:print(json.dumps(run(args.command)))
    except Exception as exc:
        print(json.dumps({'ok':False,'error_type':type(exc).__name__}));sys.exit(1)

if __name__=='__main__':main()
