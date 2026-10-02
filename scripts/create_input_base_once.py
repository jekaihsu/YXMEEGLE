"""Authorized one-shot CLI creation. A durable checkpoint prevents blind retry."""
import argparse,json,os,subprocess
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'.runtime/lark-input-cli'
CLI=Path(os.environ['APPDATA'])/'npm/node_modules/@larksuite/cli/bin/lark-cli.exe'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--isolated-test',action='store_true');options=parser.parse_args()
    prefix='test' if options.isolated_test else 'formal'
    if options.isolated_test:
        formal=json.loads((PRIVATE/'formal-create-checkpoint.json').read_text(encoding='utf-8'))
        if formal.get('status')!='schema_readback_verified':raise SystemExit('Formal destination must be verified first')
    checkpoint=PRIVATE/f'{prefix}-create-checkpoint.json'
    if checkpoint.exists():raise SystemExit('Create already attempted; inspect receipt and reconcile before any new action')
    c=json.loads((PRIVATE/'config.json').read_text(encoding='utf-8'))
    if len(c['apps'])!=1 or c['apps'][0]['appId']!='cli_aa3cab98b2789e17':raise SystemExit('Wrong app')
    env=dict(os.environ,LARKSUITE_CLI_CONFIG_DIR=str(PRIVATE))
    spec=json.loads((ROOT/'docs/INPUT_BASE_CREATE_COMMAND_20260929.json').read_text(encoding='utf-8'))
    if options.isolated_test:spec['name']='詠翔專案工作台作業資料登錄（隔離測試）'
    args=[str(CLI),'--profile','workbench-input','base','+base-create','--as','bot','--name',spec['name'],
          '--table-name',spec['table_name'],'--time-zone','Asia/Taipei','--fields',json.dumps(spec['fields'],ensure_ascii=False),'--json']
    state={'status':'outcome_unknown','created_at':datetime.now(timezone.utc).isoformat(),'app_id':c['apps'][0]['appId'],
           'name':spec['name'],'command':'original CLI base +base-create','retry_forbidden':True}
    with checkpoint.open('x',encoding='utf-8') as f:json.dump(state,f,ensure_ascii=False,indent=2)
    try:
        result=subprocess.run(args,env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=180)
    except subprocess.TimeoutExpired:
        print(json.dumps({'status':'outcome_unknown','retry_forbidden':True}));return
    receipt={'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    secret=c['apps'][0]['appSecret']
    encoded=json.dumps(receipt,ensure_ascii=False).replace(secret,'[REDACTED]')
    (PRIVATE/f'{prefix}-create-receipt.json').write_text(encoded,encoding='utf-8')
    try:body=json.loads(result.stdout or result.stderr)
    except ValueError:body={}
    state['exit_code']=result.returncode
    if result.returncode==0 and body.get('ok'):state['status']='created_pending_readback'
    elif (body.get('error') or {}).get('subtype')=='app_scope_not_applied':
        state['status']='authorization_blocked_requires_receipt_review'
    checkpoint.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':state['status'],'exit_code':result.returncode,'error':body.get('error'),
        'data_keys':list((body.get('data') or {}).keys()),'receipt':str(PRIVATE/f'{prefix}-create-receipt.json')},ensure_ascii=False))


if __name__=='__main__':main()
