from collections import Counter
from copy import deepcopy
import json
from .fixtures.f7_c115264 import fixture,BASE,CONF,CONTRACT,ITEM
from .source_entities import entity_id,update_entities
from .source_case_policy import filter_visible_cases
from .sources import source_id


def imported():
    records,tables=fixture()
    state={'environment':'test','projects':[{'id':'p','nodes':[]}]}
    assignments={source_id(r):'p' for r in records}
    update_entities(state,records,tables,assignments)
    return state,records,tables,assignments


def test_live_shape_category_fidelity_and_idempotence():
    state,records,tables,assignments=imported()
    items=state['source_work_items'];before=deepcopy(state)
    assert Counter(i['category'] for i in items)=={'報告':4,'外業':3,'控制':3,'圖資':2}
    assert [sum(entity_id(c) in i['contract_ids'] for i in items) for c in records if c['kind']=='contract']==[1,3,4,4]
    assert set(items[0])=={'id','project_id','contract_ids','category','source_url','source_missing'}
    assert all(i['project_id']=='p' and not i['source_missing'] for i in items)
    assert '999' not in json.dumps(items) and '12345' not in json.dumps(items)
    update_entities(state,records,tables,assignments)
    assert state==before


def test_missing_rows_preserved_only_after_complete_snapshot():
    state,records,tables,assignments=imported();removed=next(r for r in records if r['kind']=='reporting')
    remaining=[r for r in records if r is not removed]
    update_entities(state,remaining,[],assignments)
    assert not next(i for i in state['source_work_items'] if i['id']==entity_id(removed))['source_missing']
    update_entities(state,remaining,tables,assignments)
    assert len(state['source_work_items'])==12
    assert next(i for i in state['source_work_items'] if i['id']==entity_id(removed))['source_missing'] is True


def test_field_ids_and_hidden_linked_case_fail_closed():
    state,records,tables,assignments=imported()
    state.update(environment='production',source_visible_record_ids=['|'.join(r[k] for k in ('base_token','table_id','record_id')) for r in records])
    state['projects'][0]['case_visibility']='source_reference'
    assert len(filter_visible_cases(deepcopy(state))['source_work_items'])==12
    state['projects'].append({'id':'hidden','nodes':[],'case_visibility':'excluded_history'})
    state['contract_items'][0]['task_refs']=[{'project_id':'hidden','node_id':'n','task_id':'t'}]
    assert len(filter_visible_cases(deepcopy(state))['source_work_items'])==11
    for table in tables:
        for field in table['field_schema']:
            old=field['field_name'];field['field_name']=field['field_id']
            for r in records:
                if r['table_id']==table['table_id'] and old in r['fields']:r['fields'][field['field_id']]=r['fields'].pop(old)
    update_entities(state,records,tables,assignments)
    assert Counter(i['category'] for i in state['source_work_items'])=={'報告':4,'外業':3,'控制':3,'圖資':2}


def test_bounded_project_projection_reports_truncation_without_deleting():
    from .source_work_items import project_work_items
    state,_,_,_=imported()
    items,status=project_work_items(state,'p',max_rows=2,max_bytes=1024)
    assert len(items)==2 and status['truncated'] and status['partial']
    assert status['payload_bytes']<=1024 and len(state['source_work_items'])==12
    items,status=project_work_items(state,'p',max_bytes=2)
    assert items==[] and status['truncated']
    items,status=project_work_items(state,'p')
    assert len(items)==12 and not status['partial'] and status['payload_bytes']<10_000_000


def test_normal_importer_refresh_preserves_existing_collections(monkeypatch):
    from .seed import seed
    from .sources import import_sources
    from . import source_work_items
    records,tables=fixture();state=seed(True)
    import_sources(state,records,complete_tables=tables)
    reference=deepcopy(state);before=deepcopy(state['source_work_items'])
    import_sources(state,records,complete_tables=tables)
    assert state['source_work_items']==before and len(before)==12
    monkeypatch.setattr(source_work_items,'update_work_items',lambda *args:None)
    import_sources(reference,records,complete_tables=tables)
    for collection in ('source_quotes','source_confirmations','contract_items'):
        assert state[collection]==reference[collection]


def test_each_linked_confirmation_must_be_authorized_even_with_same_project():
    state,records,_,_=imported()
    state.update(environment='production',source_visible_record_ids=['|'.join(r[k] for k in ('base_token','table_id','record_id')) for r in records])
    state['projects'][0]['case_visibility']='source_reference'
    assert len(filter_visible_cases(deepcopy(state))['source_work_items'])==12
    state['contract_items'][0]['confirmation_ids'].append('hidden-case')
    assert len(filter_visible_cases(deepcopy(state))['source_work_items'])==11


from .test_source_sync import harness


def test_unchanged_snapshot_backfills_after_old_importer_version(harness,monkeypatch):
    from . import source_sync,source_work_items
    from .test_source_sync import snapshot
    h=harness;records,tables=fixture()
    h.service.fetcher=lambda _:dict(snapshot(h.clock[0],records),tables=tables)
    with monkeypatch.context() as old:
        old.setattr(source_sync,'SOURCE_PROJECTION_VERSION','sources-v1-20261007')
        old.setattr(source_work_items,'update_work_items',lambda *args:None)
        h.service.sync(h.wid,None,skip_unchanged=True)
    assert h.read()[0]['source_work_items']==[]
    h.clock[0]='2026-09-27T10:01:00+08:00'
    h.service.sync(h.wid,None,skip_unchanged=True)
    assert len(h.read()[0]['source_work_items'])==12
