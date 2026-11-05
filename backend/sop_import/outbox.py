from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from .models import LocalTask, LarkOutbox


def latest(db, wid, pid, tid):
    return db.scalar(select(LarkOutbox).where(LarkOutbox.workspace_id == wid, LarkOutbox.project_id == pid,
                                            LarkOutbox.task_id == tid).order_by(LarkOutbox.generation.desc()).limit(1).execution_options(populate_existing=True))


def enqueue(db, wid, pid, tid, *, resume=False):
    connection = db.connection()
    table = LarkOutbox.__table__
    where = (table.c.workspace_id == wid, table.c.project_id == pid, table.c.task_id == tid)
    revision, snapshot = connection.execute(select(LocalTask.revision, LocalTask.snapshot).where(
        LocalTask.workspace_id == wid, LocalTask.project_id == pid, LocalTask.id == tid)).one()
    if snapshot.get('test_fixture') is True:
        return False
    current = connection.execute(select(table).where(*where).order_by(table.c.generation.desc()).limit(1)).mappings().first()
    if current:
        resume = resume and current['last_error'] != 'canary_cleanup'
        # A sent create must retain its identity until recovery has established its outcome.
        connection.execute(table.update().where(*where, table.c.generation == current['generation']).values(
            target_revision=revision, state='paused' if current['state'] == 'paused' and not resume else 'sent' if current['state'] == 'sent' else 'none',
            last_error=None if resume else current['last_error'], retry_at=0))
    else:
        insert = sqlite_insert if connection.dialect.name == 'sqlite' else pg_insert
        connection.execute(insert(table).values(workspace_id=wid, project_id=pid, task_id=tid, generation=1,
                                                target_revision=revision, state='none', retry_at=0, attempts=0, drift=False)
                           .on_conflict_do_nothing())

    return True


def enqueue_all(sessions):
    with sessions.begin() as db:
        tasks = list(db.scalars(select(LocalTask)))
        return sum(enqueue(db, task.workspace_id, task.project_id, task.id, resume=True) for task in tasks)
