from copy import deepcopy
from .source_projection import project_fields,update_attachments,daily_index,preserve_missing_sources
from .sources import source_id


def test_nonblank_source_finance_conflicts_never_overwrite_manual_values():
    p={'contract_amount':9,'source_records':[
       {'id':'a','kind':'confirmation','fields':{'合約總額':0,'合約結束日期':'2026-10-01'},'url':'one'},
       {'id':'b','kind':'quote_confirmation','fields':{'合約總額':None},'url':'two'}]}
    result=project_fields(p)
    assert result['finance']['contract_amount']==0 and not result['finance']['verified']
    assert result['fields']['due_date']['value']=='2026-10-01' and p['contract_amount']==9
    p['source_records'][1]['fields']['合約總額']=12
    assert project_fields(p)['fields']['contract_amount']['status']=='conflict'
    p['source_records'][1]['source_missing']=True
    assert project_fields(p)['finance']['contract_amount']==0


def test_attachment_index_never_promises_download_and_retains_missing_metadata():
    r={'base_token':'base','table_id':'t','record_id':'r','attachment_fields':['附檔'],
       'fields':{'附檔':[{'file_token':'token','name':'圖.pdf','size':12,'url':'ephemeral-secret-url'}]}}
    ws={'projects':[{'id':'p','nodes':[]}]}; table={'base_token':'base','table_id':'t','status':'ready','attachment_fields':['附檔']}
    update_attachments(ws,[r],[table],{source_id(r):'p'})
    saved=deepcopy(ws['source_attachment_index'][0])
    assert saved['status']=='indexed' and not saved['verified'] and 'url' not in saved
    update_attachments(ws,[],[],{})
    assert ws['source_attachment_index'][0]==saved
    update_attachments(ws,[],[dict(table,attachment_fields=[])],{})
    assert ws['source_attachment_index'][0]==saved  # schema/permission absence is not deletion proof
    update_attachments(ws,[],[table],{})
    assert ws['source_attachment_index'][0]['status']=='source_missing'
    assert len(ws['projects'][0]['source_attachments'])==1
    update_attachments(ws,[r],[table],{source_id(r):'p'})
    assert ws['source_attachment_index'][0]==saved


def test_daily_index_filters_actual_actor_and_paginates_without_exposing_raw_employee_fields():
    ws={'projects':[{'id':'p','code':'C115001','daily_reports':[
        {'id':'a','date':'2026-09-28','source_actor_ids':['ou_a'],'description':'測量','source_fields':{'private':'x'},'source_provenance':{}}]}],
        'daily_unmatched':[{'id':'b','date':'2026-09-27'},{'id':'c','date':'2026-09-26','source_missing':True}],
        'source_status':{'last_sync':'clock'}}
    r=daily_index(ws,limit=1)
    assert r['total']==2 and len(r['items'])==1 and r['summary']=={'matched':1,'unmatched':1,'source_missing':0}
    assert 'source_fields' not in r['items'][0] and r['last_sync']=='clock'
    assert daily_index(ws,actor_id='ou_wrong')['total']==0
    assert daily_index(ws,q='測量',status='matched')['total']==1
    assert daily_index(ws,status='unmatched')['items'][0]['id']=='b'
    assert daily_index(ws,status='source_missing')['items'][0]['id']=='c'


def test_missing_case_and_work_items_keep_history_without_status_change_and_restore():
    source={'base_token':'base','table_id':'t','record_id':'r'}; ident=source_id(source)
    old={'id':ident,'url':'https://example/base/base?table=t&record=r','fields':{'name':'v1'}}
    p={'id':'p','source_records':[deepcopy(old)],'quotes':[{'id':ident,'fields':{'案件已入帳':True}}],
       'nodes':[{'tasks':[{'id':ident,'source_identity':source,'status':'completed','output':'成果'}]}]}
    ws={'projects':[p]}; prior={'p':[deepcopy(old)]}; table={'base_token':'base','table_id':'t','status':'ready'}
    preserve_missing_sources(ws,[],[],prior)
    assert not p['source_missing']
    preserve_missing_sources(ws,[],[table],prior)
    preserve_missing_sources(ws,[],[table],prior)
    assert p['source_missing'] and len(p['source_record_history'])==1
    assert p['quotes'][0]['source_missing'] and p['quotes'][0]['fields']['案件已入帳']
    task=p['nodes'][0]['tasks'][0];assert task['source_missing'] and task['status']=='completed' and task['output']=='成果'
    preserve_missing_sources(ws,[source],[table],prior)
    assert not p['source_missing'] and not task.get('source_missing') and len(p['source_record_history'])==1
    assert not p['quotes'][0].get('source_missing')
