"""Source health identities, projected in SQL on both supported databases."""
import json
from sqlalchemy import func, select


def read_metadata(db, model, wid):
    from .json_read_projection import json_fields
    from .request_timing import measure
    dialect = db.get_bind().dialect.name
    with measure('sourcemetadata'):
        if dialect == 'postgresql':
            return _postgres_metadata(db, model, wid)
        metadata = db.scalar(select(json_fields(model.data,
            ('status','authorized','last_sync','last_attempt_at','tables'), dialect)).where(model.id == wid))
        if metadata is None:
            return None
        snapshot = json.loads(metadata) if isinstance(metadata, str) else metadata
        records = func.json_each(model.data, '$.records').table_valued('value', joins_implicitly=True)
        rows = db.scalars(select(json_fields(records.c.value,
            ('base_token','table_id','record_id'), dialect)).select_from(model, records).where(model.id == wid))
        snapshot['records'] = [json.loads(row) if isinstance(row, str) else row for row in rows]
        return snapshot


def _postgres_metadata(db, model, wid):
    from sqlalchemy import JSON, column
    names = ('status', 'authorized', 'last_sync', 'last_attempt_at', 'tables')
    fields = func.json_to_record(model.data).table_valued(
        *(column(key, JSON) for key in names), joins_implicitly=True
    ).render_derived(name='source_health', with_types=True)
    row = db.execute(select(*(fields.c[key] for key in names))
                     .select_from(model, fields).where(model.id == wid)).first()
    if row is None:
        return None
    snapshot = dict(zip(names, row))
    identities = ('base_token', 'table_id', 'record_id')
    records = func.json_to_recordset(model.data['records']).table_valued(
        *(column(key, JSON) for key in identities), joins_implicitly=True
    ).render_derived(name='source_identities', with_types=True)
    snapshot['records'] = [dict(zip(identities, row)) for row in db.execute(
        select(*(records.c[key] for key in identities)).select_from(model, records).where(model.id == wid))]
    return snapshot


GENERATION_FIELDS = ('status','last_attempt_at','last_sync','as_of')


def read_generation(db, model, wid):
    """Project all four fence values once, preserving their JSON value types."""
    from sqlalchemy import JSON, column
    from .request_timing import measure
    dialect = db.get_bind().dialect.name
    with measure('sourcefence'):
        if dialect == 'postgresql':
            fields = func.json_to_record(model.data).table_valued(
                *(column(key, JSON) for key in GENERATION_FIELDS), joins_implicitly=True
            ).render_derived(name='source_fence', with_types=True)
            row = db.execute(select(*(fields.c[key] for key in GENERATION_FIELDS))
                .select_from(model, fields).where(model.id == wid)).first()
            return tuple(row) if row else (None,) * len(GENERATION_FIELDS)
        value = db.scalar(select(func.json_extract(model.data,
            *('$.' + key for key in GENERATION_FIELDS))).where(model.id == wid))
        return tuple(json.loads(value)) if value is not None else (None,) * len(GENERATION_FIELDS)


def read_workspace_generation(db, model, workspace_model, wid):
    """Read the workspace and source fence in one database statement."""
    from sqlalchemy import JSON, column
    from .request_timing import measure
    dialect = db.get_bind().dialect.name
    with measure('sourcefence'):
        if dialect == 'postgresql':
            fields = func.json_to_record(model.data).table_valued(
                *(column(key, JSON) for key in GENERATION_FIELDS), joins_implicitly=True
            ).render_derived(name='source_fence', with_types=True)
            source = select(model.id, *(fields.c[key] for key in GENERATION_FIELDS)).select_from(
                model, fields).where(model.id == wid).subquery()
            row = db.execute(select(workspace_model.version, *(source.c[key] for key in GENERATION_FIELDS))
                .outerjoin(source, workspace_model.id == source.c.id).where(workspace_model.id == wid)).first()
            return tuple(row) if row else (None,) * 5
        source = select(model.id, func.json_extract(model.data,
            *('$.' + key for key in GENERATION_FIELDS)).label('generation')).where(model.id == wid).subquery()
        row = db.execute(select(workspace_model.version, source.c.generation)
            .outerjoin(source, workspace_model.id == source.c.id).where(workspace_model.id == wid)).first()
        return (row[0], *(json.loads(row[1]) if row[1] is not None else (None,) * 4)) if row else (None,) * 5
