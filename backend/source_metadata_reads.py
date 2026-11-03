"""Source health identities, projected in SQL on both supported databases."""
import json
from sqlalchemy import func, select


def read_metadata(db, model, wid):
    from .json_read_projection import json_fields
    from .request_timing import measure
    dialect = db.get_bind().dialect.name
    with measure('sourcemetadata'):
        metadata = db.scalar(select(json_fields(model.data,
            ('status','authorized','last_sync','last_attempt_at','tables'), dialect)).where(model.id == wid))
        if metadata is None:
            return None
        snapshot = json.loads(metadata) if isinstance(metadata, str) else metadata
        if dialect == 'postgresql':
            records = func.json_array_elements(model.data['records']).table_valued('value', joins_implicitly=True)
        else:
            records = func.json_each(model.data, '$.records').table_valued('value', joins_implicitly=True)
        rows = db.scalars(select(json_fields(records.c.value,
            ('base_token','table_id','record_id'), dialect)).select_from(model, records).where(model.id == wid))
        snapshot['records'] = [json.loads(row) if isinstance(row, str) else row for row in rows]
        return snapshot
