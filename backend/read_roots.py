"""Request-local root decoding; every reuse first checks the database revision.

No authority or ORM objects survive a request. Callers receive a read-only root
carrier and continue to load person/admission and visibility facts normally.
"""
from types import SimpleNamespace
from sqlalchemy import select


def read_root(db, model, wid):
    from .request_timing import _current, measure
    timing = _current.get()
    if timing is None or timing.method != 'GET' or db.new or db.dirty or db.deleted:
        return db.get(model, wid)
    with measure('rootread'):
        version = db.scalar(select(model.version).where(model.id == wid))
        if version is None:
            return None
        key = (db.get_bind(), wid, version)
        roots = getattr(timing, 'read_roots', None)
        if roots is None:
            roots = timing.read_roots = {}
        if key not in roots:
            # Read revision and payload together: a commit between the scalar
            # probe and this SELECT must never label newer JSON as an old root.
            row = db.execute(select(model.id, model.version, model.data).where(model.id == wid)).first()
            if row is None:
                return None
            root = SimpleNamespace(id=row.id, version=row.version, data=row.data)
            roots[(db.get_bind(), wid, row.version)] = root
            return root
        return roots[key]


def read_root_header(db, model, wid):
    """Snapshot key admission needs the revision/schema, never the root plans."""
    row = db.execute(select(model.id, model.version, model.data['storage_schema'].as_integer().label('schema')).where(model.id == wid)).first()
    return SimpleNamespace(id=row.id, version=row.version, data={'storage_schema':row.schema}) if row else None
