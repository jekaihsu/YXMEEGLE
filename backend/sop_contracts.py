"""Versioned source evidence and approved additive SOP tasks.

Source conditions are data, never executable expressions. Unknown applicability
does not become false, mandatory, or a successful completion.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

VERSION='sop-contracts-20260930.1'
CATALOG_VERSION='sop-contracts-20260929.1'
DISABLED_NODES=frozenset({'state_52','state_58'})
DEFAULTS={
 'pm':[
  ('client_contact_record','業主聯繫紀錄與佐證',['state_50'],'always','PM','client_contact'),
  ('indoor_progress_review','各組內業進度追蹤',['state_46'],'always','PM','daily_progress'),
 ],
 'sales':[
  ('subcontract_scope_review','下包需求及工作範圍確認',['state_29'],'always','PM 彙整；該組主管確認',None),
  ('subcontract_quote_collection','下包報價收件與範圍核對',['state_35'],'subcontract','行政收件；PM＋該組主管確認',None),
 ],
 'field':[
  ('subcontract_dispatch','下包出工安排與追蹤',['state_82'],'subcontract_field','對應作業組；PM協調',None),
 ],
 'control':[
  ('subcontract_dispatch','下包出工安排與追蹤',['state_82'],'subcontract_control','對應作業組；PM協調',None),
 ],
 'mapping':[
  ('subcontract_dispatch','下包出工安排與追蹤',['state_82'],'subcontract_mapping','對應作業組；PM協調',None),
 ],
 'report':[
  ('subcontract_dispatch','下包出工安排與追蹤',['state_82'],'subcontract_report','對應作業組；PM協調',None),
 ],
 'pricing':[
  ('subcontract_delivery_review','下包成果報告與組別驗收',['state_61'],'subcontract','對應組驗收；行政引用',None),
 ],
}

@lru_cache(maxsize=1)
def _catalog():
    value=json.loads(Path(__file__).with_name('sop_source_contracts.json').read_text(encoding='utf-8'))
    assert value['version']==CATALOG_VERSION
    return value

def catalog():
    return deepcopy(_catalog())

def ensure_draft_candidate(ws,candidate):
    """Make a new contract available without replacing the company's release."""
    if any(t.get('id')==candidate['id']for t in ws['sop_templates']):return False
    from .workflow import event,now
    value=deepcopy(candidate)
    value.update(status='draft',version=max((t.get('version',0)for t in ws['sop_templates']),default=0)+1,
      created_by='system:sop-contracts',created_at=now(),generated_candidate=True)
    ws['sop_templates'].append(value)
    ws.setdefault('events',[])
    event(ws,{'id':'system:sop-contracts'},'sop_candidate_available',message='新增來源契約版 SOP 草稿候選；現行已發布範本與案件歷史不變')
    return True

def source_contracts(node_ids,template_id=334662):
    template=next(t for t in _catalog()['templates']if t['id']==template_id)
    return [deepcopy(n)|{'template_id':template_id,'template_version':template['version']}
            for n in template['nodes']if n['state_key']in node_ids]

def enrich_definition(definition):
    from .workflow import require
    require(isinstance(definition,dict),'SOP 任務定義格式錯誤',422)
    result=deepcopy(definition)
    ids=result.get('source_node_ids',[])
    refs=result.get('source_contract_refs',[])
    require(isinstance(ids,list)and all(isinstance(k,str)for k in ids),'SOP 來源節點格式錯誤',422)
    require(isinstance(refs,list)and all(isinstance(r,dict)and type(r.get('template_id'))is int
      and isinstance(r.get('node_key'),str)for r in refs),'SOP 來源契約格式錯誤',422)
    require(type(result.get('required',True))is bool and type(result.get('disabled',False))is bool,'SOP 必填／停用設定須為布林值',422)
    require(isinstance(result.get('applicability','always'),str),'SOP 適用條件格式錯誤',422)
    # Build lightweight references directly. Copying every form/condition tree
    # on each workspace upgrade makes a read-only projection unnecessarily slow.
    source_template=next(t for t in _catalog()['templates']if t['id']==334662)
    source=[n for n in source_template['nodes']if n['state_key']in ids]
    generated=[{'template_id':334662,'version':source_template['version'],
      'node_key':n['state_key'],'task_ids':[t['contract_id']for t in n['tasks']]}for n in source]
    refs=deepcopy(refs)
    for ref in generated:
        if ref not in refs:refs.append(ref)
    result['source_contract_refs']=refs
    # Original required rules stay in the source catalog. Only an explicit
    # approved local requirement determines runtime `required`.
    result.setdefault('required',True)
    result.setdefault('applicability','always')
    result['contract_version']=VERSION
    if any(n['disabled']for n in source) or any(r.get('template_id')==334662 and r.get('node_key')in DISABLED_NODES for r in refs):
        result.update(disabled=True,required=False,disabled_reason='業主核定停用考評與薪資相關計算')
    return result

def approved_definitions(node_key):
    return [enrich_definition({'key':f'approved:{node_key}:{key}','title':title,'source_node_ids':sources,
      'source_scope':'approved-D4-D5','required':recurring is None,'applicability':condition,
      'completion_scope':'single_occurrence_record' if recurring else 'node_work',
      'responsibility_note':role,'recurring_kind':recurring})
      for key,title,sources,condition,role,recurring in DEFAULTS.get(node_key,[])]

def applicability(project,definition):
    rule=definition.get('applicability','always')
    if rule=='always':return True
    if rule.startswith('subcontract_') and applicability(project,{'applicability':'subcontract'}) is False:return False
    # Deliberately requires a versioned, attributed explicit decision. Imported
    # display labels, first-seen dates or an unverified boolean are not authority.
    decision=project.get('sop_applicability',{}).get(rule)
    if not isinstance(decision,dict):return None
    if (decision.get('contract_version')!=VERSION or not decision.get('decided_by')
        or not decision.get('reason') or type(decision.get('applies'))is not bool):return None
    return decision['applies']

def disabled_task(task):
    refs=task.get('source_contract_refs')or[]
    if task.get('sop_disabled'):return True
    return any(ref.get('template_id')==334662 and ref.get('node_key')in DISABLED_NODES for ref in refs)

def execution_reasons(project,node,task):
    if disabled_task(task):return ['業主已停用此考評與薪資相關工作']
    if task.get('sop_applicability')not in (None,'always'):
        condition=applicability(project,{'applicability':task['sop_applicability']})
        if condition is None:return ['SOP 適用條件尚未核定']
        if condition is False:return ['SOP 已核定不適用；保留既有紀錄']
    if task.get('sop_task_key') == 'quote_provide' and task.get('sop_contract_version') == VERSION:
        condition=applicability(project,{'applicability':'subcontract'})
        if condition is None:return ['提出報價前需 PM 彙整下包需求並由對應主管確認']
        if condition:
            collection=[t for n in project['nodes'] for t in n['tasks']
                        if t.get('sop_task_key')=='approved:sales:subcontract_quote_collection']
            if not collection or any(t.get('status')!='completed' for t in collection):
                return ['提出報價前需完成下包報價收件與範圍核對']
    return []

def completion_reasons(project,node):
    if node.get('sop_applicability_pending'):
        return ['SOP 適用條件待核定並重新套用；不可視為已完成或不適用']
    if any(disabled_task(t)and t.get('required')and t.get('status')not in ('completed','superseded')for t in node.get('tasks',[])):
        return ['此版本仍含已停用的必做考評工作，請套用核定替代版本']
    return []

def decorate_task(task,definition,version):
    """New tasks only; an existing task's completion/owner is never rewritten."""
    task.update(sop_task_key=definition['key'],sop_definition_version=version,
      source_contract_refs=deepcopy(definition.get('source_contract_refs',[])),
      sop_contract_version=VERSION,sop_applicability=definition.get('applicability','always'),
      sop_disabled=bool(definition.get('disabled')),required=bool(definition.get('required',True)))
    task['responsibility_note']=definition.get('responsibility_note','')
    task['recurring_kind']=definition.get('recurring_kind')
    task['completion_scope']=definition.get('completion_scope','node_work')
    if task['recurring_kind']:
        task['description']='本項只保留本次追蹤紀錄；不阻擋開工前派工，不代表週期工作永久完成。後續每輪仍由追蹤與檢討管理。'
    if task['sop_disabled']:task.update(status='paused',required=False)
    return task

def merge_project_tasks(ws,project,template,actor):
    """Add approved tasks atomically; keep old results, assignments and reviews.

    Caller remains responsible for SOP approval and the existing node requirement
    migration. This helper cannot upgrade pending/Meegle formal cases.
    """
    from .case_cutover import require_execution
    from .workflow import require,event,uid,now
    from .sources import new_task
    from .workflow_rules import inherit_new_task
    require_execution(ws,project)
    from .business_policy import can_business_override
    require(actor.get('active',True)and(can_business_override(actor) or actor.get('id') in (project.get('pm_id'),project.get('supervisor_id'))),
      '需案件 PM、指定主管或明確授權備用人員核定 SOP 套用',403)
    staged=deepcopy(project);added=[];pending=[];metadata_changes=[]
    for node in staged['nodes']:
        definition=next((d for d in template['nodes']if d['key']==node['key']),None)
        require(definition is not None,'SOP 缺少既有節點定義',422)
        if node['status']=='completed':continue
        unresolved=[]
        definitions=definition.get('task_definitions')
        if not definitions:
            # Keep pre-contract templates usable without title collisions.
            definitions=[{'key':f'legacy:{node["key"]}:{i}','title':title}for i,title in enumerate(definition.get('tasks',[]))]
        for original in definitions:
            item=enrich_definition(original)
            require(bool(item.get('key')),'SOP 任務缺少穩定識別',422)
            applies=applicability(staged,item)
            if applies is None and not item.get('disabled'):
                unresolved.append({'key':item['key'],'rule':item['applicability'],'title':item['title'],'contract_version':VERSION})
            matches=[t for t in node['tasks']if t.get('sop_task_key')==item['key']]
            require(len(matches)<=1,'SOP 任務穩定識別重複',409)
            legacy=[t for t in node['tasks']if not t.get('sop_task_key') and t['title']==item['title'] and not t.get('source_identity')]
            if not matches:require(len(legacy)<=1,'舊 SOP 同名任務不唯一，請先核對原始識別再套用',409)
            existing=(matches or legacy)
            if existing:
                task=existing[0]
                if task.get('status')=='completed':continue
                changes={'sop_task_key':item['key'],'source_contract_refs':deepcopy(item.get('source_contract_refs',[])),
                  'sop_definition_version':template['id'],'sop_contract_version':VERSION,
                  'responsibility_note':item.get('responsibility_note',''),
                  'recurring_kind':item.get('recurring_kind'),
                  'completion_scope':item.get('completion_scope','node_work'),
                  'sop_applicability':item['applicability'],'sop_disabled':bool(item.get('disabled')),
                  'required':False if applies is False or item.get('disabled')else bool(item.get('required',True))}
                changes={k:v for k,v in changes.items()if task.get(k)!=v}
                if changes:
                    task.setdefault('sop_contract_history',[]).append({'from_version':task.get('sop_definition_version'),
                      'to_version':template['id'],'at':now(),'actor_id':actor['id'],
                      'before':{k:deepcopy(task.get(k))for k in changes},'after':deepcopy(changes)})
                    task.update(changes);metadata_changes.append(task['id'])
                continue
            if item.get('disabled'):continue
            if applies is None:continue
            if not applies:continue
            task=decorate_task(new_task(uid(),item['title'],None),item,template['id'])
            node['tasks'].append(task);added.append((node['id'],task['id']))
        node['sop_applicability_pending']=unresolved
        pending.extend(unresolved)
    # Commit only after the complete project validates. Assignment/audit follow
    # on the caller's transaction and only affect newly-added tasks.
    for node in project['nodes']:
        saved=next(n for n in staged['nodes']if n['id']==node['id'])
        if node['status']=='completed':continue
        old_tasks={t['id']:t for t in node['tasks']}
        committed=[]
        for task in saved['tasks']:
            existing=old_tasks.get(task['id'])
            if existing is not None:
                existing.clear();existing.update(task);committed.append(existing)
            else:committed.append(task)
        node['tasks'][:]=committed
        node['sop_applicability_pending']=saved['sop_applicability_pending']
    for nid,tid in added:
        node=next(n for n in project['nodes']if n['id']==nid)
        task=next(t for t in node['tasks']if t['id']==tid)
        inherit_new_task(ws,project,node,task,actor)
    if added or pending or metadata_changes:
        event(ws,actor,'sop_contract_merge',project['id'],message=f'新增 {len(added)} 項核定工作；{len(metadata_changes)} 項契約版本異動；{len(pending)} 項適用條件待核對；既有成果與指派保留')
    return {'added':[tid for _,tid in added],'pending':deepcopy(pending)}
