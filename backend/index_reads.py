"""Reads served from the derived index tables (VCC-98). Core statements only: SQLite and PostgreSQL.

Every reader first asks ready(); when the index is off, empty or behind the workspace
version the caller falls back to the legacy full-load path, so the index is never the
source of truth for an answer it cannot vouch for.
"""
from sqlalchemy import select, func
from . import index_tables

VISIBLE_CASES=('new_case','source_reference')


def ready(db,model,row):
    """Index maintained (flag on) and complete for exactly this workspace version."""
    if not db.info.get('index_tables'): return False
    pi,_,ci=index_tables.tables(model)
    total=db.execute(select(ci.c.value,ci.c.source_version).where(ci.c.workspace_id==row.id,ci.c.key=='projects_total',ci.c.subject_id=='')).first()
    if total is None or total.source_version!=row.version: return False
    return db.scalar(select(func.count()).select_from(pi).where(pi.c.workspace_id==row.id))==total.value


def visibility(pi,environment):
    """SQL twin of source_case_policy.visible_project: isolated environments show every case."""
    return [] if environment in ('test','demo') else [pi.c.case_visibility.in_(VISIBLE_CASES)]
