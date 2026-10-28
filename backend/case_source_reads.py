"""Compact SQLite source projections for case and source-health reads."""
from sqlalchemy import case, func, select

CASE_SOURCE_FIELDS=('id','source_identity','source_url','url','source_kind','source_missing',
    'project_id','linked_project_id','project_ids','review_project_ids','review_quote_id',
    'code','quote_code','engineering_code','parent_code','code_history','fields',
    'confirmation_ids','unresolved_confirmation_ids','quote_ids','unresolved_quote_ids',
    'contract_ids','reporting_ids','task_refs','title','item_number')


def json_fields(column, fields):
    """SQLite JSON projection preserving absent keys, booleans and nested values."""
    parts=func.json_each(column).table_valued('key','value','type',joins_implicitly=True)
    value=case((parts.c.type=='true','true'),(parts.c.type=='false','false'),
               (parts.c.type=='null','null'),(parts.c.type=='text',func.json_quote(parts.c.value)),
               else_=parts.c.value)
    return select(func.json_group_object(parts.c.key,func.json(value))).where(parts.c.key.in_(fields)).scalar_subquery()


def case_source_data(model, project_ids):
    from .source_case_policy import CODE_FIELDS
    compact=json_fields(model.data,CASE_SOURCE_FIELDS)
    # Unrelated confirmations and quotations still supply the complete redaction
    # universe, but their source values and history are not case inputs.
    metadata=func.json_set(compact,'$.fields',func.json(json_fields(model.data['fields'],CODE_FIELDS)))
    return case((model.kind=='source_quotes',metadata),
        ((model.kind=='source_confirmations') & ~func.coalesce(model.data['project_id'].as_string().in_(project_ids),False),metadata),
        else_=compact)
