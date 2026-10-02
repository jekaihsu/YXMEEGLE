"""Read-only probe of existing authorized source metadata with isolated app."""
import json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CLI=Path(os.environ['APPDATA'])/'npm/node_modules/@larksuite/cli/bin/lark-cli.exe'
env=dict(os.environ,LARKSUITE_CLI_CONFIG_DIR=str(ROOT/'.runtime/lark-input-cli'))
source=json.loads((ROOT/'deployment/source-tables.json').read_text(encoding='utf-8'))[0]
results=[]
for name,args in [('table-list',['base','+table-list','--base-token',source['base_token']]),
                  ('field-list',['base','+field-list','--base-token',source['base_token'],'--table-id',source['table_id']])]:
    p=subprocess.run([str(CLI),'--profile','workbench-input',*args,'--as','bot','--json'],env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60)
    raw=p.stdout.strip() or p.stderr.strip()
    try:
        data=json.loads(raw);error=data.get('error') or {}
        results.append({'operation':name,'ok':data.get('ok'),'exit':p.returncode,
            'error_type':error.get('type'),'error_subtype':error.get('subtype'),
            'missing_scopes':error.get('missing_scopes'), 'message':error.get('message')})
    except ValueError:results.append({'operation':name,'exit':p.returncode,'unparsed_output':True})
(ROOT/'.runtime/input-scope-read-probe.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
