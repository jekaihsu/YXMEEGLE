from decimal import Decimal
from copy import deepcopy
import json
import pytest
from .contract_links import (parse_records, resolve_line, resolve_item, build_projection,
                             Status, Reason, code_key, plan_summary)


def row(kind, ident, **fields):
    return dict(base_token='b', table_id=kind, record_id=ident, kind=kind, fields=fields)


def line(ident='l', code='X-1', qty='12', name='Synthetic item'):
    return row('contract',ident,工編號碼=code,外業數量=qty,外業工項=name)


def item(ident='i', code='X-1', qty=0, name='item', **fields):
    return row('reporting',ident,工編號碼=code,工項類別='外業',基準數量=qty,填報工項='X|外業|'+name,**fields)


def resolve(rows):
    parsed=parse_records(rows)
    return resolve_item(parsed.items[0],parsed.lines)


def test_unique_and_exact_code_normalization():
    result=resolve([line(code=' x\u200b - 1 '),item(code='X-1')])
    assert (result.line_id,result.status,result.reason,result.candidate_ids)==('b/contract/l',Status.UNIQUE,Reason.EXACT_MATCH,('b/contract/l',))
    assert code_key(' c\u200d 1\t-\n2 ')=='C1-2'
    assert resolve([line(code='C115264-1'),item(code='115264-1')]).reason==Reason.NO_MATCH


@pytest.mark.parametrize('quantity,same', [('12',True),('13',False)])
def test_ambiguous_candidates_never_choose(quantity,same):
    result=resolve([line('a'),line('b',qty=quantity),item()])
    assert (result.status,result.reason,result.line_id,result.same_quantity)==(Status.AMBIGUOUS,Reason.MULTIPLE_MATCHES,None,same)
    assert result.candidate_ids==('b/contract/a','b/contract/b')


@pytest.mark.parametrize('qty,expected', [(0,Status.AMBIGUOUS),('',Status.AMBIGUOUS),('12.0',Status.UNIQUE)])
def test_positive_base_quantity_is_an_exact_filter(qty,expected):
    result=resolve([line('a'),line('b',qty=13),item(qty=qty)])
    assert result.status==expected
    if expected==Status.UNIQUE: assert result.line_id=='b/contract/a'


def test_missing_code_name_quantity_and_mismatch_fail_closed():
    assert resolve([line(),item(code='')]).reason==Reason.NO_CODE
    assert resolve([line(),item(name='')]).reason==Reason.NO_NAME
    assert resolve([line(qty=''),item()]).status==Status.NONE
    assert resolve([line(),item(qty=13)]).reason==Reason.QUANTITY_MISMATCH
    assert resolve([line(),item(name='absent')]).reason==Reason.NO_MATCH


def test_native_link_is_left_alone_even_when_derived_match_differs():
    result=resolve([line(),item(**{'來源合約明細（日報關聯）':[{'id':'other'}]})])
    assert (result.status,result.reason,result.line_id,result.candidate_ids)==(Status.NONE,Reason.NATIVE_LINK_PRESENT,None,())


def test_rule_a_removes_only_the_last_segment_and_requires_one_confirmation():
    parsed=parse_records([line(code='C115264-01-3'),row('confirmation','c',工程確認單編號=' c115264 -01\u200b ')])
    assert (parsed.lines[0].prefix,parsed.lines[0].item_no)==('C115264-01','3')
    result=resolve_line(parsed.lines[0],parsed.confirmations)
    assert (result.confirmation_id,result.status)==('b/confirmation/c',Status.UNIQUE)
    duplicate=parse_records([row('confirmation','d',工程確認單編號='C115264-01')]).confirmations
    assert resolve_line(parsed.lines[0],parsed.confirmations+duplicate).reason==Reason.MULTIPLE_MATCHES
    assert resolve_line(parsed.lines[0],()).reason==Reason.NO_MATCH
    assert resolve_line(parse_records([line(code='')]).lines[0],()).reason==Reason.NO_CODE
    assert resolve_line(parse_records([line(code='C115264')]).lines[0],parsed.confirmations).status==Status.NONE


def test_duplicate_plan_groups_exclude_quantities_and_preserve_native_projects():
    records=[line('a'),line('b',qty='13'),line('c',code='X-2',qty='5'),item(),
             item('native',code='X-2',**{'來源合約明細（日報關聯）':[{'id':'c'}]}),
             row('confirmation','c',工程確認單編號='X')]
    before=deepcopy(records)
    projection=build_projection(records,{'b/confirmation/c':'p'},{'b/contract/c':'q'})
    summary=projection.plans['p'];category=summary['categories']['外業']
    assert category==dict(lines=2,planned_qty='0',items=1,items_native=0,items_native_unresolved=0,items_derived=0,items_ambiguous=1,items_unlinked=0,needs_review=2)
    assert summary['review_groups']==[dict(key='X-1',category='外業',line_ids=['b/contract/a','b/contract/b'])]
    assert projection.plans['q']['categories']['外業']['planned_qty']=='5'
    assert projection.plans['q']['basis']==dict(native=1,native_unresolved=0,derived=0,ambiguous=0,unlinked=0)
    assert projection.status==dict(lines_total=3,lines_derived=2,lines_unmatched=0,items_native=1,items_native_unresolved=0,items_derived=0,items_ambiguous=1,items_unlinked=0)
    assert records==before
    json.dumps(projection.plans,allow_nan=False)


def test_unique_item_inherits_derived_line_and_no_executable_or_done_data():
    projection=build_projection([line(),item(),row('confirmation','c',工程確認單編號='X')],{'b/confirmation/c':'p'}, {})
    summary=projection.plans['p']
    assert summary['categories']['外業']['planned_qty']=='12'
    assert summary['items']==[dict(id='b/reporting/i',category='外業',line_id='b/contract/l',basis='derived',reason='exact_match')]
    assert summary['basis']==dict(native=0,native_unresolved=0,derived=1,ambiguous=0,unlinked=0)
    assert summary['rule_version']=='contract-links-20261017.1'
    assert not {'tasks','completion','progress','done'} & summary.keys()


def test_payload_is_bounded_and_native_unresolved_does_not_fall_back():
    records=[line(),row('confirmation','c',工程確認單編號='X')]+[item(str(i)) for i in range(240)]
    projection=build_projection(records,{'b/confirmation/c':'p'}, {})
    assert len(projection.plans['p']['items'])<=200
    assert len(json.dumps(plan_summary({'derived_plan':projection.plans},'p'),ensure_ascii=False,separators=(',',':')).encode())<=24_000
    assert projection.plans['p']['truncated'] is True
    records[0]['fields']['所屬成案確認單（日報關聯）']=[{'id':'missing'}]
    assert build_projection(records,{'b/confirmation/c':'p'}, {}).plans=={}


def test_invalid_nonfinite_quantities_are_not_planned():
    parsed=parse_records([line(qty='NaN'),item(qty='Infinity')])
    assert parsed.lines[0].qty['外業'] is None and parsed.items[0].base_qty is None
    assert parse_records([line(qty='12.50')]).lines[0].qty['外業']==Decimal('12.50')


def test_importer_is_additive_and_replaces_stale_projection(monkeypatch):
    from .seed import seed
    from .sources import import_sources
    from . import contract_links
    from .test_new_daily_acceptance import row as source_row
    records=[source_row('confirmation','recCase',{'工程確認單編號':'X','狀態':'執行中'}),
             source_row('contract','recLine',{'工編號碼':'X-1','控制工項':'Synthetic','控制數量':12}),
             source_row('reporting','recItem',{'工編號碼':'X-1','工項類別':'控制','工項名稱':'Synthetic','基準數量':0})]
    tables=[dict(base_token=r['base_token'],table_id=r['table_id'],kind=r['kind'],status='ready') for r in records]
    state=seed(True);import_sources(state,records,complete_tables=tables)
    pid=next(p['id'] for p in state['projects'] if p['code']=='X')
    assert state['derived_plan'][pid]['categories']['控制']['planned_qty']=='12'
    assert state['derived_plan_status']==dict(lines_total=1,lines_derived=1,lines_unmatched=0,items_native=0,items_native_unresolved=0,items_derived=1,items_ambiguous=0,items_unlinked=0,partial=False)
    assert next(c for c in state['contract_items'] if c['source_identity']['record_id']=='recLine')['project_id'] is None
    before=deepcopy(state)
    monkeypatch.setattr(contract_links,'build_projection',lambda *args,**kwargs:contract_links.Projection({},{}))
    import_sources(state,records,complete_tables=tables)
    for key in ('projects','contract_items','source_work_items','source_work_items_status'):
        assert state[key]==before[key]
    assert state['derived_plan']=={} and state['derived_plan_status']=={'partial':False}


def test_visibility_never_exposes_hidden_project_or_source_dependencies():
    from .source_case_policy import filter_visible_cases
    projection=build_projection([line(),item(),row('confirmation','c',工程確認單編號='X')],{'b/confirmation/c':'p'}, {})
    state=dict(environment='production',projects=[dict(id='p',nodes=[],case_visibility='new_case')],
               derived_plan=projection.plans,derived_plan_status=projection.status,
               source_visible_record_ids=['b|contract|l','b|reporting|i','b|confirmation|c'])
    assert 'p' in filter_visible_cases(deepcopy(state))['derived_plan']
    state['source_visible_record_ids'].remove('b|contract|l')
    filtered=filter_visible_cases(deepcopy(state))
    assert filtered['derived_plan']=={} and 'derived_plan_status' not in filtered
    state['projects'][0]['case_visibility']='excluded_history'
    assert filter_visible_cases(state)['derived_plan']=={}


def test_native_line_link_never_overrides():
    records=[line('native',code='Y-1',qty=2),line('derived'),
             item(**{'來源合約明細（日報關聯）':[{'id':'native'}]}),
             row('confirmation','c',工程確認單編號='X')]
    projection=build_projection(records,{'b/confirmation/c':'p'},{'b/contract/native':'q'})
    assert projection.plans['q']['items']==[dict(id='b/reporting/i',category='外業',line_id='b/contract/native',basis='native',reason='native_link_present')]
    assert projection.plans['p']['basis']['derived']==0


def test_explicit_native_target_table_is_required():
    records=[line(),item(**{'來源合約明細（日報關聯）':[{'table_id':'other','record_id':'l'}]})]
    parsed=parse_records(records)
    assert parsed.items[0].native_line_ids==()
    assert resolve_item(parsed.items[0],parsed.lines).reason==Reason.NATIVE_LINK_PRESENT


@pytest.mark.parametrize('native_link', [True, False])
def test_native_item_project_wins_over_line_placement(native_link):
    fields={'來源合約明細（日報關聯）':[{'id':'l'}]} if native_link else {}
    records=[line(),item(**fields),row('confirmation','c',工程確認單編號='X')]
    projection=build_projection(records,{} if native_link else {'b/confirmation/c':'other'}, {},
                                native_item_projects={'b/reporting/i':'native'})
    assert projection.plans['native']['items']==[dict(id='b/reporting/i',category='外業',
        line_id='b/contract/l',basis='native' if native_link else 'derived',
        reason='native_link_present' if native_link else 'exact_match')]
    assert projection.plans.get('other',{}).get('items',[])==[]


@pytest.mark.parametrize('qty', [0, -2])
def test_nonpositive_lines_are_not_planned_or_candidates(qty):
    projection=build_projection([line('zero',qty=qty),line('positive'),item(),
        row('confirmation','c',工程確認單編號='X')],{'b/confirmation/c':'p'}, {})
    counts=projection.plans['p']['categories']['外業']
    assert (counts['lines'],counts['planned_qty'],counts['needs_review'])==(1,'12',0)
    assert projection.plans['p']['review_groups']==[]
    assert projection.plans['p']['items']==[dict(id='b/reporting/i',category='外業',
        line_id='b/contract/positive',basis='derived',reason='exact_match')]


@pytest.mark.parametrize('missing', [None,'confirmation','contract','reporting'])
def test_partial_import_preserves_previous_plan(missing):
    from .seed import seed
    from .v4_sources import import_v4
    records=[row('confirmation','c',工程確認單編號='X'),line(),item()]
    tables=[dict(base_token='b',table_id=kind,kind=kind,status='ready' if kind!=missing else 'error')
            for kind in ('confirmation','contract','reporting')]
    state=seed(True)
    state.update(derived_plan={'previous':{'marker':42}},derived_plan_status={'lines_derived':7})
    import_v4(state,records,complete_tables=tables if missing else None)
    assert state['derived_plan']=={'previous':{'marker':42}}
    assert state['derived_plan_status']=={'lines_derived':7,'partial':True}


def test_line_and_unresolved_native_provenance_is_additive_and_private():
    records=[line('a'),line('b',code='X-2'),
        item(**{'來源合約明細（日報關聯）':[{'id':'missing'}]}),
        row('confirmation','c',工程確認單編號='X')]
    records[0]['fields'].update(控制數量=3,控制工項='Control')
    projection=build_projection(records,{'b/confirmation/c':'p'},{'b/contract/a':'p'},
        native_item_projects={'b/reporting/i':'p'})
    summary=plan_summary({'derived_plan':projection.plans},'p')
    assert summary['lines_basis']=={'native':1,'derived':1}
    assert summary['basis']=={'native':0,'native_unresolved':1,'derived':0,'ambiguous':0,'unlinked':0}
    assert summary['categories']['外業']['items_native_unresolved']==1
    assert summary['items']==[dict(id='b/reporting/i',category='外業',line_id=None,
        basis='native_unresolved',reason='native_link_present')]
    assert projection.status['items_native_unresolved']==1
    assert projection.status['lines_derived']==1
    assert '_source_ids' not in summary
    assert projection.plans['p']['_source_ids']==['b/confirmation/c','b/contract/a','b/contract/b','b/reporting/i']


@pytest.mark.parametrize('quantity,expected', [('0.00000001','0.00000001'),('1E+3','1000'),('0E+1','0')])
def test_plan_quantity_uses_plain_decimal_strings(quantity, expected):
    projection=build_projection([row('confirmation','c',工程確認單編號='X'),line(qty=quantity)], {'b/confirmation/c':'p'}, {})
    assert projection.plans['p']['categories']['外業']['planned_qty']==expected
