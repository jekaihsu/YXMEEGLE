"""Project native PostgreSQL JSON without converting a large document to JSONB."""
from sqlalchemy import JSON, cast, func, select


def json_fields(column, fields, dialect='sqlite'):
    if dialect != 'postgresql':
        from .case_source_reads import json_fields as sqlite_fields
        return sqlite_fields(column, fields, dialect)
    parts = func.json_each(column).table_valued('key', 'value', joins_implicitly=True)
    return select(func.coalesce(func.json_object_agg(parts.c.key, parts.c.value), cast({}, JSON))).where(
        parts.c.key.in_(fields)).scalar_subquery()
