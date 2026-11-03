"""Small freshness rows: never deserialize retained attendance/source snapshots."""
import json
from sqlalchemy import JSON, column, func, select
from ..json_read_projection import json_fields

FIELDS = ('as_of', 'fetched_at', 'changed_at', 'last_error', 'error_code',
          'missing_scopes', 'lease_until', 'lark')


def read_status_rows(db, model, keys):
    dialect = db.get_bind().dialect.name
    if dialect == 'postgresql':
        fields = func.json_to_record(model.data).table_valued(
            *(column(key, JSON) for key in FIELDS), joins_implicitly=True
        ).render_derived(name='read_status', with_types=True)
        rows = db.execute(select(model.id, *(fields.c[key] for key in FIELDS))
                          .select_from(model, fields).where(model.id.in_(keys)))
        return {row[0]: dict(zip(FIELDS, row[1:])) for row in rows}
    projection = json_fields(model.data, FIELDS, dialect)
    return {key: json.loads(data) if isinstance(data, str) else data
            for key, data in db.execute(select(model.id, projection).where(model.id.in_(keys)))}
