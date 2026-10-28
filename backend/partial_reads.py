"""Selected workspace reads, loaded separately from backup persistence helpers."""
import json
from copy import deepcopy

from sqlalchemy import Text, cast, select

from .storage import COLLECTIONS, PROJECT_CHILDREN, READ_PROJECT_LINKED


def load_partial(db,model,row,*,collections=(),project_ids=None,project_children=(),filter_project_rows=False,project_details=True,case_sources=False):
    """Read selected collections and project trees; never pass this to save.

    Project IDs also select their headers, nodes, tasks and review cycles.
    Without IDs, project headers have empty nested lists. Other project lists
    are loaded only when explicitly named in project_children. filter_project_rows
    is read-only opt-in: scoped writes need complete shared collections for diffs.
    project_details=False reads project headers without nodes or child lists.
    case_sources keeps only navigation/progress inputs and source identity/code metadata.
    """
    collections=tuple(collections)
    project_children=tuple(project_children)
    project_ids=None if project_ids is None else tuple(project_ids)
    if set(collections)-set(COLLECTIONS): raise ValueError('unknown workspace collection')
    if set(project_children)-set(PROJECT_CHILDREN): raise ValueError('unknown project child')
    kinds=set(collections)
    if project_ids is not None: kinds.add('projects')
    result={key:deepcopy(value) for key,value in row.data.items() if key not in COLLECTIONS}
    for collection in COLLECTIONS: result[collection]=[]
    if row.data.get('storage_schema')!=2:
        for collection in kinds:
            values=row.data.get(collection,[])
            if filter_project_rows and project_ids is not None and collection in READ_PROJECT_LINKED:
                values=[item for item in values if item.get('project_id') is None or item.get('project_id') in project_ids]
            result[collection]=deepcopy(values)
        if project_ids is not None:
            result['projects']=[p for p in result['projects'] if p['id'] in project_ids]
        for p in result['projects']:
            if project_ids is None or not project_details: p['nodes']=[]
            for child in PROJECT_CHILDREN:
                if project_ids is None or not project_details or child not in project_children: p[child]=[]
    else:
        if case_sources:
            from .case_source_reads import case_source_data
        def fetch(selected,as_text=False,**filters):
            dialect=db.get_bind().dialect.name
            compact=case_sources and set(selected)<=set(('source_quotes','source_confirmations','contract_items')) and dialect in ('sqlite','postgresql')
            value=case_source_data(model,project_ids or (),dialect) if compact else model.data
            query=select(model.kind,model.parent_id,cast(value,Text) if as_text else value).where(model.workspace_id==row.id,model.kind.in_(selected))
            for column,values in filters.items(): query=query.where(getattr(model,column).in_(values))
            if filter_project_rows and project_ids is not None and set(selected) & READ_PROJECT_LINKED:
                # Mixed top-level kinds: retain shared policy rows and legacy globals.
                linked=model.data['project_id'].as_string()
                query=query.where((~model.kind.in_(READ_PROJECT_LINKED)) | linked.is_(None) | linked.in_(project_ids))
            rows=db.execute(query.order_by(model.ordinal))
            return ((kind,parent,json.loads(data)) for kind,parent,data in rows) if compact and not as_text else rows
        top=kinds-{'projects','source_work_items'}
        from . import shared_reads
        shared=top&shared_reads.KINDS if not db.info.get('shared_reads_wids') else frozenset()
        if top-shared:
            for kind,parent,data in fetch(top-shared,parent_id=('',)): result[kind].append(data)
        if shared:
            scope=tuple(project_ids) if filter_project_rows and project_ids is not None else None
            key=(row.id,getattr(row,'version',None),tuple(sorted(shared)),scope)
            if case_sources: key+=('case_sources',)
            rows=shared_reads.rows(key,lambda:[(kind,text) for kind,parent,text in fetch(shared,as_text=True,parent_id=('',))])
            for kind,text in rows: result[kind].append(json.loads(text))
        if 'source_work_items' in kinds:
            query=select(model.data).where(model.workspace_id==row.id,model.kind=='source_work_items')
            if project_ids is not None:
                from .source_work_items import MAX_ROWS
                query=query.where(model.data['project_id'].as_string().in_(project_ids)).limit(MAX_ROWS+1)
            result['source_work_items']=list(db.scalars(query.order_by(model.ordinal)))
            if project_ids is not None and len(result['source_work_items'])>MAX_ROWS:
                for pid in project_ids:
                    result.setdefault('source_work_items_status',{}).setdefault(pid,{'partial':True})['truncated']=True
        if 'projects' in kinds and project_ids != ():
            filters={'parent_id':('',)}
            if project_ids is not None: filters['entity_id']=project_ids
            result['projects']=[data for kind,parent,data in fetch(('projects',),**filters)]
        records={}
        selected_ids=[p['id'] for p in result['projects']] if project_ids is not None and project_details else []
        if selected_ids:
            nested=('nodes',)+tuple('project_'+child for child in project_children)
            for kind,parent,data in fetch(nested,parent_id=selected_ids):
                records.setdefault((kind,parent),[]).append(data)
            node_ids=[n['id'] for pid in selected_ids for n in records.get(('nodes',pid),[])]
            if node_ids:
                for kind,parent,data in fetch(('tasks','review_cycles'),parent_id=node_ids):
                    records.setdefault((kind,parent),[]).append(data)
        for p in result['projects']:
            p['nodes']=records.get(('nodes',p['id']),[])
            for n in p['nodes']:
                n['tasks']=records.get(('tasks',n['id']),[])
                n['review_cycles']=records.get(('review_cycles',n['id']),[])
            for child in PROJECT_CHILDREN: p[child]=records.get(('project_'+child,p['id']),[])
    result['_partial']={'collections':list(collections),'project_ids':None if project_ids is None else list(project_ids),'project_children':list(project_children)}
    return result
