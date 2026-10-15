"""Normalized workspace persistence with a reversible legacy migration.

Workspace metadata and append-only migration archives stay in workspaces.data;
business collections are rows with indexed workspace, kind, parent and ordering.
All materialization happens within the caller's version-checked transaction.
"""
from copy import deepcopy
from sqlalchemy import Column, String, Integer, JSON, ForeignKey, UniqueConstraint, select, delete, func

COLLECTIONS=('users','projects','approvals','events','sop_templates','delegations','jobs','recurring','input_mappings','input_revisions','cost_allocations','daily_unmatched','daily_reviews','handover_requests','sop_requests','training_plans','capability_catalog','capability_awards','learning_standards','work_schedules','approved_leave_delegations','capability_bindings','learning_mappings','financial_requests','source_quotes','source_confirmations','contract_items','source_work_items')
PROJECT_CHILDREN=('files','comments','daily_reports','evidence','finance_versions','payment_batches','confirmation_issues','delivery_batches','quote_reviews')

def models(base):
    class BusinessRow(base):
        __tablename__='business_records'
        workspace_id=Column(String(120),ForeignKey('workspaces.id'),primary_key=True)
        kind=Column(String(60),primary_key=True)
        entity_id=Column(String(160),primary_key=True)
        parent_id=Column(String(160),nullable=False,default='',index=True)
        ordinal=Column(Integer,nullable=False)
        data=Column(JSON,nullable=False)
    class PersonRow(base):
        __tablename__='company_people'
        organization_id=Column(String(120),primary_key=True)
        person_id=Column(String(120),primary_key=True)
        data=Column(JSON,nullable=False)
    return BusinessRow,PersonRow


class PartialUnavailable(Exception):
    """The stored state cannot be served by a partial write (legacy layout, pending upgrade); run the full path."""

class FootprintViolation(BaseException):
    """A partial write reached data outside the footprint it declared.

    BaseException on purpose: the mutation callbacks and index helpers contain broad
    `except Exception` clauses, and a swallowed violation would save a partial view.
    """

def _adder(desired,origin):
    def add(kind,record,parent='',ordinal=0,nested=()):
        # Nested lists become rows of their own, so they are copied there and not here.
        item={k:deepcopy(v) for k,v in record.items() if k not in nested}; ident=str(item.get('id') or f'{parent}:{ordinal}')
        if (kind,ident) in desired: raise ValueError(f'duplicate record id in {origin}: kind={kind} id={ident}')
        desired[(kind,ident)]={'parent_id':parent,'ordinal':ordinal,'data':item}
        return item
    return add

def _flatten_project(add,record,ordinal):
    pid=record['id']
    add('projects',record,ordinal=ordinal,nested=('nodes',)+PROJECT_CHILDREN)
    for j,node in enumerate(record.get('nodes',[])):
        add('nodes',node,pid,j,nested=('tasks','review_cycles'))
        for k,task in enumerate(node.get('tasks',[])): add('tasks',task,node['id'],k)
        for k,review in enumerate(node.get('review_cycles',[])): add('review_cycles',review,node['id'],k)
    for child in PROJECT_CHILDREN:
        for j,value in enumerate(record.get(child,[])): add('project_'+child,value,pid,j)

PROJECT_LINKED=frozenset({'approvals','sop_requests','financial_requests','delegations','recurring',
                          'input_mappings','input_revisions','cost_allocations','daily_reviews','handover_requests',
                          'source_quotes','source_confirmations','contract_items','source_work_items'})

def _project_resolver(desired,existing):
    def project_of(key,value):
        kind,ident=key
        if kind=='projects': return ident
        parent=value['parent_id']
        if kind=='nodes' or kind.startswith('project_'): return parent
        if kind in ('tasks','review_cycles'):
            node=desired.get(('nodes',parent)); old=existing.get(('nodes',parent))
            return node['parent_id'] if node else old.parent_id if old else None
        if kind in PROJECT_LINKED:
            return value['data'].get('project_id') or value['data'].get('linked_project_id')
        return None
    return project_of

def _changed_projects(desired,existing,project_of):
    changed=set()
    for key,value in desired.items():
        old=existing.get(key)
        left={k:v for k,v in old.data.items() if k!='concurrency_version'} if old else None
        right={k:v for k,v in value['data'].items() if k!='concurrency_version'}
        if left!=right:
            pid=project_of(key,value)
            if pid: changed.add(pid)
            if old:
                previous=project_of(key,{'parent_id':old.parent_id,'data':old.data})
                if previous: changed.add(previous)
    for key,old in existing.items():
        if key not in desired:
            pid=project_of(key,{'parent_id':old.parent_id,'data':old.data})
            if pid: changed.add(pid)
    return changed

def _changed_skip_projects(db,model,wid,root):
    """Root-level skip requests also govern completion and approval scope."""
    workspace_table=model.metadata.tables['workspaces']
    previous_root=db.scalar(select(workspace_table.c.data).where(workspace_table.c.id==wid)) or {}
    old_skips={item['id']:item for item in previous_root.get('node_skip_requests',[])}
    new_skips={item['id']:item for item in root.get('node_skip_requests',[])}
    changed=set()
    for ident in old_skips.keys() | new_skips.keys():
        old,new=old_skips.get(ident),new_skips.get(ident)
        if old!=new:
            changed.update(item['project_id'] for item in (old,new) if item and item.get('project_id'))
    return changed

def _templates_changed(desired,existing):
    return (any(key[0]=='sop_templates' and (key not in existing or existing[key].data!=value['data']) for key,value in desired.items())
            or any(key[0]=='sop_templates' and key not in desired for key in existing))

def save(db,model,wid,state):
    """Replace only changed entity rows; preserve one atomic workspace revision."""
    if '_partial' in state: raise ValueError('partial workspaces are read-only')
    root={k:deepcopy(v) for k,v in state.items() if k not in COLLECTIONS and k!='migration_archive'}; desired={}
    archive=state.get('migration_archive')
    if archive is not None: root['migration_archive_ref']='original'
    add=_adder(desired,'storage.save')
    for collection in COLLECTIONS:
        for i,record in enumerate(state.get(collection,[])):
            if collection=='projects': _flatten_project(add,record,i)
            else: add(collection,record,ordinal=i)
    if archive is not None and db.get(model,(wid,'migration_archive','original')) is None:
        db.add(model(workspace_id=wid,kind='migration_archive',entity_id='original',parent_id='',ordinal=0,data=deepcopy(archive)))
    existing={(r.kind,r.entity_id):r for r in db.scalars(select(model).where(model.workspace_id==wid,model.kind!='migration_archive'))}
    project_of=_project_resolver(desired,existing)
    changed_projects=_changed_projects(desired,existing,project_of)
    changed_projects|=_changed_skip_projects(db,model,wid,root)
    if _templates_changed(desired,existing):
        changed_projects.update(project['id'] for project in state.get('projects',[]))
    for project in state.get('projects',[]):
        old=existing.get(('projects',project['id']))
        revision=(old.data.get('concurrency_version',0) if old else 0)+(1 if project['id'] in changed_projects else 0)
        project['concurrency_version']=revision
        desired[('projects',project['id'])]['data']['concurrency_version']=revision
    # Event rows are immutable. Inserting an event at the head must not rewrite
    # every historical event's ordinal or allow a workspace update to erase it.
    event_ordinal=min((r.ordinal for (kind,_),r in existing.items() if kind=='events'),default=0)
    new_events=[key for key in desired if key[0]=='events' and key not in existing]
    for index,key in enumerate(new_events):
        desired[key]['ordinal']=event_ordinal-len(new_events)+index
    indexed=db.info.get('index_tables')
    dirty=set(changed_projects)
    if indexed:
        # Moves and reorders change index rows without changing entity data.
        for key,value in desired.items():
            old=existing.get(key)
            if old and key[0] in ('projects','nodes','tasks') and (old.parent_id!=value['parent_id'] or old.ordinal!=value['ordinal']):
                pid=project_of(key,value)
                if pid: dirty.add(pid)
    for key,value in desired.items():
        old=existing.pop(key,None)
        if old:
            if key[0]=='events': continue
            if old.data!=value['data'] or old.parent_id!=value['parent_id'] or old.ordinal!=value['ordinal']:
                old.data=value['data']; old.parent_id=value['parent_id']; old.ordinal=value['ordinal']
        else: db.add(model(workspace_id=wid,kind=key[0],entity_id=key[1],**value))
    for row in existing.values():
        if row.kind!='events': db.delete(row)
    if indexed:
        from . import index_tables  # lazy: storage must stay importable inside the isolated backup helper bundle
        index_tables.replace_projects(db,model,wid,state,dirty)
        index_tables.replace_counters(db,model,wid,state)
    root['storage_schema']=2
    return root

def save_collections(db,model,wid,state,collections):
    """Write only the named non-project collections of a load_partial state.

    Rows of every other kind are not read, copied or compared, so a write that
    changes a few people or events no longer pays for the whole workspace. Events
    stay insert-only and may be named without having been loaded.
    """
    collections=tuple(collections)
    partial=state.get('_partial')
    if (partial is None or 'projects' in collections or set(collections)-set(COLLECTIONS)
            or set(collections)-set(partial['collections'])-{'events'}):
        raise ValueError('save_collections needs a partial state that loaded every named non-project collection')
    root={k:deepcopy(v) for k,v in state.items() if k not in COLLECTIONS and k!='_partial'}
    desired={}
    for collection in collections:
        for i,record in enumerate(state.get(collection,[])):
            ident=str(record.get('id') or f':{i}')
            if (collection,ident) in desired: raise ValueError(f'duplicate record id in storage.save_collections: kind={collection} id={ident}')
            desired[(collection,ident)]={'parent_id':'','ordinal':i,'data':deepcopy(record)}
    stored=[c for c in collections if c!='events']
    existing={(r.kind,r.entity_id):r for r in db.scalars(select(model).where(model.workspace_id==wid,model.kind.in_(stored)))} if stored else {}
    if 'events' in collections:
        ids=[ident for kind,ident in desired if kind=='events']
        known=set()
        for i in range(0,len(ids),400):
            known.update(db.scalars(select(model.entity_id).where(model.workspace_id==wid,model.kind=='events',model.entity_id.in_(ids[i:i+400]))))
        fresh=[key for key in desired if key[0]=='events' and key[1] not in known]
        floor=db.scalar(select(func.min(model.ordinal)).where(model.workspace_id==wid,model.kind=='events')) or 0
        for index,key in enumerate(fresh):
            desired[key]['ordinal']=floor-len(fresh)+index
        for key in desired.keys()-set(fresh):
            if key[0]=='events': del desired[key]
    for key,value in desired.items():
        old=existing.pop(key,None)
        if old:
            if old.data!=value['data'] or old.parent_id!=value['parent_id'] or old.ordinal!=value['ordinal']:
                old.data=value['data']; old.parent_id=value['parent_id']; old.ordinal=value['ordinal']
        else: db.add(model(workspace_id=wid,kind=key[0],entity_id=key[1],**value))
    for row in existing.values(): db.delete(row)
    if db.info.get('index_tables'):
        from . import index_tables
        index_tables.advance_counters(db,model,wid,state['version']-1,state['version'])
    root['storage_schema']=2
    return root

def load_scoped(db,model,row,*,collections,project_ids):
    """The state a partial write runs on: whole named collections plus whole project trees.

    Returns the plain state (projects holds only the selected trees) and the full project
    id order, so a caller can show every other project as an untouchable placeholder.
    """
    collections=tuple(collections); project_ids=tuple(dict.fromkeys(project_ids))
    if row.data.get('storage_schema')!=2: raise PartialUnavailable('partial writes need normalized storage')
    if 'projects' in collections or 'events' in collections: raise ValueError('projects and events are never loaded as collections')
    state=load_partial(db,model,row,collections=collections,project_ids=project_ids,project_children=PROJECT_CHILDREN)
    order=list(db.scalars(select(model.entity_id).where(model.workspace_id==row.id,model.kind=='projects',model.parent_id=='').order_by(model.ordinal)))
    missing=set(project_ids)-{p['id'] for p in state['projects']}
    if missing: raise PartialUnavailable(f'unknown project in footprint: {sorted(missing)[0]}')
    return state,order

def _in_chunks(column,values,size=400):
    values=list(values)
    for i in range(0,len(values),size): yield column.in_(values[i:i+size])

def save_partial(db,model,wid,state,collections,project_ids,project_order,*,view=None):
    """Write the named collections and project trees of a load_scoped state.

    Produces the rows, project concurrency versions, event ordinals and index rows a full
    save of the same change would produce, without reading or comparing anything else.
    A change that reaches a project, template or root record outside the footprint raises
    FootprintViolation before any row is written, because a full save would have rewritten
    that project too and only the full path can do that.
    """
    collections=tuple(collections); project_ids=tuple(project_ids)
    partial=state.get('_partial')
    if (partial is None or 'projects' in collections or set(collections)-set(COLLECTIONS)
            or set(collections)-set(partial['collections'])-{'events'}):
        raise ValueError('save_partial needs a scoped state that loaded every named collection')
    loaded=[p['id'] for p in state['projects']]
    if sorted(loaded)!=sorted(project_ids): raise FootprintViolation('projects were added or removed by a partial write')
    root={k:deepcopy(v) for k,v in state.items() if k not in COLLECTIONS and k!='_partial'}
    if 'migration_archive' in root: raise ValueError('archives are written by the full save only')
    ordinals={pid:i for i,pid in enumerate(project_order)}
    desired={}; add=_adder(desired,'storage.save_partial')
    for collection in collections:
        records=state.get(collection,[])
        for i,record in enumerate(records.new() if hasattr(records,'new') else records): add(collection,record,ordinal=i)
    for project in state['projects']: _flatten_project(add,project,ordinals[project['id']])
    stored=[c for c in collections if c!='events']
    existing={}
    def pull(*clauses):
        for r in db.scalars(select(model).where(model.workspace_id==wid,*clauses)): existing[(r.kind,r.entity_id)]=r
    if stored: pull(model.kind.in_(stored))
    if project_ids:
        for part in _in_chunks(model.entity_id,project_ids): pull(model.kind=='projects',part)
        children=('nodes',)+tuple('project_'+c for c in PROJECT_CHILDREN)
        for part in _in_chunks(model.parent_id,project_ids): pull(model.kind.in_(children),part)
        node_ids=[ident for kind,ident in existing if kind=='nodes']
        for part in _in_chunks(model.parent_id,node_ids): pull(model.kind.in_(('tasks','review_cycles')),part)
    project_of=_project_resolver(desired,existing)
    changed_projects=_changed_projects(desired,existing,project_of)
    changed_projects|=_changed_skip_projects(db,model,wid,root)
    if 'sop_templates' in collections and _templates_changed(desired,existing):
        raise FootprintViolation('a template change rewrites every project')
    outside=changed_projects-set(project_ids)
    if outside: raise FootprintViolation(f'write changed project {sorted(outside)[0]} outside the footprint')
    for project in state['projects']:
        old=existing.get(('projects',project['id']))
        revision=(old.data.get('concurrency_version',0) if old else 0)+(1 if project['id'] in changed_projects else 0)
        project['concurrency_version']=revision
        desired[('projects',project['id'])]['data']['concurrency_version']=revision
    if 'events' in collections:
        ids=[ident for kind,ident in desired if kind=='events']
        known=set()
        for part in _in_chunks(model.entity_id,ids): known.update(db.scalars(select(model.entity_id).where(model.workspace_id==wid,model.kind=='events',part)))
        fresh=[key for key in desired if key[0]=='events' and key[1] not in known]
        floor=db.scalar(select(func.min(model.ordinal)).where(model.workspace_id==wid,model.kind=='events')) or 0
        for index,key in enumerate(fresh): desired[key]['ordinal']=floor-len(fresh)+index
        for key in desired.keys()-set(fresh):
            if key[0]=='events': del desired[key]
    indexed=db.info.get('index_tables')
    dirty=set(changed_projects)
    if indexed:
        for key,value in desired.items():
            old=existing.get(key)
            if old and key[0] in ('projects','nodes','tasks') and (old.parent_id!=value['parent_id'] or old.ordinal!=value['ordinal']):
                pid=project_of(key,value)
                if pid: dirty.add(pid)
        from . import index_tables
        before=index_tables.scoped_counters((r.kind,r.entity_id,r.parent_id,r.data) for r in existing.values())
        after=index_tables.scoped_counters((kind,ident,value['parent_id'],value['data']) for (kind,ident),value in desired.items() if kind!='events')
    for key,value in desired.items():
        old=existing.pop(key,None)
        if old:
            if old.data!=value['data'] or old.parent_id!=value['parent_id'] or old.ordinal!=value['ordinal']:
                old.data=value['data']; old.parent_id=value['parent_id']; old.ordinal=value['ordinal']
        else: db.add(model(workspace_id=wid,kind=key[0],entity_id=key[1],**value))
    for row in existing.values(): db.delete(row)
    if indexed:
        index_tables.replace_projects(db,model,wid,view if view is not None else state,dirty)
        index_tables.apply_counter_deltas(db,model,wid,state['version']-1,state['version'],before,after)
    root['storage_schema']=2
    return root

def load_partial(db,model,row,*,collections=(),project_ids=None,project_children=()):
    """Read selected collections and project trees; never pass this to save.

    Project IDs also select their headers, nodes, tasks and review cycles.
    Without IDs, project headers have empty nested lists. Other project lists
    are loaded only when explicitly named in project_children.
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
        for collection in kinds: result[collection]=deepcopy(row.data.get(collection,[]))
        if project_ids is not None:
            result['projects']=[p for p in result['projects'] if p['id'] in project_ids]
        for p in result['projects']:
            if project_ids is None: p['nodes']=[]
            for child in PROJECT_CHILDREN:
                if project_ids is None or child not in project_children: p[child]=[]
    else:
        def fetch(selected,**filters):
            query=select(model.kind,model.parent_id,model.data).where(model.workspace_id==row.id,model.kind.in_(selected))
            for column,values in filters.items(): query=query.where(getattr(model,column).in_(values))
            return db.execute(query.order_by(model.ordinal))
        top=kinds-{'projects','source_work_items'}
        if top:
            for kind,parent,data in fetch(top,parent_id=('',)): result[kind].append(data)
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
        selected_ids=[p['id'] for p in result['projects']] if project_ids is not None else []
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

def load(db,model,row):
    if row.data.get('storage_schema')!=2: return deepcopy(row.data)
    result=deepcopy(row.data); records={}
    # Column selection decodes fresh JSON without aliasing identity-map objects.
    for kind,parent,data in db.execute(select(model.kind,model.parent_id,model.data).where(model.workspace_id==row.id,model.kind!='migration_archive').order_by(model.ordinal)):
        records.setdefault((kind,parent),[]).append(data)
    for collection in COLLECTIONS: result[collection]=records.get((collection,''),result.get(collection,[]))
    for p in result['projects']:
        p['nodes']=records.get(('nodes',p['id']),[])
        for n in p['nodes']:
            n['tasks']=records.get(('tasks',n['id']),[]); n['review_cycles']=records.get(('review_cycles',n['id']),[])
        for child in PROJECT_CHILDREN: p[child]=records.get(('project_'+child,p['id']),[])
    return result
