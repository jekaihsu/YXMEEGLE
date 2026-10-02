"""Source reconciliation regressions: all fixtures are in-memory, no remote calls."""
from copy import deepcopy
import json
from .seed import seed
from .sources import configuration, import_sources, source_id


def record(kind, ident, fields, base=None):
    return dict(kind=kind,record_id=ident,table_id=kind,base_token=base or ('quotes' if kind in ('quote','quote_confirmation') else 'v4'),fields=fields)


def confirmation(ident='c1', code='C115001', **fields):
    return record('confirmation',ident,{'工程確認單編號':code,'狀態':'執行中',**fields})


def quote(ident='recQ1', code='115001', engineering='', refs=None):
    return record('quote',ident,{'報價編號':code,'工程編號':engineering,'此案確認單':refs or [],'工程名稱':'source name','契約價格(未稅)':100})


def formal(ws): return [p for p in ws['projects'] if p['case_type']=='formal']
def source_tasks(ws): return [(p,n,t) for p in ws['projects'] for n in p['nodes'] for t in n['tasks'] if t.get('source_identity')]


def test_quote_intakes_do_not_count_as_cases_or_merge_empty_codes():
    ws=seed(True)
    stats=import_sources(ws,[quote('q1',''),quote('q2','')])
    assert stats['projects']==0 and stats['intakes']==2
    assert len({p['id'] for p in ws['projects']})==2
    import_sources(ws,[quote('q1',''),quote('q2','')])
    assert len(ws['projects'])==2


def test_unconfirmed_quote_display_code_cannot_merge_with_formal_case_on_refresh():
    ws=seed(True)
    rows=[confirmation(),quote('q-intake','C115001')]
    import_sources(ws,rows)
    pending=next(p for p in ws['projects'] if p['case_type']=='intake')
    pending['comments']=[{'id':'local-note','body':'keep with this unconfirmed quotation'}]
    before=[(p['id'],p['case_type'],[(n['id'],[t['id'] for t in n['tasks']]) for n in p['nodes']]) for p in ws['projects']]
    for _ in range(3):
        rows[-1]['fields']['備註']='source revision'
        import_sources(ws,rows)
        assert before==[(p['id'],p['case_type'],[(n['id'],[t['id'] for t in n['tasks']]) for n in p['nodes']]) for p in ws['projects']]
        assert len(ws['archived_projects'])==0
        assert pending['comments'][0]['id']=='local-note'
        assert formal(ws)[0]['quotes']==[]


def test_real_native_link_shapes_match_and_empty_links_remain_unresolved():
    def link(table,ident=None):
        result={'table_id':table,'type':'text','text_arr':[]}
        if ident: result.update(record_ids=[ident],text='display only',text_arr=['display only'])
        return [result]
    ws=seed(True)
    c=confirmation('recC1');q=quote(refs=link('confirmation','recC1'))
    q['base_token']='v4'
    linked=record('daily','d-good',{'所屬案件':link('confirmation','recC1'),'日期':'2026-09-27','組別':'控制'})
    empty=record('daily','d-empty',{'所屬案件':link('confirmation'),'內業工項':link('reporting')})
    missing=record('daily','d-unresolved',{'所屬案件':link('confirmation','recMissing'),'日期':'2026-09-27','組別':'控制'})
    stats=import_sources(ws,[c,q,linked,empty,missing])
    assert stats['daily_imported']==1 and len(formal(ws)[0]['quotes'])==1
    assert stats['daily_unmatched_missing_reference']==stats['daily_unmatched_unresolved_reference']==1
    assert stats['daily_missing_date']==stats['daily_missing_department']==1
    assert {d['case_mapping_status'] for d in ws['daily_unmatched']}=={'missing_reference','unresolved_reference'}


def test_formula_date_serial_agrees_with_native_cost_timestamp_without_hiding_conflicts():
    from datetime import datetime, timezone, timedelta
    from .sources import day
    ws=seed(True)
    workday='2026-09-27'
    serial=(datetime.fromisoformat(workday)-datetime(1899,12,30)).days
    native=int(datetime(2026,9,27,tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)
    cost=record('cost','recCost',{'工作日期':native})
    daily=record('daily','d1',{'工程編號':'C115001','組別':'外業','工作日期-薪資':serial,'所屬成本單':['recCost']})
    stats=import_sources(ws,[confirmation(),cost,daily]);d=formal(ws)[0]['daily_reports'][0]
    assert d['date']==workday and stats['daily_conflicting_dates']==0
    assert day(str(serial),formula_serial=True)==workday
    # Only explicitly marked formula dates interpret small numeric values as days.
    assert day(serial)!=workday
    daily['fields']['工作日期-薪資']=serial+1
    stats=import_sources(ws,[confirmation(),cost,daily])
    assert stats['daily_conflicting_dates']==1 and formal(ws)[0]['daily_reports'][0]['date']==''


def test_intake_promotes_via_native_quote_confirmation_without_losing_history():
    ws=seed(True); q=quote(); import_sources(ws,[q]); p=ws['projects'][0]; pid=p['id']
    p['pm_id']='assigned'; p['comments']=[{'id':'manual-comment','body':'preserve'}]
    q['fields']['此案確認單']=['recCQ1']
    cq=record('quote_confirmation','recCQ1',{'工程確認單編號':'C115001','所屬案件':['recQ1']})
    stats=import_sources(ws,[q,cq,confirmation()])
    assert stats['projects']==1 and stats['intakes']==0
    assert len(ws['projects'])==1 and p['id']==pid and p['case_type']=='formal'
    assert p['pm_id']=='assigned' and p['comments'][0]['body']=='preserve'
    assert len(p['quotes'])==1 and len(p['source_records'])==3


def test_multiple_quotes_same_engineering_code_do_not_create_multiple_projects():
    ws=seed(True); rows=[confirmation(),quote('q1',engineering='C115001'),quote('q2','115001-01',engineering='C115001')]
    import_sources(ws,rows); pid=formal(ws)[0]['id']; import_sources(ws,rows)
    assert len(ws['projects'])==1 and formal(ws)[0]['id']==pid
    assert len(formal(ws)[0]['quotes'])==2 and formal(ws)[0]['contract_amount'] is None
    rows[-1]['fields']['契約價格(未稅)']=200; import_sources(ws,rows)
    assert formal(ws)[0]['quotes'][1]['amount']==200


def test_ambiguous_or_broken_native_quote_link_stays_intake():
    ws=seed(True)
    cq=record('quote_confirmation','recCQ1',{'工程確認單編號':'C115001'})
    q=quote(engineering='C115002',refs=['recCQ1'])
    import_sources(ws,[q,cq,confirmation(code='C115002')])
    p=next(p for p in ws['projects'] if p['case_type']=='intake')
    assert p['intake_status']=='multiple_confirmations'
    q['fields']['此案確認單']=['recUnknown']; import_sources(ws,[q,cq,confirmation(code='C115002')])
    assert next(p for p in ws['projects'] if p['case_type']=='intake')['intake_status']=='unresolved_confirmation'


def test_confirmation_first_formula_cannot_hide_conflicting_linked_quote_code():
    ws=seed(True)
    cq=record('quote_confirmation','recCQ1',{'工程確認單編號':'C115001','所屬案件':['recQ1']})
    q=quote(engineering='C115999',refs=['recCQ1'])
    import_sources(ws,[q,cq])
    assert formal(ws)[0]['quotes']==[]
    intake=next(p for p in ws['projects'] if p['case_type']=='intake')
    assert intake['source_conflicts']['confirmation']==['C115001','C115999']


def test_exact_parent_child_syntax_preserves_independent_cases():
    ws=seed(True)
    codes=['C115093','C115093-10','C115093-11','C115093-1','C115093-10-A-02-C11FW']
    import_sources(ws,[confirmation(str(i),code) for i,code in enumerate(codes)])
    assert len(formal(ws))==5
    parents={p['code']:p['parent_code'] for p in formal(ws)}
    assert parents['C115093-10']==parents['C115093-11']=='C115093'
    assert parents['C115093-1'] is None and parents['C115093-10-A-02-C11FW'] is None


def test_code_correction_preserves_identity_but_collision_does_not_move_history():
    ws=seed(True); import_sources(ws,[confirmation()]); p=formal(ws)[0]; pid=p['id']
    import_sources(ws,[confirmation(code='C115002')]); assert p['id']==pid and p['code']=='C115002'
    import_sources(ws,[confirmation(code='C115002'),confirmation('c2','C115003')])
    before={p['id']:p['code'] for p in formal(ws)}
    import_sources(ws,[confirmation(code='C115003'),confirmation('c2','C115002')])
    assert {p['id']:p['code'] for p in formal(ws)}==before
    assert len(ws['source_identity_conflicts'])==2


def test_splitting_one_confirmation_identity_requires_review():
    ws=seed(True); import_sources(ws,[confirmation(),confirmation('c2')]); pid=formal(ws)[0]['id']
    import_sources(ws,[confirmation(code='C115002'),confirmation('c2','C115003')])
    assert len(ws['projects'])==1 and ws['projects'][0]['id']==pid
    assert ws['projects'][0]['code']=='C115001' and len(ws['source_identity_conflicts'])==2


def test_legacy_quote_projects_merge_without_dropping_manual_history():
    ws=seed(True); rows=[confirmation(),quote('q1',engineering='C115001'),quote('q2',engineering='C115001')]
    import_sources(ws,[confirmation()]); first=ws['projects'][0]; second=deepcopy(first)
    first.update(id=source_id(rows[1]),source_model='legacy',code='C115001',source_record_ids=[],source_identity={})
    second.update(id=source_id(rows[2]),source_model='legacy',code='C115001',source_record_ids=[],source_identity={})
    second['nodes'][0]['tasks']=[dict(id='manual-work',title='manual',status='completed',owner_id='owner',required=True)]
    second['comments']=[{'id':'note2','body':'original note'}]
    second['files']=[{'id':'file2','name':'original.pdf'}]
    ws['projects'].append(second)
    import_sources(ws,rows)
    p=ws['projects'][0]
    assert len(ws['projects'])==1 and len(ws['archived_projects'])==1
    assert any(t['id']=='manual-work' for n in p['nodes'] for t in n['tasks'])
    assert any(f['id']=='file2' for f in p['files']) and any(c['id']=='note2' for c in p['comments'])


def test_unstarted_reporting_moves_once_between_cases_and_departments():
    ws=seed(True); a=confirmation(); b=confirmation('c2','C115002')
    item=record('reporting','r1',{'所屬案件':'C115001','工項類別':'控制','工項名稱':'work'})
    import_sources(ws,[a,b,item]); old=source_tasks(ws)[0][2]['id']
    item['fields'].update({'所屬案件':'C115002','工項類別':'圖資'})
    import_sources(ws,[a,b,item]); tasks=source_tasks(ws)
    assert len(tasks)==1 and tasks[0][0]['code']=='C115002' and tasks[0][1]['key']=='mapping' and tasks[0][2]['id']==old


def test_started_reporting_reassignment_is_reviewed_not_duplicated():
    ws=seed(True); a=confirmation(); b=confirmation('c2','C115002')
    item=record('reporting','r1',{'所屬案件':'C115001','工項類別':'控制','工項名稱':'work'})
    import_sources(ws,[a,b,item]); task=source_tasks(ws)[0][2]; task.update(status='in_progress',started_at='2026-09-27')
    item['fields']['所屬案件']='C115002'; import_sources(ws,[a,b,item])
    tasks=source_tasks(ws)
    assert len(tasks)==1 and tasks[0][0]['code']=='C115001'
    assert task['source_change_pending'] and task['source_reassignment_pending']['project_id']==formal(ws)[1]['id']


def test_nonempty_finance_value_is_retained_and_actual_cost_conflicts_visible():
    ws=seed(True)
    import_sources(ws,[confirmation('c1'),confirmation('c2',合約總額=100,實際總成本=20)])
    p=formal(ws)[0]
    assert p['source_finance']['合約總額']==100 and p['source_finance']['實際總成本']==20
    import_sources(ws,[confirmation('c1',實際總成本=30),confirmation('c2',合約總額=100,實際總成本=20)])
    assert '實際總成本' in p['source_conflicts'] and p['source_finance']['實際總成本'] is None


def test_daily_date_disagreement_is_explicit_and_checkboxes_do_not_fabricate_approval():
    ws=seed(True)
    daily=record('daily','d1',{'工程編號':'C115001','組別':'控制','工作日期-薪資':'2026-09-25','工作日期-營業額明細':'2026-09-26','控制組檢核':True,'工務助理檢核':True,'外業經理檢核':True})
    import_sources(ws,[confirmation(),daily]); d=formal(ws)[0]['daily_reports'][0]
    assert d['date']=='' and d['mapping_status']=='conflicting_dates'
    assert d['review']['status']=='unverified' and len(d['review']['checks'])==3
    daily['fields']['檢核狀態']='已退回 '
    import_sources(ws,[confirmation(),daily])
    assert formal(ws)[0]['daily_reports'][0]['review']['status']=='returned'
    daily['fields']['檢核狀態']='已通過'
    import_sources(ws,[confirmation(),daily])
    assert formal(ws)[0]['daily_reports'][0]['review']['status']=='approved'
    assert all(t['status']=='pending' for p,n,t in source_tasks(ws))


def test_configuration_only_allows_expected_source_kinds_per_base(monkeypatch):
    monkeypatch.setenv('LARK_V4_BASE_TOKEN','v4'); monkeypatch.setenv('LARK_QUOTE_BASE_TOKEN','quotes')
    rows=[record('confirmation','c',{}),record('quote','q',{}),record('quote_confirmation','cq',{}),record('quote','q2',{},'unrelated'),record('daily','d',{},'quotes')]
    monkeypatch.setenv('LARK_SOURCE_TABLES_JSON',json.dumps(rows+rows[:1]))
    assert [t['kind'] for t in configuration()]==['confirmation','quote','quote_confirmation']


def test_quote_unlink_keeps_confirmed_case_and_invalidates_votes_on_change():
    from .operations import digest
    ws=seed(True); q=quote(engineering='C115001'); rows=[confirmation(),q]
    import_sources(ws,rows); p=formal(ws)[0]
    p['quote_reviews']=[dict(id='vote1',quote_id=p['quotes'][0]['id'],source_hash=digest(p['quotes'][0]),status='approved')]
    import_sources(ws,rows); assert p['quote_reviews'][0]['status']=='approved'
    q['fields']['工程編號']=''; q['fields']['契約價格(未稅)']=200
    import_sources(ws,rows)
    assert len(ws['projects'])==1 and p['case_type']=='formal'
    assert p['quotes'][0]['amount']==200 and p['quote_reviews'][0]['status']=='invalidated'
    assert any(k.startswith('quote:') for k in p['source_conflicts'])


def test_configuration_accepts_isolated_app_configuration(monkeypatch):
    monkeypatch.setenv('LARK_SOURCE_TABLES_JSON','[]')
    cfg={'LARK_SOURCE_TABLES_JSON':json.dumps([record('confirmation','c1',{})]),'LARK_V4_BASE_TOKEN':'v4'}
    assert len(configuration(cfg))==1 and configuration()==[]


def test_daily_edit_identity_uses_native_open_id_never_a_display_name():
    ws=seed(True)
    daily=record('daily','d1',{'工程編號':'C115001','日期':'2026-09-27','組別':'控制','姓名':[{'id':'ou_reporter','name':'同名員工'},{'text':'ou_fake_display_name'}],'填寫人':'同名員工'})
    import_sources(ws,[confirmation(),daily])
    assert formal(ws)[0]['daily_reports'][0]['source_actor_ids']==['ou_reporter']
