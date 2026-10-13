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


def test_malformed_refs_are_unresolved():
    for ref in ({'project_id':'p'},{'project_id':'p','node_id':'n'},
                {'project_id':'p','task_id':'t0-0'}):
        state=fixture();state['contract_items'][0]['task_refs']=[ref]
        contract=case_navigation(state,'p')['confirmations'][0]['contracts'][0]
        assert contract==dict(id='contract0',item_number='3',title='工項',unresolved=True,work_items=[])


def test_duplicate_codes_never_merge_or_infer_edges():
    state=fixture()
    for contract in state['contract_items']:contract['fields']['工編號碼']='C115264-1'
    orphan=deepcopy(state['contract_items'][0]);orphan.update(id='text-only',confirmation_ids=[])
    state['contract_items'].append(orphan)
    cases=case_navigation(state,'p')['confirmations']
    assert [c['id'] for c in cases[0]['contracts']]==['contract0','contract1','contract2','contract3']
    assert [len(c['work_items']) for c in cases[0]['contracts']]==[1,3,4,4]
    assert cases[1]['contracts']==[]


def test_populated_route_whitelist_and_hidden_cross_project(tmp_path):
    from .test_public_case_http_boundaries import isolated_http
    from .app import WorkspaceRow,BusinessRow
    from . import storage
    app,client,_,_=isolated_http.__wrapped__(tmp_path)
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,'lark-boundary');state=storage.load(db,BusinessRow,row)
        data=fixture()
        for collection in ('source_confirmations','contract_items'):
            for item in data[collection]:
                item['project_id']='p2'
                item['source_identity']=dict(base_token='b',table_id=collection,record_id=item['id'])
                state['source_visible_record_ids'].append('b|'+collection+'|'+item['id'])
                item.update(history=[{'secret':'HISTORY_SECRET'}],source_records=[{'secret':'PAYLOAD_SECRET'}])
            state[collection]=data[collection]
        for ref in state['contract_items'][0]['task_refs']:ref['project_id']='p2'
        for contract in state['contract_items'][1:]:
            for ref in contract['task_refs']:ref['project_id']='p2'
        template=state['projects'][1]['nodes'][0]['tasks'][0]
        state['projects'][1]['nodes'][0]['tasks']=[{**deepcopy(template),**task} for task in data['projects'][0]['nodes'][0]['tasks']]
        for contract in state['contract_items']:
            for ref in contract['task_refs']:ref['node_id']=state['projects'][1]['nodes'][0]['id']
        state['source_confirmations'].append(dict(id='cross',project_id='p1',source_kind='confirmation',code='HIDDEN_SECRET'))
        row.data=storage.save(db,BusinessRow,row.id,state)
    response=client.get('/api/projects/p2/navigation')
    assert response.status_code==200
    cases=response.json()['confirmations']
    assert [c['id'] for c in cases]==['c','empty']
    assert [len(c['work_items']) for c in cases[0]['contracts']]==[1,3,4,4]
    assert set(cases[0])=={'id','code','source_url','contracts','edge_states'}
    assert set(cases[0]['contracts'][0])=={'id','item_number','title','unresolved','work_items'}
    assert set(cases[0]['contracts'][0]['work_items'][0])=={'id','category','source_url'}
    assert all(x not in response.text for x in ('amount','history','PAYLOAD_SECRET','HISTORY_SECRET','HIDDEN_SECRET','count'))
    assert client.get('/api/projects/p1/navigation').status_code==404
    app.state.engine.dispose()


def test_new_collection_drives_categories_and_case_specific_completeness():
    from .test_source_work_items import imported
    state,_,_,_=imported()
    result=case_navigation(state,'p')['confirmations'][0]
    assert [len(c['work_items']) for c in result['contracts']]==[1,3,4,4]
    assert sorted(i['category'] for c in result['contracts'] for i in c['work_items'])==sorted(['報告']*4+['外業']*3+['控制']*3+['圖資']*2)
    assert result['edge_states']['work_items']=='linked'
    state['source_confirmations'].append({'id':'empty-new','project_id':'p','source_kind':'confirmation'})
    assert case_navigation(state,'p')['confirmations'][1]['edge_states']['work_items']=='partial: 外業 work items not imported'
    state['source_work_items_status']['p']['partial']=True
    assert case_navigation(state,'p')['confirmations'][0]['edge_states']['work_items']=='partial: source work items incomplete'
    state['source_work_items_enabled']=False
    assert case_navigation(state,'p')['confirmations'][0]['edge_states']['work_items']=='partial: 外業 work items not imported'
    assert len(state['source_work_items'])==12


def test_collection_route_storage_and_request_ceilings(tmp_path):
    import gzip,json,hashlib
    from .test_perf_budget import scaled_client,count_queries
    from .test_source_work_items import imported
    source,_,_,_=imported()
    def populate(state):
        pid=state['projects'][0]['id']
        for collection in ('source_confirmations','contract_items','source_work_items'):
            state[collection]=deepcopy(source[collection])
            for item in state[collection]:item['project_id']=pid
        state['source_work_items_status']={pid:{'partial':False}}
    with scaled_client(tmp_path,2,mutate=populate) as (app,client):
        # Use the actual project identity from storage, independent of fixture naming.
        with app.state.sessions() as db:
            from .app import WorkspaceRow,BusinessRow
            from . import storage
            wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
            root=db.get(WorkspaceRow,wid);saved=storage.load(db,BusinessRow,root)
            pid=saved['projects'][0]['id']
            assert len(saved['source_work_items'])==12
        for size in (12,696):
            if size==696:
                with app.state.sessions.begin() as db:
                    root=db.get(WorkspaceRow,wid);saved=storage.load(db,BusinessRow,root)
                    template=saved['source_work_items'][0]
                    saved['source_work_items']=[{**template,'id':f'{template["id"]}-{i:04d}',
                        'source_url':template['source_url']+hashlib.sha256(str(i).encode()).hexdigest()} for i in range(size)]
                    root.data=storage.save(db,BusinessRow,wid,saved)
            with count_queries(app.state.engine) as stats:response=client.get(f'/api/projects/{pid}/navigation')
            assert response.status_code==200
            raw=len(response.content);wire=len(gzip.compress(response.content))
            print(f'F7 size={size}: queries={stats["queries"]}, raw={raw}, gzip={wire}, collection={len(json.dumps(saved["source_work_items"],ensure_ascii=False).encode())}')
            assert stats['queries']<=24 and raw<=165_000 and wire<=30_000
            assert len(json.dumps(saved['source_work_items'],ensure_ascii=False).encode())<10_000_000
            with app.state.sessions() as db:
                persisted=storage.load(db,BusinessRow,db.get(WorkspaceRow,wid))
                assert len(persisted['source_work_items'])==size
                other=storage.load_partial(db,BusinessRow,db.get(WorkspaceRow,wid),collections=['source_work_items'],project_ids=[saved['projects'][1]['id']])
                assert other['source_work_items']==[]
            assert response.json()['work_items_status']=={'partial':size!=12,'truncated':size!=12}
            case=response.json()['confirmations'][0]
            assert case['edge_states']['work_items']==('linked' if size==12 else 'partial: source work items truncated')
            if size==12:assert '外業' in response.text


def test_scaled_workspace_omits_work_items_without_affecting_navigation(tmp_path):
    from .test_perf_budget import scaled_client
    from .test_source_work_items import imported
    from .app import WorkspaceRow,BusinessRow
    from . import storage
    with scaled_client(tmp_path,319) as (app,client):
        base=client.get('/api/workspace')
        source,_,_,_=imported()
        wid=app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
        with app.state.sessions.begin() as db:
            row=db.get(WorkspaceRow,wid);state=storage.load(db,BusinessRow,row)
            pid=state['projects'][0]['id']
        before=base
        with app.state.sessions.begin() as db:
            row=db.get(WorkspaceRow,wid);state=storage.load(db,BusinessRow,row)
            state['source_work_items']=[{**source['source_work_items'][i%12],'id':f'b/items/{i}',
                'project_id':pid} for i in range(696)]
            state['source_work_items_status']={pid:{'partial':False}}
            row.data=storage.save(db,BusinessRow,wid,state)
        after=client.get('/api/workspace')
        assert after.status_code==200
        assert 'source_work_items' not in after.json() and 'source_work_items_status' not in after.json()
        # Project concurrency versions can advance; normalize only this storage metadata.
        left,right=before.json(),after.json()
        for payload in (left,right):
            for project in payload['projects']:project.pop('concurrency_version',None)
        import json
        sizes=[len(json.dumps(p,ensure_ascii=False,separators=(',',':')).encode()) for p in (left,right)]
        print(f'workspace base_raw={len(base.content)} before_raw={len(before.content)} after_raw={len(after.content)} normalized={sizes} delta={sizes[1]-sizes[0]}')
        assert sizes[0]==sizes[1]
        with app.state.sessions.begin() as db:
            row=db.get(WorkspaceRow,wid);state=storage.load(db,BusinessRow,row)
            for key in ('source_confirmations','contract_items'):
                state[key]=deepcopy(source[key])
                for item in state[key]:item['project_id']=pid
            row.data=storage.save(db,BusinessRow,wid,state)
        navigation=client.get(f'/api/projects/{pid}/navigation')
        assert navigation.status_code==200
        assert sum(len(c['work_items']) for c in navigation.json()['confirmations'][0]['contracts'])>0


def test_forward_missing_item_and_unattributable_item_are_incomplete():
    from .test_source_work_items import imported
    from .source_entities import update_entities
    from .fixtures.f7_c115264 import CONTRACT,ITEM
    for mode in ('missing','unattributable','renamed'):
        state,records,tables,assignments=imported()
        contract=next(r for r in records if r['kind']=='contract')
        item=next(r for r in records if r['kind']=='reporting')
        if mode=='unattributable':item['fields']['來源合約明細（日報關聯）'][0]['record_ids']=['recNOPE']
        else:contract['fields']['合約填報工項（日報關聯）'][0]['record_ids'].append('recNOPE')
        if mode=='renamed':
            field=next(f for t in tables if t['table_id']==CONTRACT for f in t['field_schema'] if f['field_id']=='fldOFyOZgb')
            field['field_name']='renamed-forward'
            for r in records:
                if r['table_id']==CONTRACT:r['fields']['renamed-forward']=r['fields'].pop('合約填報工項（日報關聯）')
        update_entities(state,records,tables,assignments)
        case=case_navigation(state,'p')['confirmations'][0]
        assert case['contracts'][0]['unresolved'] is True
        assert case['edge_states']['work_items']=='partial: source work items incomplete'
        assert 'recNOPE' not in repr(case)


def test_visible_contract_with_hidden_confirmation_items_is_incomplete():
    from .test_source_work_items import imported
    from .source_entities import entity_id
    state,records,_,_=imported()
    state.update(environment='production',source_visible_record_ids=[entity_id(r).replace('/','|') for r in records])
    state['projects'][0]['case_visibility']='source_reference'
    state['contract_items'][0]['confirmation_ids'].append('HIDDEN_CASE_ID')
    case=case_navigation(state,'p')['confirmations'][0]
    assert case['contracts'][0]['work_items']==[]
    assert case['contracts'][0]['unresolved'] is True
    assert case['edge_states']['work_items']=='partial: source work items incomplete'
    assert 'HIDDEN_CASE_ID' not in repr(case)


def test_http_rollback_and_missing_links_preserve_rows_and_public_omission(tmp_path):
    from .test_public_case_http_boundaries import isolated_http
    from .test_source_work_items import imported
    from .source_entities import entity_id,update_entities
    from .app import WorkspaceRow,BusinessRow
    from . import storage
    app,client,_,_=isolated_http.__wrapped__(tmp_path)
    source,records,tables,assignments=imported()
    try:
        def save_source():
            with app.state.sessions.begin() as db:
                row=db.get(WorkspaceRow,'lark-boundary');state=storage.load(db,BusinessRow,row)
                for key in ('source_confirmations','contract_items','source_work_items'):
                    state[key]=deepcopy(source[key])
                    for item in state[key]:
                        if item.get('project_id'):item['project_id']='p2'
                state['source_work_items_status']={'p2':deepcopy(source['source_work_items_status']['p'])}
                state['source_visible_record_ids']=[entity_id(r).replace('/','|') for r in records]
                row.data=storage.save(db,BusinessRow,row.id,state)
        save_source()
        url='/api/projects/p2/navigation'
        complete=client.get(url).json()
        assert sum(len(c['work_items']) for c in complete['confirmations'][0]['contracts'])==12
        with app.state.sessions() as db:
            original=storage.load(db,BusinessRow,db.get(WorkspaceRow,'lark-boundary'))['source_work_items']
        for enabled in (False,True):
            with app.state.sessions.begin() as db:
                row=db.get(WorkspaceRow,'lark-boundary');state=storage.load(db,BusinessRow,row)
                state['source_work_items_enabled']=enabled
                row.data=storage.save(db,BusinessRow,row.id,state)
            response=client.get(url).json()
            if enabled:assert response==complete
            else:
                assert response['confirmations'][0]['edge_states']['work_items']=='partial: 外業 work items not imported'
                assert 'work_items_status' not in response
            with app.state.sessions() as db:
                stored=storage.load(db,BusinessRow,db.get(WorkspaceRow,'lark-boundary'))['source_work_items']
                assert len(stored)==12 and [i['id'] for i in stored]==[i['id'] for i in original]
                assert stored==original
        item=next(r for r in records if r['kind']=='reporting')
        item['fields']['來源合約明細（日報關聯）'][0]['record_ids']=['recNOPE']
        update_entities(source,records,tables,assignments);save_source()
        case=client.get(url).json()['confirmations'][0]
        assert case['contracts'][0]['unresolved'] is True
        assert case['edge_states']['work_items']=='partial: source work items incomplete'
        workspace=client.get('/api/workspace')
        assert workspace.status_code==200
        assert 'source_work_items' not in workspace.json() and 'source_work_items_status' not in workspace.json()
        assert 'recNOPE' not in repr(case)
        # Hide one native item by its own admission; the visible contract stays partial.
        source,records,tables,assignments=imported();save_source()
        with app.state.sessions.begin() as db:
            row=db.get(WorkspaceRow,'lark-boundary');state=storage.load(db,BusinessRow,row)
            hidden=next(i for i in state['source_work_items'] if state['contract_items'][0]['id'] in i['contract_ids'])
            state['source_visible_record_ids'].remove(hidden['id'].replace('/','|'))
            row.data=storage.save(db,BusinessRow,row.id,state)
        navigation=client.get(url)
        case=navigation.json()['confirmations'][0]
        assert case['contracts'][0]['work_items']==[] and case['contracts'][0]['unresolved'] is True
        assert case['edge_states']['work_items']=='partial: source work items incomplete'
        assert hidden['id'] not in navigation.text
        assert 'source_work_items' not in client.get('/api/workspace').json()
    finally:app.state.engine.dispose()
