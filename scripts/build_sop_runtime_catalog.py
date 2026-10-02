"""Package verified source contracts without connecting to Meegle."""
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
source=json.loads((root/'docs/SOP_TEMPLATE_CONTRACTS_20260929.json').read_text(encoding='utf-8'))
result={'version':'sop-contracts-20260929.1','templates':[]}
for template in source['templates']:
    nodes=[]
    for node in template['nodes']:
        item={k:node.get(k)for k in ('state_key','name','node_type','start_mode','pass_mode','owner','required_node_fields',
          'form_conf','reform_visibility','node_transition_requirement_v2','done_operation_role','resolved_field_metadata')}
        item['disabled']=template['id']==334662 and node['state_key'] in ('state_52','state_58')
        item['disabled_reason']='業主核定停用考評與薪資相關計算' if item['disabled'] else ''
        item['tasks']=[]
        for task in node.get('task')or[]:
            task_key=task.get('element_key')or task['task_key']
            identity=f"meegle:{template['id']}:{node['state_key']}:{task_key}"
            item['tasks'].append({'identity':identity,'contract_id':f"{identity}:v{template['version']}",
              'task_key':task_key,**{k:task.get(k)for k in ('name','owner','pass_mode','node_pass_required','reform_visibility','deliverable','plan_info','union_delivery_list')}})
        nodes.append(item)
    result['templates'].append({k:template[k]for k in ('id','version','name','sha256','roles','connections')}|{'nodes':nodes})
(root/'backend/sop_source_contracts.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
print({'templates':len(result['templates']),'tasks':sum(len(n['tasks'])for t in result['templates']for n in t['nodes'])})
