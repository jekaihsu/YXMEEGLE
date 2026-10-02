"""Extract already-read template contracts; no network or runtime mutation."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
fields={}
for name in ('meegle-fields-20260929.json','meegle-fields-p2-20260929.json'):
    page=json.loads((ROOT/'.runtime'/name).read_text(encoding='utf-16'))
    fields.update({f['field_key']:f for f in page['list']})
assert not page['pagination']['has_more']

def keys_in(value):
    result=set()
    if isinstance(value,dict):
        for k,v in value.items():
            if k in ('field_key','key') and isinstance(v,str) and v.startswith('field_'):result.add(v)
            result.update(keys_in(v))
    elif isinstance(value,list):
        for v in value:result.update(keys_in(v))
    return result

out={'status':'readonly_source_contracts_not_runtime_enabled','field_count':len(fields),'templates':[]}
for tid in (334662,566082):
    path=ROOT/f'.runtime/meegle-template{tid}-detail-20260929.json'
    template=json.loads(path.read_text(encoding='utf-8'))['data'][0]
    nodes=[]
    for n in template['workflow_conf']['nodes']:
        selected={k:n.get(k) for k in ('state_key','name','node_type','start_mode','pass_mode','owner',
          'required_node_fields','field_extra_settings','form_conf','reform_visibility',
          'node_transition_requirement_v2','done_operation_role','rollback_operation_role',
          'plan_info','task','union_delivery_list','deliverable')}
        referenced=keys_in(selected)
        selected['resolved_field_metadata']={k:fields.get(k,{'unresolved':True})for k in sorted(referenced)}
        nodes.append(selected)
    out['templates'].append({'id':tid,'version':template['version'],'name':template['name'],
      'source':str(path.relative_to(ROOT)).replace('\\','/'),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
      'roles':template['key_to_label'],'connections':template['workflow_conf']['connections'],'nodes':nodes})
target=ROOT/'docs/SOP_TEMPLATE_CONTRACTS_20260929.json'
target.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for t in out['templates']:
    refs={k for n in t['nodes']for k in n['resolved_field_metadata']}
    tasks=[x for n in t['nodes']for x in(n.get('task')or[])]
    print(json.dumps({'template':t['id'],'version':t['version'],'nodes':len(t['nodes']),
      'node_forms_with_schema':sum(bool((n['form_conf']or{}).get('schema'))for n in t['nodes']),
      'tasks':len(tasks),'required_tasks':sum((x.get('node_pass_required')or{}).get('value')is True for x in tasks),
      'referenced_custom_fields':len(refs),'unresolved_fields':sorted(refs-fields.keys())},ensure_ascii=False))
