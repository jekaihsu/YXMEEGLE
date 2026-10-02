"""New V4 daily acceptance. Synthetic fixtures only: no network or production writes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from .seed import seed
from .sources import import_sources, source_id

BASE='acceptance-v4'
TABLES={'confirmation':'tbl-confirmation','contract':'tbl-contract','reporting':'tbl-reporting','daily':'tbl-daily','cost':'tbl-cost'}

def row(kind, rid, fields, **extra):
    return dict(base_token=BASE,table_id=TABLES[kind],record_id=rid,kind=kind,fields=fields,**extra)

def link(kind, *ids):
    return [{'table_id':TABLES[kind],'record_ids':list(ids),'text_arr':[],'type':'text'}]

def source_rows():
    return [row('confirmation','recCaseA',{'工程確認單編號':'C115901','狀態':'執行中'}),
            row('confirmation','recCaseB',{'工程確認單編號':'C115902','狀態':'執行中'}),
            row('contract','recContractA',{'所屬成案確認單（日報關聯）':link('confirmation','recCaseA')}),
            row('reporting','recReportingA',{'來源合約明細（日報關聯）':link('contract','recContractA'),'工項類別':'控制','工項名稱':'ACCEPTANCE synthetic item'})]

def daily(**fields):
    return row('daily','recNewDaily',{'日期':'2026-09-27','組別':'控制','備註':'ACCEPTANCE synthetic new daily',**fields})

def setup():
    state=seed(True); records=source_rows();import_sources(state,records);return state,records

def shape(state):
    return [(p['id'],p['code'],[(n['id'],n['status'],[(t['id'],t['status'],t['output']) for t in n['tasks']]) for n in p['nodes']]) for p in state['projects']]

def reports(state):return [d for p in state['projects'] for d in p['daily_reports']]

@pytest.mark.parametrize('fields',[{'所屬案件':link('confirmation','recCaseA')},{'內業工項':link('reporting','recReportingA')},{'合約工項':link('reporting','recReportingA')}])
def test_new_daily_joins_existing_case_without_case_or_task_mutation(fields):
    state,records=setup();before=shape(state); item=daily(**fields);stats=import_sources(state,records+[item]);
    assert shape(state)==before
    assert stats['daily_imported']==1 and stats['daily_unmatched']==0
    assert reports(state)[0]['case_code']=='C115901'
    assert reports(state)[0]['id']==source_id(item)
    assert reports(state)[0]['review']['status']=='unverified'


def test_repeated_sync_and_source_edit_replace_same_daily_id_only():
    state,records=setup();before=shape(state);item=daily(**{'所屬案件':link('confirmation','recCaseA')});snapshot=deepcopy(item)
    for _ in range(3):import_sources(state,records+[item])
    assert item==snapshot and len(reports(state))==1 and shape(state)==before
    item['fields']['備註']='ACCEPTANCE corrected description';import_sources(state,records+[item])
    assert len(reports(state))==1 and reports(state)[0]['description']==item['fields']['備註']
    assert reports(state)[0]['id']==source_id(item) and shape(state)==before

@pytest.mark.parametrize('fields,reason',[({},'missing_reference'),({'所屬案件':link('confirmation','recUnknown')},'unresolved_reference'),({'所屬案件':link('confirmation','recCaseA','recCaseB')},'ambiguous_reference'),({'所屬案件':link('confirmation','recCaseA'),'案件編號':'C115902'},'ambiguous_reference')])
def test_missing_unknown_and_conflicting_references_never_create_a_case(fields,reason):
    state,records=setup();before=shape(state);stats=import_sources(state,records+[daily(**fields)])
    assert shape(state)==before and not reports(state)
    assert stats['daily_unmatched']==1 and state['daily_unmatched'][0]['case_mapping_status']==reason


def test_native_reference_change_moves_same_daily_and_preserves_projects():
    state,records=setup();before=shape(state);item=daily(**{'所屬案件':link('confirmation','recCaseA')});import_sources(state,records+[item]);ident=reports(state)[0]['id']
    item['fields']['所屬案件']=link('confirmation','recCaseB');import_sources(state,records+[item])
    assert shape(state)==before and len(reports(state))==1
    assert reports(state)[0]['id']==ident and reports(state)[0]['case_code']=='C115902'


def test_cost_reference_only_is_not_case_identity():
    state,records=setup();before=shape(state);cost=row('cost','recCostA',{'工作日期':'2026-09-27','內業組別':'控制','填報帳號':[{'id':'ou_native_actor','name':'同名'}]});item=daily(**{'所屬成本單':link('cost','recCostA')})
    import_sources(state,records+[cost,item]);entry=state['daily_unmatched'][0]
    assert not reports(state) and entry['case_mapping_status']=='missing_reference' and shape(state)==before
    assert entry['source_actor_ids']==['ou_native_actor']


def test_formula_date_and_cost_date_agree_but_conflict_never_uses_import_date():
    state,records=setup();serial=(datetime(2026,9,27)-datetime(1899,12,30)).days
    native=int(datetime(2026,9,27,tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)
    cost=row('cost','recCostA',{'工作日期':native,'內業組別':'控制'})
    item=daily(**{'日期':None,'工作日期-薪資':serial,'所屬案件':link('confirmation','recCaseA'),'所屬成本單':link('cost','recCostA')})
    import_sources(state,records+[cost,item]);assert reports(state)[0]['date']=='2026-09-27'
    item['fields']['工作日期-薪資']=serial+1;stats=import_sources(state,records+[cost,item])
    assert reports(state)[0]['date']=='' and reports(state)[0]['mapping_status']=='conflicting_dates' and stats['daily_conflicting_dates']==1
    item['fields']['工作日期-薪資']=None;item['fields']['所屬成本單']=[];stats=import_sources(state,records+[item])
    assert reports(state)[0]['date']=='' and stats['daily_missing_date']==1


def test_native_actor_ids_never_resolve_display_names_or_approve_checkboxes():
    state,records=setup();item=daily(**{'所屬案件':link('confirmation','recCaseA'),'姓名':[{'id':'ou_real','name':'同名員工'},{'text':'ou_fake'}],'填寫人':'同名員工','品管檢核':True,'工務助理檢核':True})
    original=deepcopy(item);import_sources(state,records+[item]);entry=reports(state)[0]
    assert entry['source_actor_ids']==['ou_real'] and entry['review']['status']=='unverified'
    assert item==original and entry['review']['source_url']==entry['source_url']


def test_legacy_migration_rows_and_new_report_have_separate_acceptance_scope():
    state,records=setup();legacy=[row('daily','recLegacyA',{'備註':'migration fixture'}),row('daily','recLegacyB',{'可能確認單工作編號':'C999999'})]
    item=daily(**{'所屬案件':link('confirmation','recCaseA')});stats=import_sources(state,records+legacy+[item])
    assert stats['daily_unmatched']==2 and stats['daily_imported']==1
    assert reports(state)[0]['id']==source_id(item)


def test_known_and_unknown_native_links_do_not_silently_certify_one_case():
    state,records=setup();item=daily(**{'所屬案件':link('confirmation','recCaseA','recUnknown')});stats=import_sources(state,records+[item])
    assert stats['daily_imported']==0, 'Incomplete native relationship must remain unresolved, not silently pick the known half'


def test_outdoor_native_participants_are_preserved_as_ids():
    state,records=setup();item=daily(**{'所屬案件':link('confirmation','recCaseA'),'組長帳號-津貼自動化':[{'id':'ou_leader'}],'組員帳號-津貼自動化':[{'id':'ou_member'}]});import_sources(state,records+[item])
    assert reports(state)[0]['source_actor_ids']==['ou_leader','ou_member']


@pytest.mark.parametrize('work_field',['合約工項','內業工項'])
def test_real_legacy_empty_native_envelope_becomes_matched_when_new_link_arrives(work_field):
    state,records=setup();before=shape(state)
    def empty(kind):return [{'table_id':TABLES[kind],'text_arr':[],'type':'text'}]
    item=daily(**{'所屬案件':empty('confirmation'),work_field:empty('reporting')})
    stats=import_sources(state,records+[item])
    assert stats['daily_unmatched_missing_reference']==1 and not reports(state)
    # Real Base link returns the same wrapper plus record_ids after selection.
    item['fields']['所屬案件']=link('confirmation','recCaseA')
    item['fields'][work_field]=link('reporting','recReportingA')
    stats=import_sources(state,records+[item])
    assert stats['daily_imported']==1 and not state['daily_unmatched']
    assert reports(state)[0]['id']==source_id(item) and shape(state)==before


def test_direct_case_with_unresolved_selected_work_item_requires_upstream_repair():
    state,records=setup()
    records[-1]['fields']['來源合約明細（日報關聯）']=[]
    item=daily(**{'所屬案件':link('confirmation','recCaseA'),'內業工項':link('reporting','recReportingA')})
    stats=import_sources(state,records+[item])
    assert stats['daily_unmatched_unresolved_reference']==1 and not reports(state)
    records[-1]['fields']['來源合約明細（日報關聯）']=link('contract','recContractA')
    stats=import_sources(state,records+[item])
    assert stats['daily_imported']==1 and reports(state)[0]['case_code']=='C115901'
