"""Read-only fixed-folder verification with fresh complete browser ACL evidence."""
import json
from datetime import datetime, timezone
from pathlib import Path
from workbench_backup_setup import call, APP, FOLDER, STATE, save

ROOT=Path(__file__).resolve().parents[1]

def main():
    raw=(ROOT/'.runtime/workbench-lark-backup-folder-all-members.txt').read_text(encoding='utf-8')
    ui=json.JSONDecoder().raw_decode(raw.split('### Result',1)[1].lstrip())[0]
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(ui['observed_at'].replace('Z','+00:00'))).total_seconds()
    expected={'詠翔專案工作台\n擁有者\n暫無部門資訊\n可管理','詠翔工作台備份\n應用程式\n可管理','jekai\n科技\n可管理'}
    if not 0<=age<=3600 or ui['folder_token']!=FOLDER or len(ui['members'])!=3 or set(ui['members'])!=expected:
        raise ValueError('Current explicit ACL evidence required')
    if len(ui['lists'])!=1 or any(r['scrollHeight']>r['clientHeight'] or r['scrollTop']!=0 for r in ui['lists']):
        raise ValueError('Full member list not proven')
    public=call(['drive','+permission-get-setting','--token',FOLDER,'--type','folder'])['permission_public']
    baseline=json.loads((ROOT/'.runtime/lark-input-cli/backup-drive-settings-fresh.json').read_text(encoding='utf-8'))['data']['permission_public']
    if public!=baseline or public.get('external_access_entity')!='closed' or public.get('link_share_entity')!='closed':
        raise ValueError('Folder public security changed')
    listing=call(['drive','files','list','--folder-token',FOLDER,'--page-size','1'],True)
    if not isinstance(listing.get('files'),list):raise ValueError('Independent backup listing not proven')
    receipt={'ok':True,'app_id':APP,'folder':FOLDER,'observed_at':datetime.now(timezone.utc).isoformat(),
             'acl_source':'fresh_complete_authenticated_folder_ui','members':ui['members'],
             'public_unchanged':True,'public':public,'independent_app_listing_verified':True,
             'upload_verified':False,'download_verified':False,'schedule_enabled':False}
    save('folder-verified.json',receipt)
    print(json.dumps({k:v for k,v in receipt.items() if k not in {'members','public'}},ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'ok':False,'error_type':type(exc).__name__}));raise SystemExit(1)
