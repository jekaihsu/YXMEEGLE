"""Independent, immutable-identity read models for quotation/contract business data."""
from copy import deepcopy
from .sources import source_id,text,number
from .workflow import now

KINDS={'quote':'source_quotes','confirmation':'source_confirmations',
       'quote_confirmation':'source_confirmations','contract':'contract_items'}
SET_ORDER_FIELDS=('confirmation_ids','unresolved_confirmation_ids','quote_ids','unresolved_quote_ids',
                  'project_ids','review_project_ids','reporting_ids')


def normalize_sets(entity):
    """Canonicalize relationship projections; source `fields` remain unaltered evidence."""
    for key in SET_ORDER_FIELDS:
        if key in entity:entity[key]=sorted(set(entity[key]))
    if 'task_refs' in entity:
        refs={(ref['project_id'],ref['node_id'],ref['task_id']) for ref in entity['task_refs']}
        entity['task_refs']=[dict(zip(('project_id','node_id','task_id'),ref)) for ref in sorted(refs)]
    return entity


CONTRACT_DERIVATION={
    'title':{'source_fields':['contract:合約工作項目']},
    'item_number':{'source_fields':['contract:合約項次']},
    'amount_original':{'source_fields':['contract:分項金額(原始)']},
    'amount_reported':{'source_fields':['contract:分項金額(報出)']},
    'confirmation_ids':{'source_fields':['contract:所屬成案確認單（日報關聯）'],
                        'other_inputs':['linked_record_snapshot','link_table_schema']},
    'unresolved_confirmation_ids':{'source_fields':['contract:所屬成案確認單（日報關聯）'],
                                   'other_inputs':['linked_record_snapshot','link_table_schema']},
    'reporting_ids':{'source_fields':['reporting:來源合約明細（日報關聯）'],
                     'other_inputs':['workspace_tasks']},
    'task_refs':{'source_fields':['reporting:來源合約明細（日報關聯）'],
                 'other_inputs':['workspace_tasks']},
    'project_id':{'other_inputs':['workspace_source_assignments']},
    'source_missing':{'other_inputs':['complete_table_snapshot']},
}


def explain_changes(before,after,field_schemas):
    """Describe observed value changes without inferring who or what edited Lark."""
    changes=[]
    def record(path,old,new,provenance,**details):
        changes.append({'path':path,'before':deepcopy(old),'after':deepcopy(new),
                        'provenance':provenance,**details})
    for key in sorted(before.keys()|after.keys()):
        if key in ('revision','history'):continue
        if key=='fields':
            old_fields=before.get('fields') or {};new_fields=after.get('fields') or {}
            for name in sorted(old_fields.keys()|new_fields.keys()):
                if name not in old_fields or name not in new_fields or old_fields[name]!=new_fields[name]:
                    schema=field_schemas.get(name) or {};field_type=schema.get('type')
                    provenance=('source_formula_observed' if field_type==20 else
                                'source_lookup_observed' if field_type==19 else 'source_observed')
                    details={'source_field':name}
                    prop=schema.get('property') or {}
                    if field_type==20 and isinstance(prop,dict) and 'formula' in prop:
                        details['formula']=deepcopy(prop['formula'])
                    record('fields.'+name,old_fields.get(name),new_fields.get(name),provenance,**details)
            continue
        if key not in before or key not in after or before[key]!=after[key]:
            details={}
            if after.get('source_kind',before.get('source_kind'))=='contract' and key in CONTRACT_DERIVATION:
                details['derived_from']=deepcopy(CONTRACT_DERIVATION[key])
            record(key,before.get(key),after.get(key),
                   'source_presence' if key=='source_missing' else 'derived',**details)
    return changes

QUOTE_FINANCE=('契約價格(未稅)','案件已入帳','累計已入帳','累計已請款','案件可請款總額',
               '入帳資料檢核','可請款未請','入帳日期','付款條件')


def entity_id(row):return '/'.join(row[k] for k in ('base_token','table_id','record_id'))


def update_entities(ws,records,complete_tables,assignments):
    index={}
    for row in records:index.setdefault((row['base_token'],row['record_id']),[]).append(row)
    def relations(row,field,kinds):
        # A native link may specify its target table inside the value, even when
        # linked_tables metadata is absent. Resolve against the full identity.
        from .v4_sources import native_records
        matches,missing=native_records(row,field,index,kinds)
        return [entity_id(match) for match in matches],[ref['record_id'] for ref in missing]
    result={key:{} for key in set(KINDS.values())}
    schemas={(table.get('base_token'),table.get('table_id')):
             {field.get('field_name'):field for field in table.get('field_schema') or []}
             for table in complete_tables or []}
    for row in records:
        kind=row.get('kind')
        if kind not in KINDS:continue
        fields=deepcopy(row['fields']);ident=entity_id(row);pid=assignments.get(source_id(row))
        entity={'id':ident,'source_identity':{k:row[k] for k in ('base_token','table_id','record_id')},
            'source_url':f"https://yong-xiang-survey.jp.larksuite.com/base/{row['base_token']}?table={row['table_id']}&record={row['record_id']}",
            'fields':fields,'source_kind':kind,'source_missing':False,'project_id':pid,'readonly':True}
        if kind=='quote':
            refs,missing=relations(row,'此案確認單',{'confirmation','quote_confirmation'})
            entity.update(code=text(fields.get('報價編號')),confirmation_ids=refs,unresolved_confirmation_ids=missing,
                project_ids=[pid] if pid else [],review_quote_id=source_id(row),review_project_ids=[],
                amount=number(fields.get('契約價格(未稅)')),
                financial={k:deepcopy(fields[k]) for k in QUOTE_FINANCE if k in fields})
        elif kind in ('confirmation','quote_confirmation'):
            refs,missing=relations(row,'所屬案件',{'quote'})
            entity.update(code=text(fields.get('工程確認單編號')),quote_ids=refs,unresolved_quote_ids=missing)
        else:
            refs,missing=relations(row,'所屬成案確認單（日報關聯）',{'confirmation','quote_confirmation'})
            entity.update(title=text(fields.get('合約工作項目')),item_number=text(fields.get('合約項次')),
                confirmation_ids=refs,unresolved_confirmation_ids=missing,
                amount_original=number(fields.get('分項金額(原始)')),amount_reported=number(fields.get('分項金額(報出)')),
                amount_scope='contract_item',allocation_status='unverified',reporting_ids=[],task_refs=[])
        result[KINDS[kind]][ident]=entity
    # Either explicitly linked direction can describe the quotation-confirmation
    # relation; neither display name nor similar engineering code creates a link.
    for q in result['source_quotes'].values():
        for cid in q['confirmation_ids']:
            c=result['source_confirmations'].get(cid)
            if c and q['id'] not in c['quote_ids']:c['quote_ids'].append(q['id'])
    for c in result['source_confirmations'].values():
        for qid in c['quote_ids']:
            q=result['source_quotes'].get(qid)
            if q and c['id'] not in q['confirmation_ids']:q['confirmation_ids'].append(c['id'])
    for q in result['source_quotes'].values():
        q['project_ids']=sorted({pid for pid in [q.get('project_id')]+[
            result['source_confirmations'][cid].get('project_id') for cid in q['confirmation_ids']
            if cid in result['source_confirmations']] if pid})
        q['review_project_ids']=[p['id'] for p in ws['projects']
            if any(item.get('id')==q['review_quote_id'] for item in p.get('quotes',[]))]
    task_index={}
    for p in ws['projects']:
        for node in p['nodes']:
            for task in node['tasks']:task_index.setdefault(task['id'],[]).append((p,node,task))
    for row in records:
        if row.get('kind')!='reporting':continue
        contracts,missing=relations(row,'來源合約明細（日報關聯）',{'contract'})
        taskid=source_id(row)
        for p,node,task in task_index.get(taskid,[]):
            task['contract_item_ids']=contracts;task['contract_link_unresolved']=bool(missing)
            for cid in contracts:
                entity=result['contract_items'][cid]
                if entity_id(row) not in entity['reporting_ids']:entity['reporting_ids'].append(entity_id(row))
                entity['task_refs'].append({'project_id':p['id'],'node_id':node['id'],'task_id':task['id']})
    complete={(t.get('base_token'),t.get('table_id')) for t in complete_tables or [] if t.get('status')=='ready'}
    for collection,items in result.items():
        old={row['id']:row for row in ws.get(collection,[])}
        for previous in ws.get(collection,[]):
            ident=previous['id']
            if ident in items:continue
            prior=deepcopy(previous);origin=prior['source_identity']
            if (origin['base_token'],origin['table_id']) in complete:prior['source_missing']=True
            items[ident]=prior
        for ident,row in items.items():
            previous=old.get(ident);history=deepcopy((previous or {}).get('history',[]))
            normalize_sets(row)
            clean=lambda value:{k:v for k,v in value.items() if k not in ('history','revision')}
            prior_clean=clean(previous) if previous is not None else None
            normalized_prior=normalize_sets(deepcopy(prior_clean)) if prior_clean is not None else None
            changed=previous is not None and normalized_prior!=clean(row)
            if changed:
                origin=row['source_identity'];field_schemas=schemas.get((origin['base_token'],origin['table_id']),{})
                history.append({'revision':previous.get('revision',1),'replaced_at':now(),
                                'snapshot':deepcopy(prior_clean),
                                'change_explanation':explain_changes(normalized_prior,clean(row),field_schemas)})
            row['revision']=(previous or {}).get('revision',1)+(1 if changed else 0)
            row['history']=history
        ws[collection]=list(items.values())
    for p in ws['projects']:
        p['source_entity_ids']={key:[r['id'] for r in rows.values() if r.get('project_id')==p['id'] or p['id'] in r.get('project_ids',[])]
                                for key,rows in result.items()}
