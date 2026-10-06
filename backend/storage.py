"""Normalized workspace persistence with a reversible legacy migration.

Workspace metadata and append-only migration archives stay in workspaces.data;
business collections are rows with indexed workspace, kind, parent and ordering.
All materialization happens within the caller's version-checked transaction.
"""
from copy import deepcopy
from sqlalchemy import Column, String, Integer, JSON, ForeignKey, UniqueConstraint, select, delete

COLLECTIONS=('users','projects','approvals','events','sop_templates','delegations','jobs','recurring','input_mappings','input_revisions','cost_allocations','daily_unmatched','daily_reviews','handover_requests','sop_requests','training_plans','capability_catalog','capability_awards','learning_standards','work_schedules','approved_leave_delegations','capability_bindings','learning_mappings','financial_requests','source_quotes','source_confirmations','contract_items')
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

def save(db,model,wid,state):
    """Replace only changed entity rows; preserve one atomic workspace revision."""
    root=deepcopy(state); desired={}
    archive=root.pop('migration_archive',None)
    if archive is not None: root['migration_archive_ref']='original'
    def add(kind,record,parent='',ordinal=0):
        item=deepcopy(record); ident=str(item.get('id') or f'{parent}:{ordinal}')
        if (kind,ident) in desired: raise ValueError(f'duplicate record id in storage.save: kind={kind} id={ident}')
        desired[(kind,ident)]={'parent_id':parent,'ordinal':ordinal,'data':item}
        return item
    for collection in COLLECTIONS:
        for i,record in enumerate(root.pop(collection,[])):
            row=add(collection,record,ordinal=i)
            if collection=='projects':
                pid=record['id']
                for j,node in enumerate(row.pop('nodes',[])):
                    nr=add('nodes',node,pid,j)
                    for k,task in enumerate(nr.pop('tasks',[])): add('tasks',task,node['id'],k)
                    for k,review in enumerate(nr.pop('review_cycles',[])): add('review_cycles',review,node['id'],k)
                for child in PROJECT_CHILDREN:
                    for j,value in enumerate(row.pop(child,[])): add('project_'+child,value,pid,j)
    if archive is not None and db.get(model,(wid,'migration_archive','original')) is None:
        db.add(model(workspace_id=wid,kind='migration_archive',entity_id='original',parent_id='',ordinal=0,data=deepcopy(archive)))
    existing={(r.kind,r.entity_id):r for r in db.scalars(select(model).where(model.workspace_id==wid,model.kind!='migration_archive'))}
    def project_of(key,value):
        kind,ident=key
        if kind=='projects': return ident
        parent=value['parent_id']
        if kind=='nodes' or kind.startswith('project_'): return parent
        if kind in ('tasks','review_cycles'):
            node=desired.get(('nodes',parent)); old=existing.get(('nodes',parent))
            return node['parent_id'] if node else old.parent_id if old else None
        if kind in {'approvals','sop_requests','financial_requests','delegations','recurring',
                    'input_mappings','input_revisions','cost_allocations','daily_reviews','handover_requests',
                    'source_quotes','source_confirmations','contract_items'}:
            return value['data'].get('project_id') or value['data'].get('linked_project_id')
        return None
    changed_projects=set()
    for key,value in desired.items():
        old=existing.get(key)
        left={k:v for k,v in old.data.items() if k!='concurrency_version'} if old else None
        right={k:v for k,v in value['data'].items() if k!='concurrency_version'}
        if left!=right:
            pid=project_of(key,value)
            if pid: changed_projects.add(pid)
            if old:
                previous=project_of(key,{'parent_id':old.parent_id,'data':old.data})
                if previous:changed_projects.add(previous)
    for key,old in existing.items():
        if key not in desired:
            pid=project_of(key,{'parent_id':old.parent_id,'data':old.data})
            if pid: changed_projects.add(pid)
    # Root-level skip requests also govern completion and approval scope.
    workspace_table=model.metadata.tables['workspaces']
    previous_root=db.scalar(select(workspace_table.c.data).where(workspace_table.c.id==wid)) or {}
    old_skips={item['id']:item for item in previous_root.get('node_skip_requests',[])}
    new_skips={item['id']:item for item in root.get('node_skip_requests',[])}
    for ident in old_skips.keys() | new_skips.keys():
        old,new=old_skips.get(ident),new_skips.get(ident)
        if old!=new:
            changed_projects.update(item['project_id'] for item in (old,new) if item and item.get('project_id'))
    if any(key[0]=='sop_templates' and (key not in existing or existing[key].data!=value['data']) for key,value in desired.items()) or any(key[0]=='sop_templates' and key not in desired for key in existing):
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
    for key,value in desired.items():
        old=existing.pop(key,None)
        if old:
            if key[0]=='events': continue
            if old.data!=value['data'] or old.parent_id!=value['parent_id'] or old.ordinal!=value['ordinal']:
                old.data=value['data']; old.parent_id=value['parent_id']; old.ordinal=value['ordinal']
        else: db.add(model(workspace_id=wid,kind=key[0],entity_id=key[1],**value))
    for row in existing.values():
        if row.kind!='events': db.delete(row)
    root['storage_schema']=2
    return root

def load(db,model,row):
    if row.data.get('storage_schema')!=2: return deepcopy(row.data)
    result=deepcopy(row.data); records={}
    for r in db.scalars(select(model).where(model.workspace_id==row.id,model.kind!='migration_archive').order_by(model.ordinal)):
        records.setdefault((r.kind,r.parent_id),[]).append(deepcopy(r.data))
    for collection in COLLECTIONS: result[collection]=records.get((collection,''),result.get(collection,[]))
    for p in result['projects']:
        p['nodes']=records.get(('nodes',p['id']),[])
        for n in p['nodes']:
            n['tasks']=records.get(('tasks',n['id']),[]); n['review_cycles']=records.get(('review_cycles',n['id']),[])
        for child in PROJECT_CHILDREN: p[child]=records.get(('project_'+child,p['id']),[])
    return result
