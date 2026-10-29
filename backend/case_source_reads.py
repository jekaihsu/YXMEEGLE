"""Compact source projections for case and source-health reads."""
from sqlalchemy import case, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB, array

CASE_SOURCE_FIELDS=('id','source_identity','source_url','url','source_kind','source_missing',
    'project_id','linked_project_id','project_ids','review_project_ids','review_quote_id',
    'code','quote_code','engineering_code','parent_code','code_history','fields',
    'confirmation_ids','unresolved_confirmation_ids','quote_ids','unresolved_quote_ids',
    'contract_ids','reporting_ids','task_refs','title','item_number')


def json_fields(column, fields, dialect="sqlite"):
    """JSON projection preserving absent keys, booleans and nested values."""
    if dialect == 'postgresql':
        parts=func.jsonb_each(cast(column,JSONB)).table_valued('key','value',joins_implicitly=True)
        return select(func.coalesce(func.jsonb_object_agg(parts.c.key,parts.c.value),cast({},JSONB))).where(parts.c.key.in_(fields)).scalar_subquery()
    parts=func.json_each(column).table_valued('key','value','type',joins_implicitly=True)
    value=case((parts.c.type=='true','true'),(parts.c.type=='false','false'),
               (parts.c.type=='null','null'),(parts.c.type=='text',func.json_quote(parts.c.value)),
               else_=parts.c.value)
    return select(func.json_group_object(parts.c.key,func.json(value))).where(parts.c.key.in_(fields)).scalar_subquery()


def case_source_data(model, project_ids, dialect="sqlite", *, quote_facts=False):
    from .source_case_policy import CODE_FIELDS
    compact=json_fields(model.data,CASE_SOURCE_FIELDS,dialect)
    # Unrelated confirmations and quotations still supply the complete redaction
    # universe, but their source values and history are not case inputs.
    metadata=(func.jsonb_set(compact,array(['fields']),json_fields(model.data['fields'],CODE_FIELDS,dialect)) if dialect=='postgresql' else func.json_set(compact,'$.fields',func.json(json_fields(model.data['fields'],CODE_FIELDS))))
    if quote_facts:
        from .sop_import.quote_facts import DATE_FIELDS, TEXT_FIELDS
        from .sources import QUOTE_POINT_FIELDS
        fields=tuple(dict.fromkeys((*CODE_FIELDS,*DATE_FIELDS.values(),*TEXT_FIELDS.values(),*QUOTE_POINT_FIELDS,
            '編號','狀態 (1)','狀態','此案確認單','契約價格(未稅)','契約價格(含稅)',
            '外業負責組別','外業期限','案件已入帳')))
        quote=(func.jsonb_set(compact,array(['fields']),json_fields(model.data['fields'],fields,dialect)) if dialect=='postgresql' else func.json_set(compact,'$.fields',func.json(json_fields(model.data['fields'],fields))))
    else:
        quote=metadata
    return case((model.kind=='source_quotes',quote),
        ((model.kind=='source_confirmations') & ~func.coalesce(model.data['project_id'].as_string().in_(project_ids),False),metadata),
        else_=compact)


def cached_rows(db, model, workspace, selected, project_ids, *, filter_project_rows=False, quote_facts=False):
    """Project one version once, outside PostgreSQL's per-row JSONB casts.

    The cache contains source data only. Each caller still loads authority and
    applies visibility against its own fresh workspace and person records.
    """
    import json
    from sqlalchemy import Text
    from . import shared_reads
    from .source_case_policy import CODE_FIELDS
    from .storage import READ_PROJECT_LINKED
    from .sop_import.quote_facts import DATE_FIELDS, TEXT_FIELDS
    from .sources import QUOTE_POINT_FIELDS
    policy_fields=set((*CODE_FIELDS,*DATE_FIELDS.values(),*TEXT_FIELDS.values(),*QUOTE_POINT_FIELDS,
        '編號','狀態 (1)','狀態','此案確認單','契約價格(未稅)','契約價格(含稅)',
        '外業負責組別','外業期限','案件已入帳'))
    key=(workspace.id,workspace.version,tuple(sorted(selected)),None,'case_source_rows')
    def fetch():
        query=select(model.kind,cast(model.data,Text)).where(model.workspace_id==workspace.id,
            model.kind.in_(selected),model.parent_id=='').order_by(model.ordinal)
        result=[]
        for kind,payload in db.execute(query):
            value=json.loads(payload)
            value={k:v for k,v in value.items() if k in CASE_SOURCE_FIELDS}
            if kind=='source_quotes':
                value['fields']={k:v for k,v in (value.get('fields') or {}).items() if k in policy_fields}
            result.append((kind,json.dumps(value,ensure_ascii=False,separators=(',',':'))))
        return result
    rows=shared_reads.rows(key,fetch)
    scoped=set(project_ids or ())
    for kind,payload in rows:
        value=json.loads(payload)
        if filter_project_rows and project_ids is not None and kind in READ_PROJECT_LINKED:
            if value.get('project_id') is not None and value['project_id'] not in scoped:
                continue
        if kind=='source_quotes' and not quote_facts or kind=='source_confirmations' and value.get('project_id') not in scoped:
            value['fields']={k:v for k,v in (value.get('fields') or {}).items() if k in CODE_FIELDS}
        yield kind,json.dumps(value,ensure_ascii=False,separators=(',',':'))
