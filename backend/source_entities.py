"""Independent, immutable-identity read models for quotation/contract business data."""
from copy import deepcopy
from .sources import source_id,text,number,link_ids
from .workflow import now

KINDS={'quote':'source_quotes','confirmation':'source_confirmations',
       'quote_confirmation':'source_confirmations','contract':'contract_items'}
QUOTE_FINANCE=('契約價格(未稅)','案件已入帳','累計已入帳','累計已請款','案件可請款總額',
               '入帳資料檢核','可請款未請','入帳日期','付款條件')


def entity_id(row):return '/'.join(row[k] for k in ('base_token','table_id','record_id'))


def update_entities(ws,records,complete_tables,assignments):
    index={}
    for row in records:index.setdefault((row['base_token'],row['record_id']),[]).append(row)
    def relations(row,field,kinds):
        table=row.get('linked_tables',{}).get(field)
        refs=[];missing=[]
        for rid in link_ids(row['fields'].get(field)):
            matches=[r for r in index.get((row['base_token'],rid),[]) if r.get('kind') in kinds and (not table or r['table_id']==table)]
            if len(matches)==1:refs.append(entity_id(matches[0]))
            else:missing.append(rid)
        return refs,missing
    result={key:{} for key in set(KINDS.values())}
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
            clean=lambda value:{k:v for k,v in value.items() if k not in ('history','revision')}
            changed=previous is not None and clean(previous)!=clean(row)
            if changed:history.append({'revision':previous.get('revision',1),'replaced_at':now(),'snapshot':deepcopy(clean(previous))})
            row['revision']=(previous or {}).get('revision',1)+(1 if changed else 0)
            row['history']=history
        ws[collection]=list(items.values())
    for p in ws['projects']:
        p['source_entity_ids']={key:[r['id'] for r in rows.values() if r.get('project_id')==p['id'] or p['id'] in r.get('project_ids',[])]
                                for key,rows in result.items()}
