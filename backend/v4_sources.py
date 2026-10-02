"""Reconcile confirmation identities across V4 and the quotation register.

Snapshots never constitute local approvals. Unconfirmed quotations remain intake
records and ambiguous identity changes require review instead of moving history.
"""
import re
import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from urllib.parse import urlparse, parse_qs
from .sources import text, number, day, source_id, normalized_case, link_ids, new_task, canonical_department, unique_value, PROVISIONAL_CASE_FIELD
from .seed import STAGES
from .policy import upgrade, template, TECHNICAL, VERSION
from .workflow import now, uid

STATUS = {'報價中':'pending','執行中':'in_progress','已完工':'engineering_complete','已結案':'completed','中止':'paused','內部':'internal'}

def url(r):
    return f"https://yong-xiang-survey.jp.larksuite.com/base/{r['base_token']}?table={r['table_id']}&record={r['record_id']}"

def nodes(pid, sop):
    from .sop_contracts import enrich_definition,decorate_task,applicability,VERSION as CONTRACT_VERSION
    result=[]
    for key,name,_ in STAGES:
        definition=next(d for d in sop['nodes'] if d['key']==key)
        definitions=definition.get('task_definitions')or[{'key':f'legacy:{key}:{i}','title':title}for i,title in enumerate(definition['tasks'])]
        tasks=[];pending=[]
        for i,raw in enumerate(definitions):
            item=enrich_definition(raw)
            if item.get('disabled'):continue
            if applicability({},item)is None:
                pending.append({'key':item['key'],'rule':item['applicability'],'title':item['title'],'contract_version':CONTRACT_VERSION})
                continue
            tasks.append(decorate_task(new_task(f'{pid}-{key}-{i}',item['title'],None),item,sop['id']))
        result.append(dict(id=f'{pid}-{key}',key=key,name=name,owner_id='',supervisor_id='',collaborator_ids=[],status='pending',start_date=None,due_date=None,original_due_date=None,started_at=None,completed_at=None,tasks=tasks,requirements=deepcopy(definition['requirements']),review_mode=definition['review_mode'],reviewers=[],review_cycles=[],sop_applicability_pending=pending))
    return result


def new_project(code, first, sop, case_type='formal'):
    pid=uid()
    return dict(id=pid,code=code,name=text(first['fields'].get('工程名稱')) or code,client='',pm_id='',status='pending',priority='medium',due_date=None,original_due_date=None,created_at=now(),started_at=None,description='',contract_amount=None,estimated_points=None,source_kind='lark',source_model='v4',case_type=case_type,revision=1,nodes=nodes(pid,sop),files=[],comments=[],daily_reports=[],source_url=url(first),sop_version=sop['id'])


def quote_snapshot(record):
    f=record['fields']
    return dict(id=source_id(record),quote_code=normalized_case(f.get('報價編號')),engineering_code=normalized_case(f.get('工程編號')),source_url=url(record),amount=number(f.get('契約價格(未稅)')),fields=deepcopy(f))


def known_source_ids(p):
    result=set(p.get('source_record_ids',[])) | {q['id'] for q in p.get('quotes',[])}
    if p.get('source_kind')=='lark': result.add(p['id'])  # legacy source-derived project IDs
    if all(p.get('source_identity',{}).get(k) for k in ('base_token','table_id','record_id')): result.add(source_id(p['source_identity']))
    return result


def migrate_history(ws, target, other):
    """Preserve a complete pre-migration copy, and carry work into the canonical case."""
    snapshot=deepcopy(other); snapshot.update(migrated_to=target['id'],archived_reason='同確認單案件合併；完整歷史保留',archived_at=now())
    if not any(p['id']==other['id'] for p in ws['archived_projects']): ws['archived_projects'].append(snapshot)
    remap={other['id']:target['id']}
    for old in other['nodes']:
        dest=next((n for n in target['nodes'] if n['key']==old['key']),None)
        if not dest: target['nodes'].append(deepcopy(old)); continue
        remap[old['id']]=dest['id']
        for key in ('tasks','review_cycles'):
            present={x['id'] for x in dest.get(key,[])}
            dest.setdefault(key,[]).extend(deepcopy(x) for x in old.get(key,[]) if x['id'] not in present)
        if old.get('owner_id') and not dest.get('owner_id'): dest['owner_id']=old['owner_id']
        if old.get('status')!='pending' or old.get('owner_id'):
            dest.setdefault('migration_history',[]).append({'project_id':other['id'],'node_id':old['id'],'status':old['status'],'owner_id':old.get('owner_id'),'started_at':old.get('started_at'),'completed_at':old.get('completed_at')})
    for key in ('files','comments','daily_reports','evidence','finance_versions','payment_batches','issues','handoffs','confirmation_issues','quote_reviews'):
        present={x.get('id') for x in target.get(key,[]) if x.get('id')}
        target.setdefault(key,[]).extend(deepcopy(x) for x in other.get(key,[]) if not x.get('id') or x['id'] not in present)
    for key in ('pm_id','admin_id','supervisor_id'):
        if other.get(key) and not target.get(key): target[key]=other[key]
        elif other.get(key) and other[key]!=target.get(key): target.setdefault('migration_conflicts',{})[key]=[target[key],other[key]]
    target.setdefault('migration_history',[]).append({'project_id':other['id'],'code':other['code'],'status':other.get('status'),'at':now()})
    target['migration_review_required']=True
    if other.get('finance_versions') or other.get('payment_batches'):
        target.setdefault('migration_conflicts',{})['finance']=['已保留原案件財務歷史，合併後須核對有效版本與收付款']
    ws['projects'].remove(other)
    def rewrite(value):
        if isinstance(value,list):
            for item in value: rewrite(item)
        elif isinstance(value,dict):
            for k,v in list(value.items()):
                if k in ('project_id','node_id') and isinstance(v,str) and v in remap: value[k]=remap[v]
                elif k not in ('archived_projects','migration_history','migration_archive'): rewrite(v)
    rewrite(ws)


def daily_review(record, costs):
    """Only a source's explicit review status can assert approval/return."""
    fields=record['fields']; checks={}
    names=('工務助理檢核','外業經理檢核','控制組檢核','品管檢核','雅雯檢核','PM檢核','內業組長檢核')
    for prefix,f in [('daily',fields)]+[(f'cost:{i}',c) for i,c in enumerate(costs)]:
        for name in names:
            if name in f: checks[prefix+':'+name]=deepcopy(f[name])
    raw=text(fields.get('檢核狀態')).strip()
    status={'已通過':'approved','已退回':'returned','待檢核':'pending'}.get(raw,'unverified')
    return {'status':status,'source_status':raw,'checks':checks,'checked_at':fields.get('檢核時間'),'source_url':url(record)}


def source_people(value):
    """Keep native open IDs only; display names can never confer edit permission."""
    if isinstance(value,list): return {ident for item in value for ident in source_people(item)}
    if isinstance(value,dict):
        return {value[k] for k in ('id','open_id') if isinstance(value.get(k),str) and value[k].startswith('ou_')}
    return {value} if isinstance(value,str) and value.startswith('ou_') and not any(c.isspace() for c in value) else set()


def native_records(record, field, index, kinds):
    """Resolve every link, including its explicit/schema table. Never drop a bad half."""
    refs = []
    def visit(value, table=None):
        if isinstance(value, list):
            for item in value: visit(item, table)
        elif isinstance(value, dict):
            table = value.get('table_id') or table
            for key in ('record_id', 'record_ids', 'link_record_ids'):
                if key in value: visit(value[key], table)
        elif isinstance(value, str) and value.startswith('rec'):
            refs.append((table, value))
    visit(record['fields'].get(field), record.get('linked_tables', {}).get(field)
          or (record.get('cost_table_id') if field == '所屬成本單' else None))
    resolved, missing = [], []
    for table, rid in dict.fromkeys(refs):
        candidates = [r for r in index.get((record['base_token'], rid), [])
                      if r.get('kind') in kinds and (not table or r['table_id'] == table)]
        if len(candidates) == 1: resolved.append(candidates[0])
        else: missing.append({'base_token': record['base_token'], 'table_id': table,
                              'record_id': rid, 'field': field})
    return resolved, missing


RELATIONS = {'daily': {'所屬案件': {'confirmation','quote_confirmation'},
                       '內業工項': {'reporting'}, '合約工項': {'reporting'}, '所屬成本單': {'cost'}},
             'reporting': {'來源合約明細（日報關聯）': {'contract'}},
             'contract': {'所屬成案確認單（日報關聯）': {'confirmation','quote_confirmation'}}}


def source_provenance(record, index):
    seen, missing = {}, []
    def visit(row):
        ident = source_id(row)
        if ident in seen: return
        seen[ident] = {'id': ident, 'kind': row['kind'], 'fields': deepcopy(row['fields'])}
        for field, kinds in RELATIONS.get(row['kind'], {}).items():
            linked, unresolved = native_records(row, field, index, kinds)
            missing.extend(unresolved)
            for item in linked: visit(item)
    visit(record)
    return {'records': [seen[k] for k in sorted(seen)],
            'unresolved': sorted(missing, key=lambda x: json.dumps(x, sort_keys=True))}


def provenance_hash(provenance):
    return hashlib.sha256(json.dumps(provenance, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def daily_source_version(entry):
    provenance=deepcopy(entry.get('source_provenance'))
    if not provenance:return provenance_hash({'source_fields':entry.get('source_fields',{})})
    # An upstream administrative note cannot revoke every manually paired daily.
    # Preserve the full provenance for audit; identity approval consumes only the
    # upstream identity/relationship facts, while the daily and cost stay exact.
    identity_fields={'工程確認單編號','所屬案件','SourceID','報價編號'}
    for record in provenance.get('records',[]):
        if record.get('kind') in ('confirmation','quote_confirmation'):
            record['fields']={k:v for k,v in record['fields'].items() if k in identity_fields}
    return provenance_hash(provenance)


def daily_mapping_version(entry):
    """Case pairing binds identities/links, independently of delivered content."""
    provenance=deepcopy(entry.get('source_provenance'))
    identity_fields={'工程確認單編號','所屬案件','SourceID','報價編號','工程編號',
                     PROVISIONAL_CASE_FIELD,'可能確認單工作編號'}
    if not provenance:
        # Legacy rows cannot prove which fields are identity-bearing; retain
        # their full supplied source content instead of guessing a safe subset.
        return provenance_hash({'id':entry.get('id'),'fields':entry.get('source_fields',{})})
    for record in provenance.get('records',[]):
        if record.get('kind') in ('daily','cost'):continue
        allowed=identity_fields|set(RELATIONS.get(record.get('kind'),{}))
        record['fields']={k:v for k,v in record.get('fields',{}).items() if k in allowed}
    return provenance_hash(provenance)


def review_mapping_version(review):
    if review.get('mapping_version'):return review['mapping_version']
    # Existing approvals stored their original entry; derive only from that
    # immutable snapshot, never silently trust today's changed relationship.
    entry=review.get('entry')
    return daily_mapping_version(entry) if isinstance(entry,dict) and entry.get('id') else None


def mark_missing_dailies(ws, records, complete_tables):
    """Only explicit complete table snapshots prove absence, never an incremental list."""
    covered = set()
    for table in complete_tables or []:
        key = (table.get('base_token'), table.get('table_id'))
        rows = [r for r in records if (r['base_token'], r['table_id']) == key]
        if (all(key) and table.get('kind') == 'daily' and table.get('status') == 'ready'
                and isinstance(table.get('count'), int) and table['count'] == len(rows)
                and all(r.get('kind') == 'daily' for r in rows)):
            covered.add(key)
    present = {source_id(r) for r in records if r.get('kind') == 'daily'}
    def identity(entry):
        ident = entry.get('source_identity')
        if not ident:
            parsed = urlparse(entry.get('source_url', '')); query = parse_qs(parsed.query)
            ident = {'base_token': parsed.path.split('/')[-1],
                     'table_id': query.get('table', [''])[0], 'record_id': query.get('record', [''])[0]}
        if all(ident.get(k) for k in ('base_token','table_id','record_id')) and source_id(ident) == entry['id']:
            return ident
        return None
    moved = []
    for owner, entries in [(p, p['daily_reports']) for p in ws['projects']] + [(None, ws['daily_unmatched'])]:
        for entry in list(entries):
            ident = identity(entry)
            if not ident or (ident['base_token'], ident['table_id']) not in covered or entry['id'] in present:
                continue
            if not entry.get('source_missing'):
                entry.update(source_missing=True, source_missing_at=now(), source_identity=ident,
                             case_mapping_status='source_missing', mapping_status='source_missing',
                             source_missing_reason='完整來源表快照已無此日報；保留歷史，不作有效成果')
                if owner: entry['previous_project_id'] = owner['id']
            if owner:
                entries.remove(entry); moved.append(entry)
            for review in ws['daily_reviews']:
                if review['daily_id'] == entry['id'] and review['status'] in ('pending', 'approved'):
                    review.update(status='invalidated', invalidated_at=now(), invalidated_reason='完整来源快照已無此日報')
    for entry in moved:
        ws['daily_unmatched'] = [d for d in ws['daily_unmatched'] if d['id'] != entry['id']] + [entry]

def import_v4(ws, records, complete_tables=None):
    upgrade(ws)
    record_index=defaultdict(list)
    for record in records: record_index[(record['base_token'],record['record_id'])].append(record)
    mark_missing_dailies(ws, records, complete_tables)
    confirmed=[r for r in records if r.get('kind') in ('confirmation','quote_confirmation')]
    quotes=[r for r in records if r.get('kind')=='quote']
    grouped=defaultdict(list)
    for r in confirmed:
        code=normalized_case(r['fields'].get('工程確認單編號'))
        if code: grouped[code].append(r)
    # Native quote <-> confirmation links are scoped to their originating Base.
    confirmation_codes={(r['base_token'],r['record_id']):normalized_case(r['fields'].get('工程確認單編號')) for r in confirmed}
    reverse_quotes=defaultdict(set)
    for r in confirmed:
        code=confirmation_codes[(r['base_token'],r['record_id'])]
        for rid in link_ids(r['fields'].get('所屬案件')):
            if code: reverse_quotes[(r['base_token'],rid)].add(code)
    linked_quotes=defaultdict(list); intakes=[]
    for q in quotes:
        f=q['fields']; codes=set(reverse_quotes[(q['base_token'],q['record_id'])])
        refs=link_ids(f.get('此案確認單'))
        unresolved=any(not confirmation_codes.get((q['base_token'],rid)) for rid in refs)
        codes.update(confirmation_codes[(q['base_token'],rid)] for rid in refs if confirmation_codes.get((q['base_token'],rid)))
        engineering=normalized_case(f.get('工程編號'))
        if engineering and (engineering in grouped or codes): codes.add(engineering)
        if len(codes)==1 and not unresolved: linked_quotes[next(iter(codes))].append(q)
        else: intakes.append((q,sorted(codes),'unresolved_confirmation' if unresolved else 'multiple_confirmations' if len(codes)>1 else 'awaiting_confirmation'))
    original_projects=list(ws['projects'])
    previous_records={p['id']:deepcopy(p.get('source_records',[])) for p in original_projects}
    original_source_ids={p['id']:known_source_ids(p) for p in original_projects}
    existing=defaultdict(list)
    for p in original_projects:
        # An unconfirmed quote's display code can equal a confirmation code, but
        # that is not proof the quote belongs to the confirmed case. Only its
        # native source identity may promote it. Matching it here would merge
        # and recreate that intake on every refresh, duplicating its SOP tasks.
        if p.get('source_kind')=='lark' and p.get('case_type')!='intake': existing[p['code']].append(p)
    group_ids={code:{source_id(r) for r in group+linked_quotes[code]} for code,group in grouped.items()}
    # Detect code splits/collisions against the snapshot before mutating anything.
    claimed=defaultdict(set)
    for code,ids in group_ids.items():
        for p in original_projects:
            if ids & original_source_ids[p['id']]: claimed[p['id']].add(code)
    ws['source_identity_conflicts']=[]
    aliases=defaultdict(dict); by_ref={}; report_projects={}; report_fields={}; contract_projects={}
    sop=next(s for s in reversed(ws['sop_templates']) if s['status']=='published')
    for code, group in grouped.items():
        group=sorted(group,key=lambda r:(r['base_token'],r['table_id'],r['record_id']))
        by_identity=[p for p in original_projects if group_ids[code]&original_source_ids[p['id']]]
        candidates=list({p['id']:p for p in existing[code]+by_identity}.values())
        collision=any(len(claimed[p['id']])>1 for p in candidates) or any(p['code']!=code and p.get('case_type')!='intake' for p in by_identity) and bool(existing[code])
        # Multiple legacy projections of the same exact case are migratable; distinct
        # established confirmation identities are not automatically collapsed.
        collision=collision or len([p for p in candidates if p.get('source_model')=='v4' and p.get('case_type')!='intake'])>1
        if collision:
            conflict={'code':code,'project_ids':[p['id'] for p in candidates],'source_ids':sorted(group_ids[code]),'reason':'confirmation_identity_collision','records':[{'id':source_id(r),'fields':deepcopy(r['fields']),'url':url(r)} for r in group]}
            ws['source_identity_conflicts'].append(conflict)
            for p in candidates: p.setdefault('source_conflicts',{})['identity']=[code]
            continue
        candidates.sort(key=lambda p:(p.get('case_type')=='intake',p.get('created_at',''),p['id']))
        p=candidates[0] if candidates else None
        first=group[0]
        if not p:
            p=new_project(code,first,sop)
            ws['projects'].append(p)
        elif p['code']!=code: p.setdefault('code_history',[]).append(p['code']); p['code']=code
        from .case_cutover import reconcile_merged_execution
        reconcile_merged_execution(ws,p,candidates)
        for other in candidates[1:]: migrate_history(ws,p,other)
        p.update(case_type='formal',source_model='v4',source_url=url(first))
        p['parent_code']=re.fullmatch(r'([A-Za-z][0-9]{6})-([0-9]{2})',code).group(1) if re.fullmatch(r'([A-Za-z][0-9]{6})-([0-9]{2})',code) else None
        p['quotes']=[quote_snapshot(q) for q in linked_quotes[code]]
        snapshots=[{'id':source_id(r),'kind':r['kind'],'fields':deepcopy(r['fields']),'url':url(r)} for r in group+linked_quotes[code]]
        p['source_records']=snapshots; p['source_record_ids']=[x['id'] for x in snapshots]
        p['source_identity']={k:first[k] for k in ('base_token','table_id','record_id')}
        conflicts={}
        for field in ('工程名稱','合約總額','預估總成本','實際總成本','狀態'):
            vals={text(r['fields'].get(field)) for r in group if text(r['fields'].get(field))}
            if len(vals)>1: conflicts[field]=sorted(vals)
        p['source_conflicts']=conflicts
        if '工程名稱' not in conflicts: p['name']=unique_value(text(r['fields'].get('工程名稱')) for r in group) or p['name']
        remote=unique_value(text(r['fields'].get('狀態')) for r in group)
        p['source_status']=remote or '來源狀態待核對'
        # Lark's archived/finished label is source information, never a local
        # delivery, payment or closure approval.
        p['status']=p.get('execution_status','pending')
        p['source_finance']={k:None if k in conflicts else number(unique_value(text(r['fields'].get(k)) for r in group)) for k in ('合約總額','預估總成本','實際總成本')}
        p['source_finance']['actual_cost_verified']=False
        if sorted(previous_records.get(p['id'],[]),key=lambda r:r['id'])!=sorted(snapshots,key=lambda r:r['id']):
            p['source_changed_at']=now()
        for node in p['nodes']:
            complete=remote=='已結案' or remote=='已完工' and node['key'] in TECHNICAL|{'sales','confirmation','pm'} or remote=='執行中' and node['key'] in {'sales','confirmation'}
            node['source_declared_completed']=complete
            node['source_completed']=False
            node['source_completion_basis']='依 V4 匯入' if complete else None
            # Local work and votes are never overwritten by source refreshes.
        for r in group:
            by_ref[(r['base_token'],r['record_id'])]=p
            for value in (code,text(r['fields'].get('所屬案件')),text(r['fields'].get('報價編號'))):
                if value: aliases[normalized_case(value)][p['id']]=p
        for q in linked_quotes[code]:
            for value in (q['fields'].get('報價編號'),q['fields'].get('工程編號')):
                if normalized_case(value): aliases[normalized_case(value)][p['id']]=p
    for q,possible,reason in intakes:
        ident=source_id(q); snapshot=quote_snapshot(q)
        # A previously confirmed quote losing its link is a review issue, never an
        # instruction to delete its project's history or silently demote that case.
        owners=[p for p in ws['projects'] if ident in known_source_ids(p) or ident in original_source_ids.get(p['id'],set())]
        p=next((p for p in owners if p.get('case_type')=='intake' or p.get('source_model')!='v4'),None)
        if p is None and owners:
            for owner in owners:
                owner.setdefault('source_conflicts',{})['quote:'+ident]=[reason]+possible
                owner['quotes']=[v for v in owner.get('quotes',[]) if v['id']!=ident]+[snapshot]
                if ident not in owner['source_record_ids']: owner['source_record_ids'].append(ident)
                owner['source_records']=[v for v in owner['source_records'] if v['id']!=ident]+[{'id':ident,'kind':'quote','fields':deepcopy(q['fields']),'url':url(q)}]
            continue
        if p is None:
            p=new_project(snapshot['quote_code'] or ident,q,sop,'intake'); ws['projects'].append(p)
        p.update(case_type='intake',source_model='v4',intake_status=reason,quotes=[snapshot],source_url=url(q),source_record_ids=[ident],source_records=[{'id':ident,'kind':'quote','fields':deepcopy(q['fields']),'url':url(q)}],source_identity={k:q[k] for k in ('base_token','table_id','record_id')},parent_code=None)
        p['source_conflicts']={'confirmation':possible} if possible else {}
        p['name']=text(q['fields'].get('工程名稱')) or p['name']
        p['source_status']='待確認單'; p['status']='pending'
    for r in records:
        if r.get('kind')!='contract': continue
        f=r['fields']; targets,unresolved=native_records(r,'所屬成案確認單（日報關聯）',record_index,{'confirmation','quote_confirmation'})
        candidates={p['id']:p for target in targets if (p:=by_ref.get((target['base_token'],target['record_id'])))}
        unresolved=bool(unresolved or any((t['base_token'],t['record_id']) not in by_ref for t in targets))
        candidates.update(aliases.get(normalized_case(f.get('所屬案件')), {}))
        if len(candidates)==1 and not unresolved: contract_projects[(r['base_token'],r['record_id'])]=next(iter(candidates.values()))
    for r in records:
        if r.get('kind')!='reporting': continue
        f=r['fields']; refs=link_ids(f.get('來源合約明細（日報關聯）'))
        targets,unresolved=native_records(r,'來源合約明細（日報關聯）',record_index,{'contract'})
        candidates={p['id']:p for target in targets if (p:=contract_projects.get((target['base_token'],target['record_id'])))}
        unresolved=bool(unresolved or any((t['base_token'],t['record_id']) not in contract_projects for t in targets))
        direct=aliases.get(normalized_case(f.get('所屬案件')), {})
        candidates.update(direct)
        key={'控制':'control','圖資':'mapping','報告':'report'}.get(text(f.get('工項類別')))
        if len(candidates)!=1 or unresolved: continue
        p=next(iter(candidates.values())); report_projects[(r['base_token'],r['record_id'])]=p; report_fields[(r['base_token'],r['record_id'])]=f
        if not key: continue  # 外業 remains its SOP, not a duplicated confirmation work item.
        node=next(n for n in p['nodes'] if n['key']==key); ident=source_id(r)
        source={'title':text(f.get('工項名稱') or f.get('填報工項')) or 'V4 工項','points':number(f.get('對應營業額')),'work_item_id':'|'.join(sorted(refs)) or ident,
                'source_fields':deepcopy(f),'source_url':url(r)}
        elsewhere=[(oldp,oldn,t) for oldp in ws['projects'] for oldn in oldp['nodes'] for t in oldn['tasks'] if t['id']==ident and oldn is not node]
        protected=[(oldp,oldn,t) for oldp,oldn,t in elsewhere if t.get('started_at') or t.get('manual_updated') or t.get('status')!='pending' or t.get('output') or t.get('comments')]
        if protected:
            for oldp,oldn,t in protected:
                t['source_change_pending']=True
                t['source_reassignment_pending']={'project_id':p['id'],'node_id':node['id'],'source':deepcopy(source)}
                oldp.setdefault('source_conflicts',{})['work_item:'+ident]=[oldp['code'],p['code']]
            p.setdefault('source_conflicts',{})['work_item:'+ident]=['人工工項待核對，尚未搬移']
            continue
        moved=None
        for oldp,oldn,t in elsewhere:
            oldn['tasks'].remove(t)
            if moved is None: moved=t
        task=next((t for t in node['tasks'] if t['id']==ident),None)
        if not task and moved:
            task=moved; node['tasks'].append(task); task.update(source)
        if not task:
            task=new_task(ident,source['title'],source['work_item_id'],source['points']); task['source_identity']={k:r[k] for k in ('base_token','table_id','record_id')}; node['tasks'].append(task)
            from .workflow_rules import inherit_new_task
            inherit_new_task(ws,p,node,task)
        elif task.get('source_snapshot')!=source:
            if task.get('started_at') or task.get('manual_updated'): task['source_change_pending']=True
            else: task.update(source)
        task['source_snapshot']=source
    stats=dict(daily_imported=0,daily_unmatched=0,daily_unmatched_missing_reference=0,daily_unmatched_unresolved_reference=0,daily_unmatched_ambiguous_reference=0,daily_missing_date=0,daily_missing_department=0,daily_conflicting_dates=0,daily_provisional=0,confirmations_missing_code=sum(not normalized_case(r['fields'].get('工程確認單編號')) for r in confirmed),projects=sum(p.get('case_type','formal')=='formal' for p in ws['projects']),intakes=sum(p.get('case_type')=='intake' for p in ws['projects']),identity_conflicts=len(ws['source_identity_conflicts']))
    costs=defaultdict(list)
    for r in records:
        if r.get('kind')=='cost': costs[(r['base_token'],r['record_id'])].append(r)
    for r in records:
        if r.get('kind')!='daily': continue
        f=r['fields']; ident=source_id(r)
        for p in ws['projects']: p['daily_reports']=[d for d in p['daily_reports'] if d['id']!=ident]
        ws['daily_unmatched']=[d for d in ws['daily_unmatched'] if d['id']!=ident]
        code=normalized_case(f.get('案件編號') or f.get('工程編號') or f.get('案號'))
        candidates=dict(aliases.get(code,{})); basis='source_case_or_link'; linked=[]; unresolved_case=False
        for field in ('所屬案件','內業工項','合約工項'):
            targets,unresolved=native_records(r,field,record_index,RELATIONS['daily'][field])
            unresolved_case=unresolved_case or bool(unresolved)
            for target in targets:
                rid=target['record_id']
                p=(by_ref if field=='所屬案件' else report_projects).get((target['base_token'],rid))
                if p: candidates[p['id']]=p
                else: unresolved_case=True
                if (r['base_token'],rid) in report_fields: linked.append(report_fields[(r['base_token'],rid)])
        if not candidates and not code and not any(link_ids(f.get(k)) for k in ('所屬案件','內業工項','合約工項')):
            code=normalized_case(f.get(PROVISIONAL_CASE_FIELD) or f.get('可能確認單工作編號')); candidates=dict(aliases.get(code,{})); basis='provisional_case_code'
        costrecords,_=native_records(r,'所屬成本單',record_index,{'cost'})
        costfields=[c['fields'] for c in costrecords]
        dates={day(f.get(k),formula_serial=k in ('工作日期-薪資','工作日期-營業額明細')) for k in ('工作日期-薪資','工作日期-營業額明細','日期')}|{day(c.get(k)) for c in costfields for k in ('工作日期','出工日期','日期')}; dates.discard('')
        rawgroup=unique_value([text(f.get('組別'))]+[text(c.get('內業組別') or c.get('組別') or c.get('所屬組別')) for c in costfields])
        department=canonical_department(text(f.get('營業額組別-明細') or r.get('department')) or unique_value(text(x.get('工項類別')) for x in linked) or rawgroup)
        people=[text(f.get('姓名') or f.get('填寫人') or f.get('人員'))]
        for c in [f]+costfields:
            for k in ('填報帳號','組長帳號-津貼自動化','組員帳號-津貼自動化'):
                v=c.get(k); people.extend(text(x) for x in v) if isinstance(v,list) else people.append(text(v))
        entry=dict(id=ident,date=unique_value(dates),department=department,source_department=rawgroup,case_code=code,source_case_code=code,person='、'.join(dict.fromkeys(x for x in people if x)),description=text(f.get('工作內容') or f.get('工項說明') or f.get('本明細適用工項') or f.get('備註')) or '、'.join(text(x.get('工項名稱')) for x in linked),points=number(f.get('最終營業額點數') if f.get('最終營業額點數') is not None else f.get('營業額點數')),source_url=url(r),match_basis=basis,mapping_status='conflicting_dates' if len(dates)>1 else 'missing_date' if not dates else 'missing_department' if not department else 'provisional_case_code' if basis=='provisional_case_code' else 'ready',source_fields=deepcopy(f))
        entry['review']=daily_review(r,costfields)
        entry['source_identity']={k:r[k] for k in ('base_token','table_id','record_id')}
        entry['source_actor_ids']=sorted({ident for person_fields in [f]+costfields for key in ('姓名','填寫人','人員','填報帳號','組長帳號-津貼自動化','組員帳號-津貼自動化') for ident in source_people(person_fields.get(key))})
        entry['source_provenance']=source_provenance(r,record_index)
        entry['source_version']=daily_source_version(entry)
        entry['mapping_version']=daily_mapping_version(entry)
        for review in ws['daily_reviews']:
            if (review['daily_id']==ident and review['status'] in ('pending','approved')
                    and not review_mapping_version(review) and review.get('source_version')==entry['source_version']):
                review['mapping_version']=entry['mapping_version']
            if review['daily_id']==ident and review['status'] in ('pending','approved') and review_mapping_version(review)!=entry['mapping_version']:
                review.update(status='invalidated',invalidated_at=now(),invalidated_reason='日報或上游關聯來源已改版，須重新核對')
        approved=next((m for m in reversed(ws['daily_reviews']) if m['daily_id']==ident and m['status']=='approved' and review_mapping_version(m)==entry['mapping_version']),None)
        if approved:
            candidates={p['id']:p for p in ws['projects'] if p['id']==approved['project_id']}; entry['match_basis']='manual_review'; unresolved_case=False
        # Date/department quality applies to all source rows, including unmatched
        # rows. Counting it only after a match makes a broken source look healthy.
        for k,condition in [('daily_provisional',basis=='provisional_case_code' and bool(code)),('daily_missing_date',not dates),('daily_missing_department',not department),('daily_conflicting_dates',len(dates)>1)]: stats[k]+=int(condition)
        if len(candidates)!=1 or unresolved_case:
            has_reference=bool(code or any(link_ids(f.get(k)) for k in ('所屬案件','內業工項','合約工項')))
            reason='ambiguous_reference' if len(candidates)>1 else 'unresolved_reference' if has_reference or unresolved_case else 'missing_reference'
            entry['case_mapping_status']=reason
            stats['daily_unmatched_'+reason]+=1
            entry['candidates']=list(candidates); ws['daily_unmatched'].append(entry); stats['daily_unmatched']+=1; continue
        p=next(iter(candidates.values())); entry['case_code']=p['code']; entry['case_mapping_status']='matched'; p['daily_reports'].append(entry)
        stats['daily_imported']+=1
    for p in ws['projects']:
        scope_records=[{'id':source_id(r),'kind':r['kind'],'fields':r['fields']} for r in records
                       if r.get('kind') in ('contract','reporting') and
                       (contract_projects if r['kind']=='contract' else report_projects).get((r['base_token'],r['record_id'])) is p]
        p['source_scope_hash']=provenance_hash(sorted(scope_records,key=lambda x:x['id']))
        p['source_work_items']=deepcopy(scope_records)
        fingerprints={q['id']:hashlib.sha256(json.dumps(q,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest() for q in p.get('quotes',[])}
        for review in p.get('quote_reviews',[]):
            if review['status'] in ('pending','approved') and fingerprints.get(review['quote_id'])!=review['source_hash']:
                review.update(status='invalidated',invalidated_reason='來源報價版本已更新，須重新共同確認',invalidated_at=now())
    stats['daily_source_missing']=sum(bool(d.get('source_missing')) for d in ws['daily_unmatched'])
    upgrade(ws)
    from .source_projection import update_attachments,preserve_missing_sources
    preserve_missing_sources(ws,records,complete_tables,previous_records)
    assignments={source_id(r):p['id'] for r in records
                 if (p:=contract_projects.get((r['base_token'],r['record_id']))
                     or report_projects.get((r['base_token'],r['record_id'])))}
    for p in ws['projects']:
        for ident in p.get('source_record_ids',[]): assignments[ident]=p['id']
        for entry in p.get('daily_reports',[]): assignments[entry['id']]=p['id']
    update_attachments(ws,records,complete_tables,assignments)
    from .source_entities import update_entities
    update_entities(ws,records,complete_tables,assignments)
    from .case_cutover import initialize_execution_system
    initialize_execution_system(ws)
    from .operations import reconcile_daily_evidence,refresh_project_state
    reconcile_daily_evidence(ws)
    for p in ws['projects']:
        refresh_project_state(p,ws)
        p['status']=p['execution_status']
    return stats
