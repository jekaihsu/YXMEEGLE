"""Synthetic case graph built by the production importers; no remote services."""
from copy import deepcopy
from .seed import seed
from .sources import import_sources, source_id
from .source_entities import entity_id
from .source_case_policy import identity, apply_source_reference_policy, filter_visible_cases
from .v4_sources import source_provenance, url


def record(kind, rid, fields):
    return dict(base_token='universe-base',table_id=kind+'-table',record_id=rid,kind=kind,fields=fields)


def link(kind, *ids):
    return [{'table_id':kind+'-table','record_ids':list(ids),'text_arr':[],'type':'text'}]


def build_universe(admit_hidden=False):
    state=seed(True);state['users']=seed()['users']
    records=[record('confirmation','recCaseA',{'工程確認單編號':'C115901'}),
        record('confirmation','recCaseB',{'工程確認單編號':'C115902'}),
        record('confirmation','recCaseC',{'工程確認單編號':'C115901'}),
        record('confirmation','recCaseD',{'工程確認單編號':'C115904'})]
    for rid,refs in [('recQuoteA',['recCaseA']),('recQuoteB',['recCaseB']),
                     ('recQuoteD',['recCaseD']),('recQuoteAB',['recCaseA','recCaseB']),
                     ('recQuoteMissing',['recCaseA'])]:
        records.append(record('quote',rid,{'報價編號':'Q'+rid,'此案確認單':link('confirmation',*refs)}))
    for suffix,refs in [('A',['recCaseA']),('B',['recCaseB']),('AB',['recCaseA','recCaseB']),('Ghost',['recGhostX'])]:
        records.append(record('contract','recContract'+suffix,{'所屬成案確認單（日報關聯）':link('confirmation',*refs)}))
        records.append(record('reporting','recReport'+suffix,{'來源合約明細（日報關聯）':link('contract','recContract'+suffix),
            '工項類別':'控制','工項名稱':'universe item'}))
    records.append(record('daily','recDailyA',{'日期':'2026-10-13','組別':'控制',
        '所屬案件':link('confirmation','recCaseA'),'內業工項':link('reporting','recReportA')}))
    import_sources(state,records)
    qa=next(r for r in records if r['record_id']=='recQuoteA')
    qa['fields']['此案確認單']=link('confirmation','recCaseA','recCaseB')
    next(r for r in records if r['record_id']=='recContractA')['fields']['所屬成案確認單（日報關聯）']=link('confirmation','recCaseA','recCaseB')
    import_sources(state,records)
    qa['fields']['此案確認單']=link('confirmation','recCaseA','recGhostX')
    next(r for r in records if r['record_id']=='recContractA')['fields']['所屬成案確認單（日報關聯）']=link('confirmation','recCaseA')
    current=[r for r in records if r['record_id']!='recQuoteMissing']
    tables=[dict(base_token='universe-base',table_id=k+'-table',status='ready') for k in ('quote','confirmation','contract','reporting','daily')]
    import_sources(state,current,complete_tables=tables)
    state['environment']='production'
    for p in state['projects']:
        p.update(case_visibility='excluded_history',execution_system='meegle')
    pa=next(p for p in state['projects'] if p['code']=='C115901')
    pd=next(p for p in state['projects'] if p['code']=='C115904')
    for p in (pa,pd):
        p.update(case_visibility='new_case',execution_system='workbench',pm_id='u-pm',supervisor_id='u-manager')
    admitted=[r for r in current if r['record_id'] not in ('recCaseB','recCaseC','recQuoteB','recQuoteAB')]
    if admit_hidden:admitted.append(next(r for r in records if r['record_id']=='recCaseC'))
    apply_source_reference_policy(state,{'records':admitted},state['users'][0])
    hb=next(r for r in records if r['record_id']=='recCaseB')
    hq=next(r for r in records if r['record_id']=='recQuoteB')
    index={}
    for r in records:index.setdefault((r['base_token'],r['record_id']),[]).append(r)
    daily=next(r for r in records if r['kind']=='daily')
    native=deepcopy(daily);native['fields']['所屬案件']=link('confirmation','recCaseA','recCaseB','recGhostX')
    provenance=source_provenance(native,index)
    pa['daily_reports'][0]['source_provenance']=deepcopy(provenance)
    pa['nodes'][0]['tasks'][0]['source_provenance']=deepcopy(provenance)
    state['daily_reviews']=[dict(id='universe-review',project_id=pa['id'],daily_id=source_id(daily),
        status='pending',reason='keep this review',parts=[],entry=deepcopy(pa['daily_reports'][0]))]
    # Plant real identities in the additional holders the importers also emit.
    pa['source_entity_ids']['source_confirmations'].append(entity_id(hb))
    pa['source_entity_ids']['source_quotes'].append(entity_id(hq))
    pa['source_record_ids'].append(source_id(hq))
    from .v4_sources import quote_snapshot
    pa['quotes'].append(quote_snapshot(hq))
    pa.setdefault('source_record_history',[]).append(dict(id=source_id(hb),url=url(hb),fields=deepcopy(hb['fields'])))
    pa.setdefault('source_conflicts',{})['quote:'+source_id(hq)]=['C115902']
    state['source_case_review']=[dict(identity=identity(hb),code=['C115902'])]
    return state,records,pa['id']


def forbidden(state, records):
    """Independent oracle: use raw records and policy, never the redaction plan."""
    public=deepcopy(state);filter_visible_cases(public)
    retained={identity(r['source_identity']) for c in ('source_confirmations','source_quotes') for r in public[c]}
    retained|={identity(p.get('source_identity') or {}) for p in public['projects']}
    def tokens(r):
        return {r['record_id'],entity_id(r),identity(r),source_id(r),'record='+r['record_id']}
    hidden=set();allowed=set()
    for r in records:
        if r['kind'] not in ('confirmation','quote','quote_confirmation'):continue
        target=allowed if identity(r) in retained else hidden
        target.update(tokens(r))
        target.update(str(r['fields'][k]) for k in ('工程確認單編號','工程編號','報價編號') if r['fields'].get(k))
    allowed.update(p['code'] for p in public['projects'])
    return hidden-allowed


def walk(value, path=()):
    if isinstance(value,dict):
        for key,item in value.items():
            yield path+(key,),key
            yield from walk(item,path+(key,))
    elif isinstance(value,list):
        for item in value:yield from walk(item,path+('[]',))
    elif isinstance(value,str):yield path,value
