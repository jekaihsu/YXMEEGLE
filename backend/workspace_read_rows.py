"""Full tree reads with compact source facts for the assigned Home panel.

Tree and authority collections retain their ordinary SQL/order. Large imported
source histories never cross the SQL boundary; only the case evidence fields do.
"""
import json
from sqlalchemy import Text, cast, select, case


def read_rows(db, model, row, omitted, case_sources):
    from .case_source_reads import CASE_SOURCE_FIELDS
    from .json_read_projection import json_fields
    from .request_timing import measure
    dialect = db.get_bind().dialect.name
    if dialect not in ('sqlite', 'postgresql'):
        value = model.data
    else:
        compact = json_fields(model.data, CASE_SOURCE_FIELDS, dialect)
        value = case((model.kind.in_(('source_quotes','source_confirmations','contract_items')), compact), else_=model.data)
    # A text cast gives both dialects the same explicit decode boundary.
    query = select(model.kind, model.entity_id, model.parent_id, model.ordinal, cast(value, Text)).where(
        model.workspace_id == row.id, model.kind.notin_(('migration_archive', *omitted))).order_by(model.ordinal)
    with measure('homerows'):
        for kind, ident, parent, ordinal, payload in db.execute(query):
            yield kind, ident, parent, ordinal, json.loads(payload)
