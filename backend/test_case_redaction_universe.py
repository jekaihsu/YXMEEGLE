"""Public response oracle over a real-builder universe."""
import json
import pytest
from .case_universe import build_universe, forbidden, walk
from .test_public_case_http_boundaries import isolated_http
from .app import WorkspaceRow, BusinessRow, CacheRow
from . import storage

LEAK_PATHS=[
 'contract_items.[].history.[].snapshot.confirmation_ids.[]',
 'source_quotes.[].history.[].snapshot.confirmation_ids.[]',
 'source_quotes.[].history.[].snapshot.fields.此案確認單.[].record_ids.[]',
 'projects.[].source_entity_ids.source_confirmations.[]',
 'projects.[].source_entity_ids.source_quotes.[]',
 'projects.[].source_record_ids.[]',
 'projects.[].quotes.[].id','projects.[].quotes.[].source_url',
 'projects.[].source_record_history.[].id','projects.[].source_record_history.[].url',
 'projects.[].source_conflicts.quote:', 'policy_summary.[].source_conflicts.quote:',
 'policy_summary.[].closure.financial.incoming.quotes.[].quote_id',
 'policy_summary.[].closure.financial.incoming.quotes.[].source_url',
 'policy_summary.[].closure.missing.[]',
 'daily_reviews.[].entry.source_provenance.records.[].id',
 'daily_reviews.[].entry.source_provenance.unresolved.[].record_id',
 'source_case_review.[].identity','source_case_review.[].code.[]']


def install(app,state):
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,'lark-boundary');row.data=storage.save(db,BusinessRow,row.id,state)


@pytest.mark.parametrize('path',LEAK_PATHS)

def test_known_holder(isolated_http,path):
    app,client,_,signin=isolated_http
    state,records,_=build_universe();install(app,state);signin('u-manager')
    response=client.get('/api/workspace');assert response.status_code==200
    needles=forbidden(state,records)|{'recGhostX'}
    hits=[(p,s) for p,s in walk(response.json()) if '.'.join(p).startswith(path) and any(n in s for n in needles)]
    assert not hits,hits


def test_generic_net_preserves_unknown_containers():
    from . import case_redaction as cr
    hidden='recNonAdmitted'
    out={'rows':[{'id':'keep-row','unknown':hidden,'refs':[hidden,'safe'],hidden:1,
        'url':'https://x.test/base/b?record='+hidden}]}
    plan=cr.Plan(frozenset(),frozenset({hidden}),frozenset())
    cr.apply(out,plan)
    assert out == {'rows':[{'id':'keep-row','unknown':None,'refs':['safe'],'url':None}]}
    assert plan.fallback == 4


def test_differential_planting_every_collection(isolated_http):
    from copy import deepcopy
    from . import case_redaction as cr
    from .storage import COLLECTIONS
    app,client,_,signin=isolated_http
    original,records,_=build_universe();needles=forbidden(original,records)
    # Both runs preserve all real builder output and differ only in probe slots.
    from .source_case_policy import filter_visible_cases
    public=deepcopy(original);filter_visible_cases(public)
    responses=[]
    for token in (sorted(n for n in needles if not n.startswith('record=')),['NEUTRAL-PROBE']):
        state=deepcopy(public)
        def plant(value):
            if isinstance(value,dict):
                for child in list(value.values()):plant(child)
                value.update(zz_probe_s=token[0],zz_probe_l=list(token),zz_probe_k={x:1 for x in token})
            elif isinstance(value,list):
                for child in value:plant(child)
        for collection in set(COLLECTIONS)|{'projects'}:
            plant(state.setdefault(collection,[]))
        cr.apply(state,cr.make_plan(cr.snapshot(original),public))
        responses.append(state)
    def strip(value):
        if isinstance(value,dict):return {k:strip(v) for k,v in value.items() if not k.startswith('zz_probe')}
        if isinstance(value,list):return [strip(v) for v in value]
        return value
    assert strip(responses[0]) == strip(responses[1])
    # Scan probe slots independently of any legacy holders still awaiting L1/L2.
    probe_values=[s for path,s in walk(responses[0]) if any(k.startswith('zz_probe') for k in path)]
    assert not any(n in s for n in needles for s in probe_values)


def test_history_scope_and_unresolved_are_response_only(isolated_http):
    from copy import deepcopy
    app,client,_,signin=isolated_http
    state,records,pid=build_universe()
    state['recurring']=[dict(id='routine-safe',project_id=pid,history=[{'id':'routine-event','evidence':'keep'}])]
    state['approvals']=[dict(id='approval-safe',project_id=pid,type='confirmation',history=[{'id':'approval-event','message':'keep'}])]
    install(app,state);signin('u-manager')
    before=deepcopy(state)
    response=client.get('/api/workspace');assert response.status_code==200
    public=response.json()
    assert public['recurring'][0]['history']==[{'id':'routine-event','evidence':'keep'}]
    assert public['approvals'][0]['history']==[{'id':'approval-event','message':'keep'}]
    assert 'source_case_review' not in public
    for collection in ('source_quotes','source_confirmations','contract_items'):
        assert all('history' not in r for r in public[collection])
    qa=next(q for q in public['source_quotes'] if q['source_identity']['record_id']=='recQuoteA')
    assert qa['unresolved_confirmation_ids']==['［不開放檢視］']
    body=dict(action='comment_add',project_id=pid,version=public['version'],request_id='universe-storage',payload={'body':'hello'})
    for result in (client.post('/api/actions',json=body),client.post('/api/actions',json=body)):
        assert result.status_code==200,result.text
        assert 'source_case_review' not in result.json()
    with app.state.sessions() as db:
        stored=storage.load(db,BusinessRow,db.get(WorkspaceRow,'lark-boundary'))
    for collection in ('source_quotes','source_confirmations','contract_items','daily_reviews','source_case_review','source_visible_record_ids'):
        assert stored[collection]==before[collection]
    old=next(p for p in before['projects'] if p['id']==pid);new=next(p for p in stored['projects'] if p['id']==pid)
    for key in ('quotes','source_record_history','source_record_ids','source_entity_ids','source_conflicts','daily_reports'):
        assert new.get(key)==old.get(key)


def test_builder_id_form_completeness():
    import re
    from .case_universe import walk
    state,records,_=build_universe()
    needles=forbidden(state,records)
    ids={n for n in needles if n.startswith(('rec','src-'))}
    from .source_entities import entity_id
    from .source_case_policy import identity
    from .sources import source_id
    exact={x for r in records for x in (r['record_id'],entity_id(r),identity(r),source_id(r))}
    exact.update(str(r['fields'][k]) for r in records for k in ('工程確認單編號','工程編號','報價編號') if r['fields'].get(k))
    for path,value in walk(state):
        if not any(n in value for n in ids):continue
        explained=value in exact or bool(re.search(r'[?&]record=[^&#]+',value))
        explained |= value.startswith(('quote:','work_item:')) and value.split(':',1)[1] in exact
        explained |= all(part in exact for part in value.split('|'))
        assert explained,(path,value)


def test_admitted_reference_order_and_ghost_whitelist(isolated_http):
    from .source_entities import entity_id
    from .sources import source_id
    from .case_universe import record
    app,client,_,signin=isolated_http
    state,records,pid=build_universe(True)
    a=next(r for r in records if r['record_id']=='recCaseA')
    c=next(r for r in records if r['record_id']=='recCaseC')
    qa=next(q for q in state['source_quotes'] if q['source_identity']['record_id']=='recQuoteA')
    qa['confirmation_ids']=[entity_id(c),'universe-base/confirmation-table/recGhostX',entity_id(a)]
    p=next(p for p in state['projects'] if p['id']==pid)
    p['source_record_ids']=[source_id(c),'src-unknown-ghost',source_id(a)]
    p['source_entity_ids']['source_confirmations']=[entity_id(c),'ghost-confirmation',entity_id(a)]
    install(app,state);signin('u-manager');response=client.get('/api/workspace')
    assert response.status_code==200
    public=response.json();qa=next(q for q in public['source_quotes'] if q['source_identity']['record_id']=='recQuoteA')
    assert qa['confirmation_ids']==[entity_id(c),entity_id(a)]
    p=next(p for p in public['projects'] if p['id']==pid)
    assert p['source_record_ids']==[source_id(c),source_id(a)]
    assert p['source_entity_ids']['source_confirmations']==[entity_id(c),entity_id(a)]
    # Contract ids remain outside phase 1; reference indexing must preserve them.
    assert p['source_entity_ids']['contract_items']


def test_typed_holders_and_derived_business_values(isolated_http,monkeypatch):
    from copy import deepcopy
    from . import case_redaction as cr
    from .sources import source_id
    app,client,_,signin=isolated_http
    state,records,pid=build_universe();install(app,state);signin('u-manager')
    response=client.get('/api/workspace');assert response.status_code==200
    public=response.json();needles=forbidden(state,records)
    assert not any(n in response.text for n in needles),[(path,value) for path,value in walk(response.json()) if any(n in value for n in needles)]
    p=next(p for p in public['projects'] if p['id']==pid)
    missing=next(q for q in p['quotes'] if q.get('source_missing'))
    assert missing['id'].startswith('removed-') and missing['review_available'] is False
    assert missing['quote_code'] is None and missing['engineering_code'] is None
    assert missing['source_url'] is None and missing['fields'] is None
    qa=next(q for q in public['source_quotes'] if q['source_identity']['record_id']=='recQuoteA')
    assert qa['fields']['此案確認單'][0]['record_ids']==['recCaseA','recGhostX']
    hidden_quote=next(r for r in records if r['record_id']=='recQuoteB')
    assert 'quote:'+source_id(hidden_quote) not in p['source_conflicts']
    assert any(k.startswith('quote:') for k in p['source_conflicts'])
    monkeypatch.setattr(cr,'apply',lambda out,plan:plan)
    baseline=client.get('/api/workspace').json()
    def business(rows):
        return [(r['project_id'],r['closure']['status'],len(r['closure']['missing']),
            r['closure']['financial']['incoming']['status']) for r in rows]
    assert business(public['policy_summary'])==business(baseline['policy_summary'])
    assert any('［不開放檢視］' in message for row in public['policy_summary'] for message in row['closure']['missing'])


def test_registered_handler_primitives():
    from . import case_redaction as cr
    plan=cr.Plan(frozenset({'recAdmitted'}),frozenset({'recHiddenCase'}),frozenset({'C999999'}))
    out={'unresolved':[{'record_id':'recGhostID','field':'keep'}],
        'unresolved_quote_ids':['recGhostID'],
        'fields':{'link':[{'record_ids':['recHiddenCase']},{'text':'C999999'},{'record_ids':['recAdmitted']} ]},
        'source_conflicts':{'quote:recHiddenCase':['C999999'],'quote:recAdmitted':['keep','C999999']},
        'quote_ids':['recAdmitted','recGhostID','recHiddenCase']}
    cr.apply(out,plan)
    assert out=={'unresolved':[{'record_id':'［不開放檢視］','field':'keep'}],
        'unresolved_quote_ids':['［不開放檢視］'],
        'fields':{'link':[{'record_ids':['recAdmitted']}]},
        'source_conflicts':{'quote:recAdmitted':['keep']},'quote_ids':['recAdmitted']}
    assert plan.fallback==0


def test_policy_labels_do_not_match_admitted_code_prefixes():
    from . import case_redaction as cr
    plan=cr.Plan(frozenset(),frozenset(),frozenset({'Q1'}),labels={'p':['Q1']})
    out={'policy_summary':[{'project_id':'p','closure':{'missing':['報價 Q1：x','報價 Q10：x']}}]}
    cr.apply(out,plan)
    assert out['policy_summary'][0]['closure']['missing']==['報價 ［不開放檢視］：x','報價 Q10：x']


@pytest.mark.parametrize('viewer,admit_hidden',[('u-pm',False),('u-manager',False),('u-manager',True)])
def test_all_public_routes_and_receipt_replay(isolated_http,viewer,admit_hidden):
    app,client,_,signin=isolated_http
    state,records,pid=build_universe(admit_hidden);install(app,state);signin(viewer)
    with app.state.sessions.begin() as db:
        db.get(CacheRow,'lark-boundary').data={'configured':True,'status':'ready','tables':[],'records':records}
    needles=forbidden(state,records)
    from .source_case_policy import filter_visible_cases
    from copy import deepcopy
    visible=deepcopy(state);filter_visible_cases(visible)
    routes=['/api/workspace','/api/workspace?scope=shell','/api/projects','/api/sources','/api/daily-reports',
            '/api/company-dashboard','/api/audit','/api/session']
    routes += [route for p in visible['projects'] for route in ('/api/projects/'+p['id'],'/api/projects/'+p['id']+'/navigation')]
    for route in routes:
        response=client.get(route);assert response.status_code==200,(route,response.text)
        assert not any(n in response.text for n in needles),route
        assert app.state.case_redaction_stats.fallback==0,route
    public=client.get('/api/workspace').json()
    body=dict(action='comment_add',project_id=pid,version=public['version'],request_id='route-replay-'+viewer,payload={'body':'hello'})
    for response in (client.post('/api/actions',json=body),client.post('/api/actions',json=body)):
        assert response.status_code==200,response.text
        assert not any(n in response.text for n in needles)
        assert app.state.case_redaction_stats.fallback==0


def test_redaction_cost_on_scaled_production(isolated_http,monkeypatch):
    import time,statistics
    from . import case_redaction as cr
    from .perf_fixture import build_scaled_workspace
    app,client,_,signin=isolated_http
    state=build_scaled_workspace();state['environment']='production'
    for p in state['projects']:p.update(case_visibility='new_case',execution_system='workbench')
    install(app,state);signin('u-manager')
    sweep_times=[];request_times=[];apply=cr.apply
    def count(value):
        if type(value) is dict:return 1+sum(count(v) for v in value.values())
        if type(value) is list:return 1+sum(count(v) for v in value)
        return 0
    def measure(out,plan):
        baseline=count(out);start=time.perf_counter();result=apply(out,plan)
        sweep_times.append(time.perf_counter()-start)
        assert result.visited<=baseline*1.1
        return result
    monkeypatch.setattr(cr,'apply',measure)
    for _ in range(3):
        start=time.perf_counter();response=client.get('/api/workspace');request_times.append(time.perf_counter()-start)
        assert response.status_code==200
    assert statistics.median(sweep_times)<=statistics.median(request_times)*0.08
    print('COST sweep_ms',statistics.median(sweep_times)*1000,'request_ms',statistics.median(request_times)*1000,
          'visited',app.state.case_redaction_stats.visited)


def test_redaction_runs_after_private_projection(isolated_http,monkeypatch):
    from . import case_redaction as cr
    app,client,_,signin=isolated_http
    state,records,pid=build_universe();install(app,state);signin('u-pm')
    apply=cr.apply
    def check(out,plan):
        assert all('capabilities' not in u for u in out['users'] if u['id']!='u-pm')
        assert 'task_capabilities_checked_at' in out
        assert not any(k=='source_fields' for path,k in walk(out))
        return apply(out,plan)
    monkeypatch.setattr(cr,'apply',check)
    response=client.get('/api/workspace');assert response.status_code==200


def test_projection_idempotence_and_node_provenance_storage(isolated_http):
    from copy import deepcopy
    from . import case_redaction as cr
    from .source_case_policy import filter_visible_cases
    app,client,_,signin=isolated_http
    state,records,pid=build_universe();before=deepcopy(state)
    out=deepcopy(state);filter_visible_cases(out)
    cr.apply(out,cr.make_plan(cr.snapshot(state),out));once=deepcopy(out)
    cr.apply(out,cr.make_plan(cr.snapshot(state),out));assert out==once
    install(app,state);signin('u-manager');client.get('/api/workspace')
    with app.state.sessions() as db:
        stored=storage.load(db,BusinessRow,db.get(WorkspaceRow,'lark-boundary'))
    assert stored['source_quotes']==before['source_quotes']
    project=next(p for p in stored['projects'] if p['id']==pid)
    original=next(p for p in before['projects'] if p['id']==pid)
    assert [t.get('source_provenance') for n in project['nodes'] for t in n['tasks']]==[
        t.get('source_provenance') for n in original['nodes'] for t in n['tasks']]


def test_source_cache_excluded_history_keeps_rows_without_case_identity(isolated_http):
    from .source_case_policy import identity
    app,client,_,signin=isolated_http
    state,records,_=build_universe()
    hidden=next(r for r in records if r['record_id']=='recCaseB')
    state['source_visible_record_ids'].append(identity(hidden));install(app,state);signin('u-manager')
    with app.state.sessions.begin() as db:
        db.get(CacheRow,'lark-boundary').data={'configured':True,'status':'ready','tables':[],'records':records}
    response=client.get('/api/sources');assert response.status_code==200
    assert not any(n in response.text for n in forbidden(state,records))
    masked=next(r for r in response.json()['records'] if r['kind']=='confirmation' and r['record_id'] is None)
    assert masked['fields']['工程確認單編號'] is None
    assert app.state.case_redaction_stats.fallback==0
