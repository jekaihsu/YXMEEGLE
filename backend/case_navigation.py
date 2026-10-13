"""Native E1/E2 navigation over existing source entities; no inferred joins."""
from copy import deepcopy
from .source_case_policy import filter_visible_cases
from .source_entities import entity_id
from .source_work_items import project_work_items
from .workspace_projection import _strip_source_payloads


def case_navigation(workspace, project_id):
    """Pure, whitelisted projection; caller applies viewer privacy/admission."""
    state=filter_visible_cases(deepcopy(workspace))
    _strip_source_payloads(state)
    project=next((p for p in state.get('projects',[]) if p['id']==project_id),None)
    if project is None:return {'confirmations':[]}
    tasks={(node['id'],task['id']):task for node in project.get('nodes',[])
           for task in node.get('tasks',[])}
    new_items,status=project_work_items(state,project_id)
    use_items=state.get('source_work_items_enabled',True) and project_id in state.get('source_work_items_status',{})
    imported_contracts={cid for i in state.get('source_work_items',[]) if i.get('project_id')==project_id for cid in i['contract_ids']}
    confirmations=[]
    for confirmation in state.get('source_confirmations',[]):
        if confirmation.get('project_id')!=project_id or confirmation.get('source_kind')!='confirmation':continue
        case_items=use_items and any(confirmation['id'] in c.get('confirmation_ids',[]) and c['id'] in imported_contracts for c in state.get('contract_items',[]))
        contracts=[]
        for contract in state.get('contract_items',[]):
            if contract.get('project_id')!=project_id or confirmation['id'] not in contract.get('confirmation_ids',[]):continue
            items={};missing=False
            for ref in contract.get('task_refs',[]):
                if ref.get('project_id')!=project_id:continue
                task=tasks.get((ref.get('node_id'),ref.get('task_id')))
                origin=(task or {}).get('source_identity') or {}
                if not task or not all(origin.get(k) for k in ('base_token','table_id','record_id')):
                    missing=True;continue
                ident=entity_id(origin)
                if ident not in contract.get('reporting_ids',[]):
                    missing=True;continue
                items[ident]={'id':ident,'category':task.get('category') or 'unknown',
                              'source_url':task.get('source_url')}
            missing=missing or bool(set(contract.get('reporting_ids',[]))-items.keys())
            if case_items:
                linked=[i for i in new_items if contract['id'] in i['contract_ids']]
                items={i['id']:{k:i.get(k) for k in ('id','category','source_url')} for i in linked}
                missing=status['partial'] or any(i.get('source_missing') for i in linked)
            contracts.append({'id':contract['id'],'item_number':contract.get('item_number'),
                'title':contract.get('title'),'unresolved':bool(missing or contract.get('source_missing')
                    or contract.get('unresolved_confirmation_ids')),'work_items':list(items.values())})
        confirmations.append({'id':confirmation['id'],'code':confirmation.get('code'),
            'source_url':confirmation.get('source_url'),'contracts':contracts,
            'edge_states':{'contracts':'linked' if contracts else 'unlinked/unknown',
                'work_items':(('partial: source work items truncated' if status['truncated'] else
                    'partial: source work items incomplete' if status['partial'] else 'linked')
                    if case_items else 'partial: 外業 work items not imported'),
                'daily':'unlinked/unknown','files':'unlinked/unknown'}})
    result={'confirmations':confirmations}
    if use_items:result['work_items_status']={k:status[k] for k in ('partial','truncated')}
    return result
