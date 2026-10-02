"""Read back the one created Input Base and produce private deployment mapping."""
import argparse,ast,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'.runtime/lark-input-cli'
CLI=Path(os.environ['APPDATA'])/'npm/node_modules/@larksuite/cli/bin/lark-cli.exe'
env=dict(os.environ,LARKSUITE_CLI_CONFIG_DIR=str(PRIVATE))
parser=argparse.ArgumentParser();parser.add_argument('--isolated-test',action='store_true');options=parser.parse_args()
prefix='test' if options.isolated_test else 'formal'
receipt=json.loads(json.loads((PRIVATE/f'{prefix}-create-receipt.json').read_text(encoding='utf-8'))['stdout'])['data']
base=receipt['base']['base_token'];table=receipt['table']['id']
for name,args in [('tables',['base','+table-list','--base-token',base]),
                  ('fields',['base','+field-list','--base-token',base,'--table-id',table])]:
    result=subprocess.run([str(CLI),'--profile','workbench-input',*args,'--as','bot','--json'],env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=60)
    if result.returncode:raise SystemExit(f'Readback failed: {name}; no writes attempted')
    body=json.loads(result.stdout)
    if not body.get('ok'):raise SystemExit(f'Readback not successful: {name}')
    (PRIVATE/f'{prefix}-{name}-readback.json').write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'operation':name,'data':body.get('data')},ensure_ascii=False))

tables=json.loads((PRIVATE/f'{prefix}-tables-readback.json').read_text(encoding='utf-8'))['data']['tables']
fields=json.loads((PRIVATE/f'{prefix}-fields-readback.json').read_text(encoding='utf-8'))['data']['fields']
assert len(tables)==1 and tables[0]['id']==table and tables[0]['records_count']==0
tree=ast.parse((ROOT/'backend/input_registration.py').read_text(encoding='utf-8'))
names=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='FIELD_NAMES' for t in n.targets))
assert len(fields)==9 and {f['name'] for f in fields}==set(names.values())
assert all(f['type']=='text' and f['id'].startswith('fld') for f in fields)
assert len({f['id'] for f in fields})==9
mapping={key:{'field_id':next(f['id'] for f in fields if f['name']==name),'field_name':name} for key,name in names.items()}
prepared={'environment_variables':{'LARK_INPUT_BASE_TOKEN':base,'LARK_INPUT_TABLE_ID':table,
    'LARK_INPUT_REGISTRATION_FIELDS_JSON':json.dumps(mapping,ensure_ascii=False,separators=(',',':'))},
    'workspace_settings':{'input_base':base,'input_table':table},'mapping':mapping,
    'permission_grant':receipt.get('permission_grant'),'status':'schema_readback_verified_no_records',
    'runtime_submission_tested':False}
if options.isolated_test:
    formal=json.loads((PRIVATE/'formal-input-config.json').read_text(encoding='utf-8'))
    assert base!=formal['environment_variables']['LARK_INPUT_BASE_TOKEN'] and table!=formal['environment_variables']['LARK_INPUT_TABLE_ID']
    assert not {v['field_id'] for v in mapping.values()} & {v['field_id'] for v in formal['mapping'].values()}
    prepared['environment_variables']={'LARK_TEST_BASE_TOKEN':base,'LARK_TEST_INPUT_TABLE_ID':table,
        'LARK_TEST_INPUT_REGISTRATION_FIELDS_JSON':json.dumps(mapping,ensure_ascii=False,separators=(',',':'))}
    prepared['workspace_settings']={'test_base':base,'test_input_table':table}
(PRIVATE/f'{prefix}-input-config.json').write_text(json.dumps(prepared,ensure_ascii=False,indent=2),encoding='utf-8')
checkpoint=PRIVATE/f'{prefix}-create-checkpoint.json';state=json.loads(checkpoint.read_text(encoding='utf-8'))
state.update(status='schema_readback_verified',base_token=base,table_id=table,field_count=9,record_count=0)
checkpoint.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'verified':True,'fields':9,'records':0,'mapping_file':str(PRIVATE/f'{prefix}-input-config.json')}))
