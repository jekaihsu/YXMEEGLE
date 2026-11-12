"""Prepared normalized deltas match full saves, including indexes and event history."""
from copy import deepcopy
import random

from sqlalchemy import select

from . import storage, index_tables
from .models import BusinessRow, WorkspaceRow
from .perf_fixture import build_scaled_workspace
from .test_index_maintenance import make, commit, mutate


def dump(sessions):
    with sessions() as db:
        return sorted((r.kind,r.entity_id,r.parent_id,r.ordinal,r.data) for r in db.scalars(select(BusinessRow)))


def test_prepared_deltas_match_full_save_for_add_delete_move_and_reorder(tmp_path):
    (tmp_path/'full').mkdir(); (tmp_path/'prepared').mkdir()
    engine,full=make(tmp_path/'full',True)
    other,prepared=make(tmp_path/'prepared',True)
    try:
        for sessions in (full,prepared): commit(sessions,build_scaled_workspace(4))
        rng=random.Random(411)
        for serial in range(24):
            with full() as db: state=storage.load(db,BusinessRow,db.get(WorkspaceRow,'w'))
            mutate(state,rng,serial)
            # Change template and root-level skip scope too, beyond business rows.
            if serial==3: state['sop_templates']=[{'id':'new-template','name':'new template'}]
            if serial==5: state['node_skip_requests']=[{'id':'skip','project_id':state['projects'][0]['id'],'status':'draft'}]
            with prepared() as db:
                row=db.get(WorkspaceRow,'w'); existing={}
                storage.load(db,BusinessRow,row,row_snapshot=existing)
                after=deepcopy(state)
                plan=storage.prepare_save(BusinessRow,'w',after,existing,row.data,indexed=True)
            # A sync event is appended only once the transaction has begun.
            after['events'].insert(0,{'id':f'event-{serial}','action':'sync'})
            state['events']=deepcopy(after['events'])
            commit(full,state)
            with prepared.begin() as db:
                row=db.get(WorkspaceRow,'w'); after['version']=row.version+1
                row.data=storage.save_prepared(db,BusinessRow,'w',after,plan); row.version=after['version']
            assert dump(full)==dump(prepared)
            with prepared() as db:
                row=db.get(WorkspaceRow,'w'); saved=storage.load(db,BusinessRow,row)
                assert index_tables.reconcile(db,BusinessRow,'w',saved)['healthy']
    finally:
        engine.dispose(); other.dispose()
