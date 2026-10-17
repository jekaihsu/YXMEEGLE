"""Pure planning links. Derived evidence never assigns executable work."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import json
from .sources import normalized_case, text
from .source_work_items import MAX_BYTES, MAX_ROWS

RULE_VERSION='contract-links-20261017.1'
CATEGORY_FIELDS={c:(c+'數量',c+'工項') for c in ('外業','控制','圖資','報告')}
NATIVE_ITEM_FIELD='來源合約明細（日報關聯）'
NATIVE_CASE_FIELD='所屬成案確認單（日報關聯）'


class Status(StrEnum):
    UNIQUE='unique'
    AMBIGUOUS='ambiguous'
    NONE='none'


class Reason(StrEnum):
    EXACT_MATCH='exact_match'
    NO_CODE='no_code'
    NO_NAME='no_name'
    NO_MATCH='no_match'
    MULTIPLE_MATCHES='multiple_matches'
    QUANTITY_MISMATCH='quantity_mismatch'
    NATIVE_LINK_PRESENT='native_link_present'
    UNKNOWN_CATEGORY='unknown_category'


@dataclass(frozen=True)
class Line:
    record_id: str
    key: str
    prefix: str
    item_no: str
    qty: dict[str, Decimal | None]
    names: dict[str, str]
    native_case_present: bool=False


@dataclass(frozen=True)
class Item:
    record_id: str
    key: str
    category: str
    name: str
    base_qty: Decimal | None
    native_line_ids: tuple[str, ...]=()
    native_link_present: bool=False


@dataclass(frozen=True)
class Confirmation:
    record_id: str
    code_key: str


@dataclass(frozen=True)
class LineCase:
    line_id: str
    confirmation_id: str | None
    status: Status
    reason: Reason


@dataclass(frozen=True)
class ItemLink:
    item_id: str
    line_id: str | None
    status: Status
    reason: Reason
    candidate_ids: tuple[str, ...]=()
    same_quantity: bool=False


@dataclass(frozen=True)
class Parsed:
    lines: tuple[Line, ...]
    items: tuple[Item, ...]
    confirmations: tuple[Confirmation, ...]


@dataclass(frozen=True)
class Projection:
    plans: dict
    status: dict


def code_key(value):
    return ''.join(normalized_case(value).split()).upper()


def name_key(value):
    return ''.join(normalized_case(value).split())


def quantity(value):
    try:
        result=Decimal(text(value).strip())
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def record_key(row):
    return '/'.join(row[k] for k in ('base_token','table_id','record_id'))


def native_refs(value,table=None):
    if isinstance(value,list):
        return list(dict.fromkeys(ref for v in value for ref in native_refs(v,table)))
    if isinstance(value,dict):
        table=value.get('table_id') or table
        ident=value.get('record_id') or value.get('id')
        if isinstance(ident,str): return [(table,ident)]
        return native_refs(value.get('record_ids',value.get('link_record_ids')),table)
    if isinstance(value,str) and value.startswith('rec'): return [(table,value)]
    return []


def parse_records(records):
    lines=[];items=[];confirmations=[]
    contracts=defaultdict(list)
    for r in records:
        if r.get('kind')=='contract': contracts[(r['base_token'],r['record_id'])].append(r)
    for r in records:
        f=r['fields'];ident=record_key(r);kind=r.get('kind');key=code_key(f.get('工編號碼'))
        if kind=='contract':
            prefix,separator,item_no=key.rpartition('-')
            lines.append(Line(ident,key,prefix if separator else '',item_no if separator else '',
                {c:quantity(f.get(q)) for c,(q,n) in CATEGORY_FIELDS.items()},
                {c:name_key(f.get(n)) for c,(q,n) in CATEGORY_FIELDS.items()},bool(native_refs(f.get(NATIVE_CASE_FIELD)))))
        elif kind=='reporting':
            refs=native_refs(f.get(NATIVE_ITEM_FIELD),r.get('linked_tables',{}).get(NATIVE_ITEM_FIELD));targets=[]
            for table,ref in refs:
                candidates=[c for c in contracts[(r['base_token'],ref)] if not table or c['table_id']==table]
                if len(candidates)==1: targets.append(record_key(candidates[0]))
            # Missing native targets remain unresolved instead of falling back to a code match.
            native_ids=tuple(sorted(targets)) if len(targets)==len(refs) else ()
            name=text(f.get('填報工項')).rsplit('|',1)[-1] or text(f.get('工項名稱'))
            items.append(Item(ident,key,name_key(f.get('工項類別')),name_key(name),quantity(f.get('基準數量')),native_ids,bool(refs)))
        elif kind=='confirmation':
            confirmations.append(Confirmation(ident,code_key(f.get('工程確認單編號'))))
    return Parsed(tuple(lines),tuple(items),tuple(confirmations))


def resolve_line(line,confirmations):
    candidates=[c.record_id for c in confirmations if line.prefix and c.code_key==line.prefix]
    status=Status.UNIQUE if len(candidates)==1 else Status.AMBIGUOUS if candidates else Status.NONE
    reason=Reason.NO_CODE if not line.key else Reason.EXACT_MATCH if len(candidates)==1 else Reason.MULTIPLE_MATCHES if candidates else Reason.NO_MATCH
    return LineCase(line.record_id,candidates[0] if len(candidates)==1 else None,status,reason)


def resolve_item(item,lines,*,ignore_native=False):
    reason=None
    if item.native_link_present and not ignore_native: reason=Reason.NATIVE_LINK_PRESENT
    elif not item.key: reason=Reason.NO_CODE
    elif item.category not in CATEGORY_FIELDS: reason=Reason.UNKNOWN_CATEGORY
    elif not item.name: reason=Reason.NO_NAME
    if reason: return ItemLink(item.record_id,None,Status.NONE,reason)
    candidates=[l for l in lines if l.key==item.key and l.qty[item.category] is not None and item.name in l.names[item.category]]
    before=bool(candidates)
    if item.base_qty is not None and item.base_qty>0:
        candidates=[l for l in candidates if l.qty[item.category]==item.base_qty]
    candidates.sort(key=lambda l:l.record_id)
    status=Status.UNIQUE if len(candidates)==1 else Status.AMBIGUOUS if candidates else Status.NONE
    reason=Reason.EXACT_MATCH if len(candidates)==1 else Reason.MULTIPLE_MATCHES if candidates else Reason.QUANTITY_MISMATCH if before else Reason.NO_MATCH
    return ItemLink(item.record_id,candidates[0].record_id if len(candidates)==1 else None,status,reason,
                    tuple(l.record_id for l in candidates),bool(candidates) and len({l.qty[item.category] for l in candidates})==1)


def build_projection(records,confirmation_projects,native_line_projects,*,native_item_projects=None):
    parsed=parse_records(records);line_projects=dict(native_line_projects);derived=0
    for line in parsed.lines:
        if line.record_id in line_projects or line.native_case_present: continue
        result=resolve_line(line,parsed.confirmations)
        pid=confirmation_projects.get(result.confirmation_id) if result.status==Status.UNIQUE else None
        if pid: line_projects[line.record_id]=pid;derived+=1
    plans={};basis=Counter();native_item_projects=native_item_projects or {};dependencies=defaultdict(set)
    for line in parsed.lines:
        if pid:=line_projects.get(line.record_id): dependencies[pid].add(line.record_id)
    for confirmation in parsed.confirmations:
        if pid:=confirmation_projects.get(confirmation.record_id): dependencies[pid].add(confirmation.record_id)
    def plan(pid):
        if pid not in plans:
            plans[pid]=dict(rule_version=RULE_VERSION,basis=dict.fromkeys(('native','derived','ambiguous','unlinked'),0),
                categories={c:dict(lines=0,planned_qty=Decimal(0),items=0,items_native=0,items_derived=0,items_ambiguous=0,items_unlinked=0,needs_review=0) for c in CATEGORY_FIELDS},
                review_groups=[],items=[],truncated=False)
        return plans[pid]
    groups=defaultdict(list)
    for line in parsed.lines:
        for category in CATEGORY_FIELDS:
            if line.qty[category] is not None: groups[(line.key,category,line.names[category])].append(line)
    for (key,category,name),lines in sorted(groups.items()):
        for line in lines:
            pid=line_projects.get(line.record_id)
            if not pid: continue
            summary=plan(pid);counts=summary['categories'][category];counts['lines']+=1
            if len(lines)>1: counts['needs_review']+=1
            else: counts['planned_qty']+=line.qty[category]
        if len(lines)>1:
            for pid in {line_projects[l.record_id] for l in lines if l.record_id in line_projects}:
                plan(pid)['review_groups'].append(dict(key=key,category=category,line_ids=sorted(l.record_id for l in lines if line_projects.get(l.record_id)==pid)))
    for item in sorted(parsed.items,key=lambda i:i.record_id):
        result=resolve_item(item,parsed.lines);line_id=result.line_id
        if item.native_link_present:
            item_basis='native';line_id=item.native_line_ids[0] if len(item.native_line_ids)==1 else None
            pids={line_projects.get(l) for l in item.native_line_ids} if line_id else set()
        else:
            item_basis={Status.UNIQUE:'derived',Status.AMBIGUOUS:'ambiguous',Status.NONE:'unlinked'}[result.status]
            pids={line_projects.get(l) for l in result.candidate_ids}
        basis[item_basis]+=1
        pid=(next(iter(pids)) if len(pids)==1 and None not in pids else None) if pids else native_item_projects.get(item.record_id)
        if not pid: continue
        dependencies[pid].update((item.record_id,*(item.native_line_ids if item.native_link_present else result.candidate_ids)))
        summary=plan(pid);summary['basis'][item_basis]+=1
        if item.category in CATEGORY_FIELDS:
            counts=summary['categories'][item.category];counts['items']+=1;counts['items_'+item_basis]+=1
        summary['items'].append(dict(id=item.record_id,category=item.category,line_id=line_id,basis=item_basis,reason=result.reason.value))
    for summary in plans.values():
        for counts in summary['categories'].values(): counts['planned_qty']=str(counts['planned_qty'])
        rows=summary['items'];summary['items']=rows[:MAX_ROWS];summary['truncated']=len(rows)>MAX_ROWS
        # Bound both review groups and item rows because source text can be arbitrarily long.
        while len(json.dumps(summary,ensure_ascii=False,separators=(',',':')).encode())>MAX_BYTES:
            summary['truncated']=True
            if summary['items']: summary['items'].pop()
            elif summary['review_groups']: summary['review_groups'].pop()
            else: break
    for pid,summary in plans.items(): summary['_source_ids']=sorted(dependencies[pid])
    return Projection(plans,dict(lines_total=len(parsed.lines),lines_derived=derived,
        lines_unmatched=sum(l.record_id not in line_projects for l in parsed.lines),
        **{'items_'+k:basis[k] for k in ('native','derived','ambiguous','unlinked')}))


def plan_summary(state,pid):
    from copy import deepcopy
    summary=deepcopy((state.get('derived_plan') or {}).get(pid))
    if summary is not None: summary.pop('_source_ids',None)
    return summary
