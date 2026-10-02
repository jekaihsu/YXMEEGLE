"""Read-only application-identity probe. Never prints credentials or business rows."""
import argparse
import json
import re
from pathlib import Path
import httpx

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--saved-config',required=True); parser.add_argument('--output',default='.runtime/v06-connectivity.json'); args=parser.parse_args()
    raw=json.loads(Path(args.saved_config).read_text(encoding='utf-8-sig')); cfg=raw.get('variables',{}).get('data',raw)
    result={'identity':'application','writes':False,'auth':False,'tables':[]}
    api='https://open.larksuite.com/open-apis'
    with httpx.Client(timeout=25) as c:
        try:
            r=c.post(api+'/auth/v3/tenant_access_token/internal',json={'app_id':cfg['LARK_APP_ID'],'app_secret':cfg['LARK_APP_SECRET']}); response=r.json()
            result['auth_code']=response.get('code'); result['auth']=bool(response.get('tenant_access_token')) and r.status_code==200
            if result['auth']:
                headers={'Authorization':'Bearer '+response['tenant_access_token']}
                for table in json.loads(Path('deployment/source-tables.json').read_text(encoding='utf-8-sig')):
                    base=table['base_token']; tid=table['table_id']
                    r=c.get(f'{api}/bitable/v1/apps/{base}/tables/{tid}/fields',headers=headers,params={'page_size':100}); body=r.json()
                    message=body.get('msg','')
                    scopes=sorted(set(re.findall(r'\b(?:bitable|base):[a-zA-Z_:]+',message)))
                    result['tables'].append(dict(kind=table['kind'],table_id=tid,http_status=r.status_code,code=body.get('code'),required_scope_alternatives=scopes,field_count=len(body.get('data',{}).get('items',[])),has_more=body.get('data',{}).get('has_more',False)))
        except httpx.HTTPError as exc: result['network_error']=type(exc).__name__
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    if 'network_error' in result: raise SystemExit(2)
    if not result['auth'] or not result['tables'] or any(t['http_status']!=200 or t['code']!=0 for t in result['tables']): raise SystemExit(1)

if __name__=='__main__': main()
