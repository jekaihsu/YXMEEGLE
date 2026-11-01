"""Offline catalog/tool-contract evaluation; scripted choices do not measure model accuracy."""
import json
import pytest
from .test_ai_database import app, client, ai_database_url
from .test_ai_api import BODY, Fake, events
from .test_ai_datasets import PAYLOADS
from .ai.providers import Event, ToolCall
from .ai.datasets import REGISTRY, index


QUESTIONS = [
 ('列出逾期案件','search_cases',{'overdue':True}),
 ('我的進行中案件有哪些','search_cases',{'owner':'me','status':'in_progress'}),
 ('C115 的案件有哪些','search_cases',{'query':'C115'}),
 ('案件 p1 誰負責','case_owners',{'case_id':'p1'}),
 ('案件 p1 哪些工作還沒完成','case_progress',{'case_id':'p1'}),
 ('今天誰遲到','attendance_today',{'range':'today','date':''}),
 ('這週沒有打卡紀錄排名','attendance_today',{'range':'week','date':''}),
 ('上週外業審核退回名單','report_review',{'dept':'field','week':'2026-10-26','status':'returned'}),
 ('甲負責的業務案件','report_sales',{'pm':'甲'}),
 ('上週外業進度剩多少','report_progress',{'dept':'field','week':'2026-10-26'}),
 ('車輛使用次數比較','report_assets',{'kind':'vehicle'}),
 ('儀器最近使用情形','report_assets',{'kind':'instrument'}),
 ('甲這週聯繫哪些案件','report_contacts',{'person':'甲','from':'2026-10-26','to':'2026-11-01'}),
 ('甲十月底的日報','daily_reports',{'actor_id':'甲','date_from':'2026-10-26','date_to':'2026-10-31'}),
 ('本週外業派工','dispatch_board',{'from':'2026-10-26','to':'2026-11-01','group':'外業'}),
 ('p1 外業 SOP 任務狀態','sop_tasks',{'case_id':'p1','node_key':'field'}),
 ('p1 外業節點任務由誰負責','node_detail',{'case_id':'p1','node_key':'field'}),
 ('合約項目 contract1 的名稱','contract_detail',{'key':'contract1'}),
]


@pytest.mark.parametrize('question,ident,params',QUESTIONS,ids=[q[0] for q in QUESTIONS])
def test_scripted_catalog_selection(app,client,monkeypatch,question,ident,params):
    from .ai.tools import Reader
    original=Reader.get
    async def read(self,path,**args):
        if ident in PAYLOADS:
            return PAYLOADS[ident]
        if ident=='attendance_today':
            return dict(days=[],people=[],status='ok',as_of=None)
        return await original(self,path,**args)
    monkeypatch.setattr(Reader,'get',read)
    class Scripted(Fake):
        async def stream(self,spec,system,messages,tools):
            step=len(self.inputs)
            self.inputs.append(messages.copy())
            if step==0:
                assert ident in system and question in messages[0]['content']
                name,args='list_datasets',{}
            elif step==1:
                catalog=json.loads(messages[-1]['content'][0]['content'])['datasets']
                assert ident in {d['id'] for d in catalog}
                name,args='describe_dataset',dict(id=ident)
            elif step==2:
                described=json.loads(messages[-1]['content'][0]['content'])
                assert described['id']==ident
                assert set(params)<=set(described['params']['properties'])
                REGISTRY[ident].params.model_validate(params)
                name,args='query_dataset',dict(id=ident,params=params,limit=20,offset=0)
            else:
                result=json.loads(messages[-1]['content'][0]['content'])
                assert 'error' not in result,result
                assert result['dataset_id']==ident and 'columns' in result and 'limitations' in result
                yield Event('text','查詢結果。')
                yield Event('stop',[])
                return
            call=ToolCall(str(step),name,args)
            yield Event('tool',call)
            yield Event('stop',[dict(type='tool_use',id=call.id,name=name,input=args)])
    app.state.ai_providers={'claude':Scripted()}
    output=events(client.post('/api/ai/chat',json={**BODY,'messages':[dict(role='user',content=question)]}))
    assert output[-1]['type']=='done',output
    assert not any(e.get('status')=='error' for e in output)


@pytest.mark.parametrize('question,missing',[
 ('每月業務營收趨勢','monthly_revenue'),('哪些合約即將到期','contract_expiry')])
def test_unsupported_questions_are_explicit(question,missing):
    assert missing not in REGISTRY
    text=' '.join(d['description'] for d in index())
    assert '無月營收資料' in text and '無到期日資料' in text
