"""Populate only the disposable local review database with labelled fixtures."""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
ROOT=Path(__file__).resolve().parents[1]
DATABASE=ROOT/'.runtime/review-20260927.db'
os.environ['DATABASE_URL']='sqlite:///'+DATABASE.as_posix()
os.environ['UPLOAD_DIR']=str(ROOT/'.runtime/review-uploads-20260927')
os.environ['APP_ENV']='development'
os.environ['DEMO_MODE']='true'
from sqlalchemy import select
from backend.app import app,WorkspaceRow,BusinessRow
from backend import storage
from backend.policy import upgrade

def main():
    count=0
    with app.state.sessions.begin() as db:
        rows=list(db.scalars(select(WorkspaceRow)))
        if any(not r.id.startswith('demo-') for r in rows):
            raise SystemExit('Review database contains non-demo workspace; refusing changes')
        for row in rows:
            ws=upgrade(storage.load(db,BusinessRow,row))
            if ws.get('review_fixture_version')==1: continue
            ws['environment']='demo'
            for u in ws['users']:
                if u['id']=='u-manager' and 'approve_capability' not in u['capabilities']: u['capabilities'].append('approve_capability')
            for p in ws['projects']:
                p['case_type']='formal'
            if ws['projects']:
                p=ws['projects'][0]; p.update(sales_id='u-manager',supervisor_id='u-manager',admin_id='u-manager')
                p['quotes']=[dict(id='review-quote-'+str(i),quote_code='測試報價-'+str(i),engineering_code=p['code'],source_url='',amount=10000*i,fields={'備註':'本機虛構驗收資料'}) for i in (1,2)]
                ws['projects'][-1].update(case_type='intake',name='本機測試：尚未確認接案')
            ws['capability_catalog']=[{'id':'review-skill-1','name':'本機測試：控制測量','active':True,'department':'控制組','level':'示範','source_url':''}]
            ws['review_fixture_version']=1
            ws['version']=row.version+1; row.version=ws['version']; row.data=storage.save(db,BusinessRow,row.id,ws); count+=1
    print('Updated isolated fictional review workspaces:',count)

if __name__=='__main__': main()
