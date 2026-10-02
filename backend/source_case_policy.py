"""Authoritative Lark source visibility, separate from execution authority.

The current policy includes all verified V4/quotation cases, including closed
ones. Legacy cutover helpers remain only for interpreting prior decisions.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from .workflow import require, now, event

CASE_KINDS = {'confirmation','quote_confirmation','quote'}
CODE_FIELDS = ('工程確認單編號','工程編號','報價編號')
SOURCE_REFERENCE_POLICY = 'all-authorized-lark-cases-20260930'


def apply_source_reference_policy(ws,snapshot,actor):
    """Display verified source cases without granting execution authority.

    Called only after the service has verified the complete authorized snapshot.
    Missing source rows retain their prior reference/history; absence is handled
    by the importer, never by deleting local work or revoking its visibility.
    """
    records=snapshot['records']
    current={identity(r) for r in records if r.get('kind') in CASE_KINDS
             and all(r.get(k) for k in ('base_token','table_id','record_id'))}
    changed=[]
    for project in ws.get('projects',[]):
        if identity(project.get('source_identity') or {}) not in current:continue
        if project.get('case_visibility') not in ('new_case','source_reference'):
            project.setdefault('case_visibility_history',[]).append({
                'from':project.get('case_visibility'),'at':now(),'reason':SOURCE_REFERENCE_POLICY})
            project['case_visibility']='source_reference'
            changed.append(project['id'])
        project.setdefault('execution_system','pending')
    previous=ws.get('source_case_policy_revision')
    ws['source_case_policy_revision']=SOURCE_REFERENCE_POLICY
    ws['source_visible_record_ids']=sorted(identity(r) for r in records)
    if previous!=SOURCE_REFERENCE_POLICY or changed:
        event(ws,actor,'source_reference_policy_applied',message=f'顯示全部已核實 Lark 來源案件（含已結案）；本次新增可見 {len(changed)} 案，未授予執行權限')


def identity(row):
    return '|'.join(str(row.get(k,'')) for k in ('base_token','table_id','record_id'))


def codes(row):
    from .sources import normalized_case
    return {normalized_case(row.get('fields',{}).get(k)) for k in CODE_FIELDS} - {''}


def _created_at(row):
    value = row.get('created_time')
    try:
        if type(value) in (int,float):
            return datetime.fromtimestamp(value/1000 if value > 100000000000 else value,timezone.utc)
        if isinstance(value,str):
            if value.isdigit():return _created_at({'created_time':int(value)})
            stamp = datetime.fromisoformat(value.replace('Z','+00:00'))
            return stamp if stamp.tzinfo else None
    except (ValueError,TypeError,OverflowError,OSError):pass
    return None


def _snapshot_tables(snapshot):
    return sorted((str(t.get('base_token','')),str(t.get('table_id',''))) for t in snapshot.get('tables',[]))


def establish_baseline(ws, actor, snapshot, *, expected_sync_revision, reason):
    require(actor.get('active',True) and actor.get('role')=='manager','需公司管理員核定來源基準',403)
    require(ws.get('environment')=='production','切換基準只適用正式工作區',409)
    require(ws.get('source_case_policy_revision')!=SOURCE_REFERENCE_POLICY,
            '已採全部 Lark 來源案件顯示規則，不可再套用舊的新案切換基準',409)
    require(not ws.get('source_case_baseline'),'來源基準已核定，不可重新建立將新案變成舊案',409)
    require(isinstance(reason,str) and 1<=len(reason.strip())<=1000,'請填切換核定原因',422)
    require(expected_sync_revision==ws.get('source_status',{}).get('sync_revision'),'來源快照已更新，請重新核對',409)
    require(isinstance(snapshot,dict) and snapshot.get('status')=='ready' and snapshot.get('records') is not None
            and snapshot.get('tables') and all(t.get('status')=='ready' for t in snapshot['tables']),
            '必須先完成全來源快照；部分資料不可作為新舊案基準',409)
    require(snapshot.get('last_sync')==ws.get('source_status',{}).get('last_sync'),'快照與成功同步版本不符',409)
    records=snapshot['records']
    ids=sorted({identity(r) for r in records})
    require(len(ids)==len(records) and all(all(r.get(k) for k in ('base_token','table_id','record_id')) for r in records),
            '來源識別重複或不完整',409)
    old_codes=set().union(*(codes(r) for r in records if r.get('kind') in CASE_KINDS)) if records else set()
    for project in ws.get('projects',[]):
        old_codes.update(str(x) for x in [project.get('code'),*project.get('code_history',[])] if x)
    stamp=now()
    baseline={'version':1,'cutover_at':stamp,'approved_by':actor['id'],'reason':reason.strip(),
              'sync_revision':expected_sync_revision,'snapshot_at':snapshot['last_sync'],
              'source_tables':_snapshot_tables(snapshot),'record_ids':ids,'case_codes':sorted(old_codes),
              'snapshot_hash':hashlib.sha256(json.dumps(records,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    ws['source_case_baseline']=baseline
    ws['source_visible_record_ids']=[]
    for project in ws.get('projects',[]):_exclude(project,stamp,'present_at_cutover')
    event(ws,actor,'source_case_baseline_established',message=f'核定新舊案基準；{len(ids)} 筆既有來源僅留伺服器歷史，不進入案件工作台')
    return baseline_summary(ws)


def _exclude(project,stamp,reason):
    project.setdefault('case_visibility_history',[])
    if project.get('case_visibility')!='excluded_history':
        project['case_visibility_history'].append({'from':project.get('case_visibility'),
            'previous_execution_system':project.get('execution_system'),'at':stamp,'reason':reason})
    project['case_visibility']='excluded_history'
    project['execution_system']='meegle'


def baseline_summary(ws):
    if ws.get('source_case_policy_revision')==SOURCE_REFERENCE_POLICY:
        return {'status':'active','policy_revision':SOURCE_REFERENCE_POLICY,
                'scope':'all_authorized_lark_cases','pending_count':0}
    baseline=ws.get('source_case_baseline')
    if not baseline:return {'status':'baseline_required','pending_count':len(ws.get('source_case_review',[]))}
    return {'status':'active','cutover_at':baseline['cutover_at'],'snapshot_at':baseline['snapshot_at'],
            'sync_revision':baseline['sync_revision'],'baseline_record_count':len(baseline['record_ids']),
            'pending_count':len(ws.get('source_case_review',[]))}


def partition_snapshot(ws,snapshot):
    """Return only proven new cases and their unambiguous dependent records."""
    from .sources import link_ids, normalized_case
    baseline=ws.get('source_case_baseline'); records=snapshot['records']
    # Until an explicit baseline exists, a full snapshot is evidence only.
    # Do not reclassify existing work or treat withheld rows as deletions.
    if not baseline:return [],set()
    for p in ws.get('projects',[]):
        if p.get('case_visibility')!='new_case':_exclude(p,now(),'historical_or_unclassified')
    require(_snapshot_tables(snapshot)==[tuple(t) for t in baseline['source_tables']],
            '來源表集合已變更，需核對切換基準；不自動判定新案',409)
    cutoff=datetime.fromisoformat(baseline['cutover_at'])
    old_ids=set(baseline['record_ids']);old_codes=set(baseline['case_codes'])
    old_refs={(parts[0],parts[2]) for item in old_ids if len(parts:=item.split('|'))==3}
    by_ref={(r['base_token'],r['record_id']):r for r in records}
    references={identity(r):set() for r in records}
    for r in records:
        for value in r.get('fields',{}).values():
            for ref in link_ids(value):
                target=by_ref.get((r['base_token'],ref))
                if target:references[identity(r)].add(identity(target))
    cases={identity(r):r for r in records if r.get('kind') in CASE_KINDS}
    old={key for key,r in cases.items() if key in old_ids or codes(r)&old_codes}
    for key,row in cases.items():
        if any((row['base_token'],ref) in old_refs for field in ('此案確認單','所屬案件')
               for ref in link_ids(row.get('fields',{}).get(field))):old.add(key)
    # A new quotation connected to an old case remains old, even if its own
    # record timestamp is new. Propagate both directions across case links.
    edges={key:{ref for ref in references[key] if ref in cases} for key in cases}
    by_code={}
    for key,row in cases.items():
        for code in codes(row):by_code.setdefault(code,set()).add(key)
    for key,row in cases.items():
        for code in codes(row):edges[key].update(by_code[code]-{key})
    for key,refs in list(edges.items()):
        for ref in refs:edges[ref].add(key)
    pending={};new=set()
    for key,row in cases.items():
        if key in old:continue
        created=_created_at(row)
        if created is None:
            pending[key]='missing_created_time'
        elif created<=cutoff:old.add(key)
        elif created>datetime.now(timezone.utc):pending[key]='future_created_time'
        else:new.add(key)
    changed=True
    while changed:
        changed=False
        for key,refs in edges.items():
            if key not in old and refs&old:old.add(key);changed=True
    new-=old
    for key in old:pending.pop(key,None)
    # Incomplete native case links cannot prove a new-case identity.
    for key,row in cases.items():
        if key not in new:continue
        raw_refs=set().union(*(set(link_ids(row.get('fields',{}).get(f))) for f in ('此案確認單','所屬案件')))
        if any((row['base_token'],ref) not in by_ref for ref in raw_refs):pending[key]='unresolved_native_case_link'
    changed=True
    while changed:
        changed=False
        for key in new-set(pending):
            if edges[key]&set(pending):pending[key]='related_case_identity_unverified';changed=True
    new-=set(pending)
    ws['source_case_review']=[{'identity':key,'code':sorted(codes(cases[key]))[:3],
        'reason':reason,'source_kind':cases[key]['kind']} for key,reason in sorted(pending.items())]
    selected=set(new)
    # Dependent contract/daily/cost records are admitted only when their graph
    # points exclusively to new data. Never surface unmatched old daily rows.
    allowed_codes=set().union(*(codes(cases[k]) for k in new)) if new else set()
    changed=True
    while changed:
        changed=False
        for r in records:
            key=identity(r)
            if key in selected or key in cases:continue
            refs=references[key]
            row_codes={normalized_case(r.get('fields',{}).get(f)) for f in ('所屬案件','工程編號','案件編號','案號')} - {''}
            if refs&old or row_codes&old_codes:continue
            if (refs&selected or row_codes&allowed_codes) and not (refs-selected):
                selected.add(key);changed=True
    return [r for r in records if identity(r) in selected],new


def mark_imported_new(ws,new_ids):
    for project in ws.get('projects',[]):
        if project.get('case_visibility')=='excluded_history':continue
        ident=project.get('source_identity') or {}
        if identity(ident) in new_ids:
            project['case_visibility']='new_case';project['execution_system']='workbench'
            project.setdefault('execution_assignment',{'basis':'verified_post_cutover_source','recorded_by':'system:cutover','recorded_at':now()})


def visible_project(ws,project):
    return ws.get('environment') in ('test','demo') or project.get('case_visibility') in ('new_case','source_reference')


def filter_visible_cases(state):
    if state.get('environment') in ('test','demo'):return state
    visible={p['id'] for p in state.get('projects',[]) if visible_project(state,p)}
    allowed_sources=set(state.get('source_visible_record_ids',[]))
    state['projects']=[p for p in state.get('projects',[]) if p['id'] in visible]
    for key,value in list(state.items()):
        if isinstance(value,list) and key not in ('users','projects','sop_templates','source_case_review'):
            state[key]=[item for item in value if not isinstance(item,dict) or not item.get('project_id') or item['project_id'] in visible]
    # Known business collections must have a visible owner. Orphan records are
    # never public merely because they lack a project_id.
    owned=('approvals','node_skip_requests','financial_requests','recurring','input_mappings',
           'input_revisions','cost_allocations','daily_reviews','handover_requests','sop_requests',
           'delegations','source_attachment_index')
    for key in owned:
        if key in state:
            state[key]=[row for row in state[key] if row.get('project_id') in visible
                        and all(part.get('project_id') in visible for part in row.get('parts',[]))]
    for key in ('source_quotes','source_confirmations','contract_items'):
        if key not in state:continue
        rows=[]
        for row in state[key]:
            related=set(row.get('project_ids',[]))|set(row.get('review_project_ids',[]))
            if row.get('project_id'):related.add(row['project_id'])
            if row.get('linked_project_id'):related.add(row['linked_project_id'])
            related.update(ref.get('project_id') for ref in row.get('task_refs',[]) if ref.get('project_id'))
            if identity(row.get('source_identity') or {}) not in allowed_sources or related-visible:continue
            if not related&visible:continue
            rows.append(row)
        state[key]=rows
    if 'jobs' in state:
        state['jobs']=[job for job in state['jobs']
            if ((job.get('payload') or {}).get('project_id') in visible
                or not (job.get('payload') or {}).get('project_id') and job.get('kind') not in
                    ('input','file','mention','confirmation','approval'))]
    state['events']=[item for item in state.get('events',[]) if item.get('project_id') in visible]
    state.pop('archived_projects',None)
    state.pop('migration_archive_ref',None)
    state['daily_unmatched']=[]
    state['source_identity_conflicts']=[]
    state['source_case_baseline_status']=baseline_summary(state)
    state.pop('source_case_baseline',None)
    state.pop('source_visible_record_ids',None)
    return state


def visible_source_snapshot(state,snapshot):
    """Public cache view uses durable admitted identities from the same sync."""
    if state.get('environment') in ('demo','test'):return snapshot
    allowed=set(state.get('source_visible_record_ids',[]))
    result=deepcopy(snapshot)
    result['records']=[r for r in result.get('records',[]) if identity(r) in allowed]
    for table in result.get('tables',[]):
        table['count']=sum(r.get('base_token')==table.get('base_token') and r.get('table_id')==table.get('table_id') for r in result['records'])
    result.pop('case_filter',None)
    result['message']='顯示已核實的 V4 與報價總表來源資料（含已結案）；來源顯示不代表可執行工作'
    return result
