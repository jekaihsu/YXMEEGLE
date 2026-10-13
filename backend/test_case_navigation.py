from copy import deepcopy
from .case_navigation import case_navigation


def fixture():
    confirmations=[dict(id='c',code='C115264',source_kind='confirmation',project_id='p',source_url='case'),
                   dict(id='empty',code='C115264',source_kind='confirmation',project_id='p'),
                   dict(id='quote',source_kind='quote_confirmation',project_id='p')]
    contracts=[];tasks=[]
    for index,size in enumerate((1,3,4,4)):
        cid=f'contract{index}';refs=[];ids=[]
        for item in range(size):
            tid=f't{index}-{item}';rid=f'b/reporting/{tid}'
            refs.append(dict(project_id='p',node_id='n',task_id=tid));ids.append(rid)
            tasks.append(dict(id=tid,source_identity=dict(base_token='b',table_id='reporting',record_id=tid),
                              source_url=rid,source_fields={'secret':'hidden'}))
        contracts.append(dict(id=cid,project_id='p',confirmation_ids=['c'],item_number=str((3,1,1,2)[index]),
                              title='工項',reporting_ids=ids,task_refs=refs,amount_reported=123,
                              fields={'工編號碼':f'C115264-{(3,1,1,2)[index]}'}))
    tasks.append(dict(id='orphan',source_url='orphan',source_fields={'所屬案件':'C115264'}))
    return dict(environment='test',projects=[dict(id='p',nodes=[dict(id='n',tasks=tasks)])],
                source_confirmations=confirmations,contract_items=contracts)


def test_c115264_native_shape_and_safe_projection():
    state=fixture();before=deepcopy(state)
    result=case_navigation(state,'p')['confirmations']
    assert [c['id'] for c in result]==['c','empty']
    case=result[0]
    assert (case['code'],case['source_url'])==('C115264','case')
    assert [c['item_number'] for c in case['contracts']]==['3','1','1','2']
    assert [len(c['work_items']) for c in case['contracts']]==[1,3,4,4]
    assert case['contracts'][0]==dict(id='contract0',item_number='3',title='工項',unresolved=False,
        work_items=[dict(id='b/reporting/t0-0',category='unknown',source_url='b/reporting/t0-0')])
    assert case['edge_states']==dict(contracts='linked',work_items='partial: 外業 work items not imported',
                                     daily='unlinked/unknown',files='unlinked/unknown')
    assert 'amount' not in repr(result) and 'secret' not in repr(result) and 'orphan' not in repr(result)
    assert state==before


def test_missing_links_and_unresolved_contract_are_explicit():
    state=fixture();contract=state['contract_items'][0]
    contract.update(reporting_ids=[],task_refs=[],unresolved_confirmation_ids=['missing'])
    result=case_navigation(state,'p')['confirmations']
    assert result[0]['contracts'][0]['work_items']==[]
    assert result[0]['contracts'][0]['unresolved'] is True
    assert result[1]['contracts']==[]
    assert result[1]['edge_states']==dict(contracts='unlinked/unknown',
        work_items='partial: 外業 work items not imported',daily='unlinked/unknown',files='unlinked/unknown')


def test_project_scope_native_e2_and_visibility():
    state=fixture();state['contract_items'][0]['project_id']='other'
    state['contract_items'][1]['reporting_ids']=[]
    result=case_navigation(state,'p')['confirmations'][0]
    assert [c['id'] for c in result['contracts']]==['contract1','contract2','contract3']
    assert result['contracts'][0]['work_items']==[]
    assert case_navigation(state,'other')=={'confirmations':[]}
    state['environment']='production'
    assert case_navigation(state,'p')=={'confirmations':[]}


def test_current_importer_replay_uses_existing_native_projections():
    from .test_new_daily_acceptance import setup
    state,_=setup()
    state['environment']='test'
    pid=next(c['project_id'] for c in state['source_confirmations'] if c['code']=='C115901')
    case=case_navigation(state,pid)['confirmations'][0]
    assert len(case['contracts'])==1
    assert len(case['contracts'][0]['work_items'])==1
    assert case['contracts'][0]['work_items'][0]['category']=='unknown'
    assert case['edge_states']['work_items']=='partial: 外業 work items not imported'


def test_route_returns_navigation_and_rejects_unknown_project(tmp_path):
    from .test_perf_budget import scaled_client
    with scaled_client(tmp_path,1) as (_,client):
        pid=client.get('/api/workspace').json()['projects'][0]['id']
        response=client.get('/api/projects/'+pid+'/navigation')
        assert response.status_code==200 and response.json()=={'confirmations':[]}
        assert client.get('/api/projects/missing/navigation').status_code==404


def test_production_requires_admitted_source_identity():
    state=fixture();state['environment']='production';state['projects'][0]['case_visibility']='source_reference'
    state['source_visible_record_ids']=['b|confirmations|c','b|contracts|contract0']
    for collection,table in (('source_confirmations','confirmations'),('contract_items','contracts')):
        for row in state[collection]:
            row['source_identity']=dict(base_token='b',table_id=table,record_id=row['id'])
    case=case_navigation(state,'p')['confirmations'][0]
    assert case['id']=='c' and [c['id'] for c in case['contracts']]==['contract0']
