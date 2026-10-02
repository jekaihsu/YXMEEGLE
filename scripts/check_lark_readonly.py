"""Verify existing app access without logging credentials or business records."""
import json
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]

def main():
    config=json.loads((ROOT/'.runtime/lark-existing.json').read_text(encoding='utf-8'))
    tables=json.loads((ROOT/'deployment/source-tables.json').read_text(encoding='utf-8'))
    output=[]
    with httpx.Client(timeout=30) as client:
        reply=client.post('https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal',json={
            'app_id':config['LARK_APP_ID'],'app_secret':config['LARK_APP_SECRET']}).json()
        if reply.get('code')!=0 or not reply.get('tenant_access_token'):
            print(json.dumps({'ok':False,'stage':'app_auth','code':reply.get('code')}));return
        headers={'Authorization':'Bearer '+reply['tenant_access_token']}
        for table in tables:
            url=f"https://open.larksuite.com/open-apis/bitable/v1/apps/{table['base_token']}/tables/{table['table_id']}/records"
            r=client.get(url,headers=headers,params={'page_size':1})
            body=r.json()
            output.append({'table':table['name'],'http':r.status_code,'code':body.get('code'),
                           'sample_rows':len(body.get('data',{}).get('items',[])),
                           'has_more':body.get('data',{}).get('has_more')})
    report={'ok':all(x['code']==0 for x in output),'tables':output,'writes':0}
    (ROOT/'.runtime/lark-connectivity.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
