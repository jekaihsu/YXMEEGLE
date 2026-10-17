"""Reads served from the derived index tables (VCC-98). Core statements only: SQLite and PostgreSQL.

Every reader first asks ready(); when the index is off, empty or behind the workspace
version the caller falls back to the legacy full-load path, so the index is never the
source of truth for an answer it cannot vouch for.
"""
from sqlalchemy import select, func, case
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


def _binary(column,db):
    """Code-point ordering like Python's sort; PostgreSQL otherwise sorts by locale collation."""
    return column.collate('C') if db.bind.dialect.name=='postgresql' else column


def casefold_safe(q):
    """True when lower() agrees with str.casefold() for q, so LIKE can stand in for the legacy substring test."""
    return all(ch.isascii() or ch.lower()==ch.upper() for ch in q)


def search(pi,q):
    """Substring match over code, name and client, with LIKE wildcards in q taken literally."""
    needle=q.lower().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
    return func.lower(pi.c.code+' '+pi.c.name+' '+pi.c.client).like('%'+needle+'%',escape='\\')


def project_page(db,model,wid,environment,*,q='',status='',owner='',offset=0,limit=30):
    """Legacy /api/projects body: filter, sort (due_date or '9999', id), count and slice in SQL.

    Only the seven response columns of the requested page are read.
    """
    pi,*_=index_tables.tables(model)
    where=[pi.c.workspace_id==wid,*visibility(pi,environment)]
    if status: where.append(pi.c.status==status)
    if owner: where.append(pi.c.pm_id==owner)
    if q: where.append(search(pi,q))
    total=db.scalar(select(func.count()).select_from(pi).where(*where))
    due=case((pi.c.due_date=='','9999'),else_=pi.c.due_date)
    rows=db.execute(select(pi.c.project_id,pi.c.code,pi.c.name,pi.c.status,pi.c.source_status,pi.c.pm_id,pi.c.due_date).where(*where)
                    .order_by(_binary(due,db),_binary(pi.c.project_id,db)).limit(limit).offset(offset)).all()
    return {'total':total,'offset':offset,'limit':limit,'items':[dict(id=r.project_id,code=r.code,name=r.name,status=r.status,source_status=r.source_status or None,pm_id=r.pm_id,due_date=r.due_date or None) for r in rows]}
