"""Question accounting and bounded, manager-readable exchanges."""
from datetime import datetime, timezone, timedelta
import json
import re
from threading import Lock, Thread
from time import monotonic
import logging
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text, CheckConstraint, func, select, case, and_, or_, delete, update, inspect, true, union
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.schema import CreateColumn
from ..models import Base

TAIPEI = ZoneInfo('Asia/Taipei')
logger = logging.getLogger(__name__)

STALE_ACTIVE_RUN_SECONDS = 24 * 60 * 60
GENERATION_PRUNE_GRACE_SECONDS = 10 * 60


class AiUsageRow(Base):
    __tablename__ = 'ai_usage'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at = Column(DateTime(timezone=True), nullable=False)
    day = Column(String(10), nullable=False, index=True)
    workspace_id = Column(String(120), nullable=False)
    actor_id = Column(String(120), nullable=False, index=True)
    actor_name = Column(String(240), nullable=False)
    conversation_id = Column(String(120), nullable=False)
    provider = Column(String(16), nullable=False)
    scope = Column(String(16), nullable=False, default='global', server_default='global')
    project_id = Column(String(200), nullable=True)
    authz_version = Column(Integer, nullable=True)
    permission_key = Column(String(64), nullable=True)
    provenance_version = Column(Integer, nullable=True)
    model = Column(String(120), nullable=False)
    effort = Column(String(24), nullable=False)
    input_tokens = Column(BigInteger, nullable=False)
    cache_read_tokens = Column(BigInteger, nullable=False)
    cache_write_tokens = Column(BigInteger, nullable=False)
    output_tokens = Column(BigInteger, nullable=False)
    cost_micro_usd = Column(BigInteger, nullable=True)
    price_version = Column(String(120), nullable=False)
    steps = Column(Integer, nullable=False)
    tool_calls = Column(Integer, nullable=False)
    latency_ms = Column(Integer, nullable=False)
    first_token_ms = Column(Integer, nullable=True)
    status = Column(String(16), nullable=False)
    error_code = Column(String(64), nullable=True)


class AiCaseRead(Base):
    """Per-tool provenance retained for audit; conversation tables authorize reads."""
    __tablename__ = 'ai_case_read'
    usage_id = Column(String(36), primary_key=True)
    tool_call_id = Column(String(120), primary_key=True)
    project_id = Column(String(200), primary_key=True)


class AiWorkspaceRead(Base):
    """Per-turn workspace provenance for audit, bounded by content retention."""
    __tablename__ = 'ai_workspace_read'
    usage_id = Column(String(36), primary_key=True)
    marker = Column(String(80), primary_key=True)


class AiConversationCaseRead(Base):
    __tablename__ = 'ai_conversation_case_read'
    workspace_id = Column(String(120), primary_key=True)
    actor_id = Column(String(120), primary_key=True)
    conversation_id = Column(String(120), primary_key=True)
    project_id = Column(String(200), primary_key=True)


class AiConversationWorkspaceRead(Base):
    __tablename__ = 'ai_conversation_workspace_read'
    workspace_id = Column(String(120), primary_key=True)
    actor_id = Column(String(120), primary_key=True)
    conversation_id = Column(String(120), primary_key=True)
    marker = Column(String(80), primary_key=True)


class AiSchemaMigration(Base):
    __tablename__ = 'ai_schema_migration'
    name = Column(String(120), primary_key=True)
    completed_at = Column(DateTime(timezone=True), nullable=False)


CONVERSATION_READ_BACKFILL = 'conversation-read-authority-v1'
USAGE_CONVERSATION_INDEX = 'ix_ai_usage_conversation'



def insert_once(db, table):
    if db.get_bind().dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(table)


def delete_read_metadata(db, ids):
    for model in (AiCaseRead, AiWorkspaceRead):
        db.execute(delete(model).where(model.usage_id.in_(ids)))


def delete_unused_conversation_metadata(db):
    g,u,e = AiConversationGeneration,AiUsageRow,AiExchangeRow
    for c in (AiConversationCaseRead,AiConversationWorkspaceRead):
        retained = select(u.id).join(e,e.usage_id == u.id).where(u.workspace_id == c.workspace_id,
            u.actor_id == c.actor_id,u.conversation_id == c.conversation_id).exists()
        active = select(g.conversation_id).where(g.workspace_id == c.workspace_id,g.actor_id == c.actor_id,
            g.conversation_id == c.conversation_id,g.active_runs > 0,
            g.last_activity_at >= datetime.now(timezone.utc)-timedelta(seconds=STALE_ACTIVE_RUN_SECONDS)).exists()
        db.execute(delete(c).where(~retained,~active))


class AiExchangeRow(Base):
    __tablename__ = 'ai_exchange'
    usage_id = Column(String(36), primary_key=True)
    workspace_id = Column(String(120), nullable=False)
    actor_id = Column(String(120), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    tool_names = Column(Text, nullable=False)
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)


class AiConversationGeneration(Base):
    __tablename__ = 'ai_conversation_generation'
    workspace_id = Column(String(120), primary_key=True)
    actor_id = Column(String(120), primary_key=True)
    conversation_id = Column(String(120), primary_key=True)
    generation = Column(Integer, nullable=False, default=0)
    active_runs = Column(Integer, nullable=False, default=0, server_default='0')
    last_activity_at = Column(DateTime(timezone=True), nullable=True, default=lambda: datetime.now(timezone.utc))


def lock_generation(db, workspace_id, actor_id, conversation_id, *, starting=False):
    if db.get_bind().dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    table = AiConversationGeneration
    statement = insert(table).values(workspace_id=workspace_id, actor_id=actor_id,
        conversation_id=conversation_id, generation=0, active_runs=1 if starting else 0,
        last_activity_at=datetime.now(timezone.utc))
    statement = statement.on_conflict_do_update(
        index_elements=['workspace_id', 'actor_id', 'conversation_id'],
        set_={'active_runs': table.active_runs + (1 if starting else 0),
              'last_activity_at': statement.excluded.last_activity_at})
    return db.scalar(statement.returning(table.generation))


def conversation_generation(sessions, workspace_id, actor_id, conversation_id):
    with sessions.begin() as db:
        return lock_generation(db, workspace_id, actor_id, conversation_id, starting=True)


def release_conversation(sessions, workspace_id, actor_id, conversation_id):
    with sessions.begin() as db:
        table = AiConversationGeneration
        db.execute(update(table).where(table.workspace_id == workspace_id, table.actor_id == actor_id,
            table.conversation_id == conversation_id, table.active_runs > 0).values(active_runs=table.active_runs - 1,
                last_activity_at=datetime.now(timezone.utc)))


def stores_content(cfg):
    value = str(cfg.get('AI_STORE_CONTENT', 'true')).strip().lower()
    if value not in ('true', '1', 'yes', 'on', 'false', '0', 'no', 'off'):
        logger.warning('Invalid AI_STORE_CONTENT; content storage disabled')
    return value in ('true', '1', 'yes', 'on')


def content_retention(cfg):
    try:
        days = int(cfg.get('AI_CONTENT_RETENTION_DAYS', 90))
        if days < 0:
            raise ValueError
        return days
    except (TypeError, ValueError):
        logger.warning('Invalid AI_CONTENT_RETENTION_DAYS; using 90 days')
        return 90


_SECRET = re.compile(
    r'\bsk-[A-Za-z0-9_-]{16,}|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'
    r'|\bAIza[A-Za-z0-9_-]{20,}|\bghp_[A-Za-z0-9]+|\bxox[bapr]-[A-Za-z0-9-]+'
    r'|(?i:bearer\s+[^\s,;]+|\b(?:password|token|secret)\s*=\s*(?:"[^"\n]*"|\'[^\'\n]*\'|[^\s,;&]+))'
    r'|(?<!\d)09\d{2}[ -]?\d{3}[ -]?\d{3}(?!\d)|\b[A-Z][12]\d{8}\b'
    r'|(?<!\d)(?:\d{4}[ -]){3}\d{4}(?!\d)|\d{13,}')


def redact(text, limit):
    text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]', '', text)
    return _SECRET.sub('[redacted]', text)[:limit]


_cleanup_lock = Lock()
_last_cleanup = None
_cleanup_running = False


def cleanup_content(sessions, retention_days):
    global _last_cleanup, _cleanup_running
    with _cleanup_lock:
        if _cleanup_running or (_last_cleanup is not None and monotonic() - _last_cleanup < 3600):
            return
        _cleanup_running = True
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        while True:
            with sessions.begin() as db:
                ids = db.scalars(select(AiExchangeRow.usage_id).where(
                    AiExchangeRow.created_at < cutoff).limit(500)).all()
                if not ids:
                    break
                db.execute(delete(AiExchangeRow).where(AiExchangeRow.usage_id.in_(ids)))
                delete_read_metadata(db, ids)
        with sessions.begin() as db:
            g, u, e = AiConversationGeneration, AiUsageRow, AiExchangeRow
            retained = select(u.id).join(e, e.usage_id == u.id).where(
                u.workspace_id == g.workspace_id, u.actor_id == g.actor_id,
                u.conversation_id == g.conversation_id).exists()
            now = datetime.now(timezone.utc)
            db.execute(update(g).where(g.last_activity_at.is_(None)).values(last_activity_at=now))
            db.execute(delete(g).where(
                g.last_activity_at < now - timedelta(seconds=GENERATION_PRUNE_GRACE_SECONDS),
                or_(g.active_runs == 0,
                g.last_activity_at < now - timedelta(seconds=STALE_ACTIVE_RUN_SECONDS)), ~retained))
        with sessions.begin() as db:
            for metadata in (AiCaseRead,AiWorkspaceRead):
                u,g,e = AiUsageRow,AiConversationGeneration,AiExchangeRow
                retained = select(e.usage_id).where(e.usage_id == metadata.usage_id).exists()
                live = select(u.id).join(g,and_(g.workspace_id == u.workspace_id,g.actor_id == u.actor_id,
                    g.conversation_id == u.conversation_id)).where(u.id == metadata.usage_id,g.active_runs > 0,
                    g.last_activity_at >= datetime.now(timezone.utc)-timedelta(seconds=STALE_ACTIVE_RUN_SECONDS)).exists()
                db.execute(delete(metadata).where(~retained,~live))
            delete_unused_conversation_metadata(db)
        with _cleanup_lock:
            _last_cleanup = monotonic()
    finally:
        with _cleanup_lock:
            _cleanup_running = False


def schedule_cleanup(sessions, retention_days):
    def clean():
        try:
            cleanup_content(sessions, retention_days)
        except Exception:
            logger.error('ai_content_cleanup_failed')
    Thread(target=clean, daemon=True).start()


class AiFeedbackRow(Base):
    __tablename__ = 'ai_feedback'
    __table_args__ = (CheckConstraint('rating IN (1, -1)', name='ai_feedback_rating'),)
    usage_id = Column(String(36), primary_key=True)
    actor_id = Column(String(120), primary_key=True)
    rating = Column(Integer, nullable=False)
    reason = Column(String(24), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


def owns_usage(sessions, workspace_id, actor_id, usage_id):
    with sessions() as db:
        return db.scalar(select(AiUsageRow.id).where(
            AiUsageRow.id == usage_id, AiUsageRow.workspace_id == workspace_id,
            AiUsageRow.actor_id == actor_id)) is not None


def feedback_statement(dialect, usage_id, actor_id, rating, reason):
    if dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    now = datetime.now(timezone.utc)
    statement = insert(AiFeedbackRow).values(usage_id=usage_id, actor_id=actor_id,
        rating=rating, reason=reason, created_at=now, updated_at=now)
    return statement.on_conflict_do_update(index_elements=['usage_id', 'actor_id'],
        set_={k: getattr(statement.excluded, k) for k in ('rating', 'reason', 'updated_at')})


def feedback(sessions, usage_id, actor_id, rating, reason):
    with sessions.begin() as db:
        if rating == 'none':
            db.execute(delete(AiFeedbackRow).where(AiFeedbackRow.usage_id == usage_id,
                                                   AiFeedbackRow.actor_id == actor_id))
        else:
            db.execute(feedback_statement(db.get_bind().dialect.name, usage_id, actor_id,
                                          1 if rating == 'up' else -1, reason))


def today():
    return datetime.now(TAIPEI).date().isoformat()


def record(sessions, *, exchange=None, conversation_generation=None, case_reads=(), workspace_reads=(), **values):
    created = datetime.now(timezone.utc)
    values = dict(created_at=created, day=created.astimezone(TAIPEI).date().isoformat(), **values)
    values.setdefault('id', str(uuid4()))
    for attempt in range(2):
        try:
            with sessions.begin() as db:
                if db.get(AiUsageRow, values['id']) is None:
                    db.add(AiUsageRow(**values))
                    metadata_allowed = values.get('error_code') != 'ai_forbidden' and exchange is not None
                    if metadata_allowed and conversation_generation is not None:
                        metadata_allowed &= lock_generation(db, values['workspace_id'], values['actor_id'], values['conversation_id']) == conversation_generation
                    if metadata_allowed:
                        db.add_all(AiCaseRead(usage_id=values['id'], tool_call_id=call, project_id=project)
                                   for call, project in set(case_reads))
                        db.add_all(AiWorkspaceRead(usage_id=values['id'], marker=marker) for marker in set(workspace_reads))
                        key = {k:values[k] for k in ('workspace_id','actor_id','conversation_id')}
                        projects = {project for _,project in case_reads}
                        if values.get('scope') == 'project' and values.get('project_id'):
                            projects.add(values['project_id'])
                        for table,field,items in ((AiConversationCaseRead,'project_id',projects),
                                                 (AiConversationWorkspaceRead,'marker',set(workspace_reads))):
                            if items:
                                db.execute(insert_once(db,table).values([{**key,field:item} for item in sorted(items)]).on_conflict_do_nothing())
            break
        except Exception:
            if attempt == 1:
                logger.error('ai_usage_write_failed')
                return
    if exchange is None:
        return
    try:
        with sessions.begin() as db:
            current = lock_generation(db, values['workspace_id'], values['actor_id'], values['conversation_id'])
            if conversation_generation is not None and current != conversation_generation:
                return
            if db.get(AiExchangeRow, values['id']) is None:
                db.add(AiExchangeRow(usage_id=values['id'], workspace_id=values['workspace_id'],
                    actor_id=values['actor_id'], created_at=created,
                    question=redact(exchange['question'], 4000), answer=redact(exchange['answer'], 20000),
                    tool_names=json.dumps(exchange['tools'], ensure_ascii=False),
                    error_detail=redact(exchange['error_detail'], 200) if exchange['error_detail'] else None))
    except Exception:
        logger.error('ai_exchange_write_failed')


def daily_tokens(sessions, workspace_id, actor_id):
    with sessions() as db:
        return db.scalar(select(func.coalesce(func.sum(AiUsageRow.input_tokens + AiUsageRow.output_tokens), 0))
                         .where(AiUsageRow.workspace_id == workspace_id, AiUsageRow.actor_id == actor_id,
                                AiUsageRow.day == today()))


def query(sessions, workspace_id, start, end, actor=None, provider=None, rating=None, scope=None, q=None, *, content_enabled=True, retention_days=90, export=False, allowed_project_ids=None, viewer_can_hr=True, viewer_can_reports=True):
    row = AiUsageRow
    rating_row = AiFeedbackRow
    joined = row.__table__.outerjoin(rating_row, and_(row.id == rating_row.usage_id, row.actor_id == rating_row.actor_id))
    authorized = content_authorized(row, allowed_project_ids, viewer_can_hr=viewer_can_hr, viewer_can_reports=viewer_can_reports)
    joined = joined.outerjoin(AiExchangeRow, and_(authorized, row.id == AiExchangeRow.usage_id,
        row.workspace_id == AiExchangeRow.workspace_id,
        AiExchangeRow.created_at >= datetime.now(timezone.utc) - timedelta(days=retention_days)))
    filters = [row.workspace_id == workspace_id, row.day >= start, row.day <= end]
    if q:
        pattern = '%' + q[:200].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        filters.append(or_(AiExchangeRow.question.ilike(pattern, escape='\\'),
                           AiExchangeRow.answer.ilike(pattern, escape='\\')) if content_enabled else row.id.is_(None))
    if scope:
        filters.append(row.scope == scope)
    if provider:
        filters.append(row.provider == provider)
    if rating:
        filters.append(rating_row.rating.is_(None) if rating == 'none' else rating_row.rating == (1 if rating == 'up' else -1))
    people_filters = filters[:]
    if actor:
        filters.append(row.actor_id == actor)
    metrics = [func.count().label('questions'), func.coalesce(func.sum(row.input_tokens), 0).label('input_tokens'),
               func.coalesce(func.sum(row.output_tokens), 0).label('output_tokens'),
               func.coalesce(func.sum(row.cost_micro_usd), 0).label('cost_micro_usd'),
               func.coalesce(func.sum(case((row.cost_micro_usd.is_(None), 1), else_=0)), 0).label('unpriced_calls'),
               func.coalesce(func.sum(case((rating_row.rating == 1, 1), else_=0)), 0).label('up'),
               func.coalesce(func.sum(case((rating_row.rating == -1, 1), else_=0)), 0).label('down')]

    def public(result):
        value = dict(result)
        value['cost_usd'] = int(value.pop('cost_micro_usd')) / 1_000_000
        for key in ('questions', 'input_tokens', 'output_tokens'):
            value[key] = int(value[key])
        if 'last_at' in value:
            value['last_at'] = iso(value['last_at'])
        return value

    latest = select(row.actor_id, row.actor_name, func.row_number().over(
        partition_by=row.actor_id, order_by=(row.created_at.desc(), row.id.desc())).label('rank')
    ).select_from(joined).where(*people_filters).subquery()
    with sessions() as db:
        if db.get_bind().dialect.name == 'postgresql':
            db.connection(execution_options={'isolation_level': 'REPEATABLE READ'})
        else:
            # SQLite SELECT alone does not start a snapshot with the legacy driver.
            db.connection().exec_driver_sql('BEGIN')
        if export:
            entries = [exchange_json(r, f, e if content_enabled else None, authorized=permitted)
                       for r, f, e, permitted in db.execute(select(row, rating_row, AiExchangeRow, authorized).select_from(joined)
                           .where(*filters).order_by(row.created_at.desc(), row.id.desc()).limit(501))]
            keys = ('usage_id', 'created_at', 'name', 'provider', 'scope', 'rating', 'reason', 'question', 'answer', 'tools', 'authorization_basis')
            return dict(rows=[{k: entry[k] for k in keys} for entry in entries[:500]], truncated=len(entries) > 500)
        names = dict(db.execute(select(latest.c.actor_id, latest.c.actor_name).where(latest.c.rank == 1)).all())
        totals = public(db.execute(select(*metrics).select_from(joined).where(*filters)).mappings().one())
        up, down = totals.pop('up'), totals.pop('down')
        totals['feedback'] = dict(up=up, down=down, rated=up + down, up_rate=up / (up + down) if up + down else None)
        totals['unpriced_calls'] = totals['unpriced_calls'] or 0
        groups = {}
        for name, columns in (
            ('by_person', [row.actor_id, func.max(row.created_at).label('last_at')]),
            ('by_day', [row.day]), ('by_provider', [row.provider]),
        ):
            key = columns[0]
            groups[name] = [public(r) for r in db.execute(select(*columns, *metrics).select_from(joined).where(*filters)
                                                         .group_by(key).order_by(key)).mappings()]
        for person in groups['by_person']:
            person['name'] = names.get(person['actor_id'], person['actor_id'])
        people = [dict(actor_id=k, name=v) for k, v in sorted(names.items())]
        entries = [exchange_json(r, f, e if content_enabled else None, authorized=permitted)
                   for r, f, e, permitted in db.execute(select(row, rating_row, AiExchangeRow, authorized).select_from(joined)
                       .where(*filters).order_by(row.created_at.desc(), row.id.desc()).limit(50))]
        recent = [{k: v for k, v in entry.items() if k not in ('question', 'answer', 'project_id')} for entry in entries]
        reasons = dict.fromkeys(('wrong', 'incomplete', 'slow', 'other', 'unspecified'), 0)
        reasons.update(dict(db.execute(select(func.coalesce(rating_row.reason, 'unspecified'), func.count()).select_from(joined)
            .where(*filters, rating_row.rating == -1).group_by(rating_row.reason)).all()))
    return dict(range={'from': start, 'to': end}, totals=totals, **groups, people=people, recent=recent, reasons=reasons)


def exchange_json(row, feedback, exchange, *, authorized=True):
    if not authorized:
        exchange = None
    question = exchange.question if exchange else None
    answer = exchange.answer if exchange else None
    return dict(usage_id=row.id, created_at=iso(row.created_at), actor_id=row.actor_id, name=row.actor_name,
        provider=row.provider, scope=row.scope, project_id=row.project_id if authorized else None, status=row.status,
        authorization_basis='recorded' if row.provenance_version == 1 else 'legacy_workspace',
        rating={1: 'up', -1: 'down'}.get(feedback.rating) if feedback else None,
        reason=feedback.reason if feedback else None, question=question, answer=answer,
        question_preview=question[:120] if question is not None else None,
        answer_preview=answer[:120] if answer is not None else None,
        tools=json.loads(exchange.tool_names) if exchange else [], error_detail=exchange.error_detail if exchange else None,
        latency_ms=row.latency_ms, input_tokens=row.input_tokens, output_tokens=row.output_tokens,
        cost_usd=None if row.cost_micro_usd is None else row.cost_micro_usd / 1_000_000)


def exchange(sessions, workspace_id, usage_id, *, content_enabled=True, retention_days=90, allowed_project_ids=None, viewer_can_hr=True, viewer_can_reports=True):
    with sessions() as db:
        row = db.scalar(select(AiUsageRow).where(AiUsageRow.id == usage_id, AiUsageRow.workspace_id == workspace_id))
        if row is None:
            return None
        feedback = db.get(AiFeedbackRow, (usage_id, row.actor_id))
        content = db.scalar(select(AiExchangeRow).where(AiExchangeRow.usage_id == usage_id,
            AiExchangeRow.workspace_id == workspace_id,
            AiExchangeRow.created_at >= datetime.now(timezone.utc) - timedelta(days=retention_days))) if content_enabled else None
        authorized = db.scalar(select(content_authorized(AiUsageRow, allowed_project_ids, viewer_can_hr=viewer_can_hr, viewer_can_reports=viewer_can_reports)).where(AiUsageRow.id == usage_id))
        result = exchange_json(row, feedback, content, authorized=authorized)
        result.pop('question_preview')
        result.pop('answer_preview')
        return result


def iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


ADDED_USAGE_COLUMNS = ('scope', 'project_id', 'authz_version', 'permission_key', 'provenance_version')


def column_ddl(name, dialect):
    column = AiUsageRow.__table__.c[name]
    return 'ALTER TABLE ai_usage ADD COLUMN ' + str(CreateColumn(column).compile(dialect=dialect))


def ensure_schema(engine):
    """Create the AI tables and add columns introduced after a table first shipped; create_all never alters existing tables."""
    Base.metadata.create_all(engine, tables=[AiSchemaMigration.__table__, AiConversationCaseRead.__table__, AiConversationWorkspaceRead.__table__, AiWorkspaceRead.__table__, AiCaseRead.__table__, AiConversationGeneration.__table__, AiUsageRow.__table__, AiFeedbackRow.__table__, AiExchangeRow.__table__], checkfirst=True)
    for table, names in ((AiConversationGeneration.__table__, ('active_runs', 'last_activity_at')),
                         (AiUsageRow.__table__, ADDED_USAGE_COLUMNS)):
        for name in names:
            try:
                with engine.begin() as connection:
                    if name in {c['name'] for c in inspect(connection).get_columns(table.name)}:
                        continue
                    ddl = str(CreateColumn(table.c[name]).compile(dialect=connection.dialect))
                    connection.exec_driver_sql(f'ALTER TABLE {table.name} ADD COLUMN {ddl}')
            except DBAPIError:
                if name not in {c['name'] for c in inspect(engine).get_columns(table.name)}:
                    raise
    backfill_conversation_reads(engine)
    with engine.begin() as connection:
        missing = select(AiConversationGeneration).where(AiConversationGeneration.last_activity_at.is_(None)).exists()
        if connection.scalar(select(missing)):
            connection.execute(update(AiConversationGeneration).where(AiConversationGeneration.last_activity_at.is_(None)).values(last_activity_at=datetime.now(timezone.utc)))
    for index in AiUsageRow.__table__.indexes:
        try:
            index.create(engine, checkfirst=True)
        except DBAPIError:
            existing = {i['name']:i['column_names'] for i in inspect(engine).get_indexes('ai_usage')}
            if existing.get(index.name) != [c.name for c in index.columns]:
                raise

    ensure_usage_conversation_index(engine)


def backfill_conversation_reads(engine):
    with engine.begin() as connection:
        if connection.dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        claimed = connection.scalar(insert(AiSchemaMigration).values(
            name=CONVERSATION_READ_BACKFILL, completed_at=datetime.now(timezone.utc)
        ).on_conflict_do_nothing().returning(AiSchemaMigration.name))
        if claimed is None:
            return
        u = AiUsageRow
        for audit, authority, field in ((AiCaseRead, AiConversationCaseRead, 'project_id'),
                                         (AiWorkspaceRead, AiConversationWorkspaceRead, 'marker')):
            column = getattr(audit, field)
            source = select(u.workspace_id,u.actor_id,u.conversation_id,column).join(
                audit,audit.usage_id == u.id).where(func.coalesce(u.error_code,'') != 'ai_forbidden'
                ).distinct().order_by(u.workspace_id,u.actor_id,u.conversation_id,column)
            connection.execute(insert(authority).from_select(
                ['workspace_id','actor_id','conversation_id',field],source).on_conflict_do_nothing())


def ensure_usage_conversation_index(engine):
    if engine.dialect.name != 'postgresql':
        if any(index['name'] == USAGE_CONVERSATION_INDEX for index in inspect(engine).get_indexes('ai_usage')):
            return
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE INDEX IF NOT EXISTS {USAGE_CONVERSATION_INDEX} ON ai_usage (workspace_id, actor_id, conversation_id)')
        return
    try:
        with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
            try:
                connection.exec_driver_sql("SET lock_timeout = '1s'")
                connection.exec_driver_sql("SET statement_timeout = '15s'")
                valid = connection.exec_driver_sql(
                    "SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass('ix_ai_usage_conversation') AND indrelid=to_regclass('ai_usage')").scalar()
                if valid is True:
                    return
                if valid is False:
                    connection.exec_driver_sql(f'DROP INDEX CONCURRENTLY IF EXISTS {USAGE_CONVERSATION_INDEX}')
                connection.exec_driver_sql(f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {USAGE_CONVERSATION_INDEX} ON ai_usage (workspace_id, actor_id, conversation_id)')
            finally:
                try:
                    connection.exec_driver_sql('RESET lock_timeout')
                    connection.exec_driver_sql('RESET statement_timeout')
                except SQLAlchemyError:
                    connection.invalidate()
    except SQLAlchemyError:
        logger.warning('ai_usage_conversation_index_retry_on_next_startup')


def content_authorized(row, allowed_project_ids=None, permission_key=None, viewer_can_hr=True, viewer_can_reports=True):
    conditions = []
    if allowed_project_ids is not None:
        c = AiConversationCaseRead
        conditions += [or_(row.scope != 'project', row.project_id.in_(allowed_project_ids)),
            ~select(c.project_id).where(c.workspace_id == row.workspace_id,c.actor_id == row.actor_id,
                c.conversation_id == row.conversation_id,c.project_id.not_in(allowed_project_ids)).exists()]
    if permission_key is not None:
        conditions.append(or_(row.permission_key.is_(None), row.permission_key == permission_key))
    if not viewer_can_hr:
        c = AiConversationWorkspaceRead
        conditions.append(~select(c.marker).where(c.workspace_id == row.workspace_id,c.actor_id == row.actor_id,
            c.conversation_id == row.conversation_id,c.marker == 'attendance').exists())
    if not viewer_can_reports:
        c = AiConversationWorkspaceRead
        conditions.append(~select(c.marker).where(c.workspace_id == row.workspace_id,c.actor_id == row.actor_id,
            c.conversation_id == row.conversation_id,c.marker.like('report:%')).exists())
    return and_(*conditions) if conditions else true()


def required_case_ids(sessions, workspace_id, actor_id=None):
    c,u,e = AiConversationCaseRead,AiUsageRow,AiExchangeRow
    cases = select(c.project_id).where(c.workspace_id == workspace_id)
    scoped = select(u.project_id).join(e,e.usage_id == u.id).where(u.workspace_id == workspace_id,
        u.scope == 'project',u.project_id.is_not(None))
    if actor_id is not None:
        cases = cases.where(c.actor_id == actor_id)
        scoped = scoped.where(u.actor_id == actor_id)
    with sessions() as db:
        return set(db.scalars(union(cases,scoped)))


def conversation_authority(sessions, workspace_id, actor_id, conversation_id):
    with sessions() as db:
        usages = db.execute(select(AiUsageRow.id, AiUsageRow.scope, AiUsageRow.project_id,
            AiUsageRow.permission_key, AiUsageRow.provenance_version).where(
            AiUsageRow.workspace_id == workspace_id, AiUsageRow.actor_id == actor_id,
            AiUsageRow.conversation_id == conversation_id,
            func.coalesce(AiUsageRow.error_code,'') != 'ai_forbidden')).all()
        c = AiConversationCaseRead
        refs = set(db.scalars(select(c.project_id).where(c.workspace_id == workspace_id,
            c.actor_id == actor_id,c.conversation_id == conversation_id)))
        w = AiConversationWorkspaceRead
        workspace_reads = set(db.scalars(select(w.marker).where(w.workspace_id == workspace_id,w.actor_id == actor_id,w.conversation_id == conversation_id)))
    refs.update(u.project_id for u in usages if u.scope == 'project')
    return dict(case_ids=refs, workspace_reads=workspace_reads, permission_keys={u.permission_key for u in usages if u.permission_key},
        scopes={(u.scope,u.project_id) for u in usages},
        legacy=any(u.provenance_version != 1 for u in usages))


def conversation_scopes(sessions, workspace_id, actor_id, conversation_id):
    with sessions() as db:
        rows = db.execute(select(AiUsageRow.scope, AiUsageRow.project_id).where(
            AiUsageRow.workspace_id == workspace_id, AiUsageRow.actor_id == actor_id,
            AiUsageRow.conversation_id == conversation_id).distinct()).all()
        return [tuple(row) for row in rows]


def history_statement(workspace_id, actor_id, retention_days):
    u, e = AiUsageRow, AiExchangeRow
    return select(u, e).join(e, and_(e.usage_id == u.id, e.workspace_id == u.workspace_id,
        e.actor_id == u.actor_id)).where(u.workspace_id == workspace_id, u.actor_id == actor_id,
        e.created_at >= datetime.now(timezone.utc) - timedelta(days=retention_days))


def conversation_title(question):
    return ' '.join(question.split())[:60]


def conversations(sessions, workspace_id, actor_id, scope, project_id, limit, before, *, content_enabled, retention_days, allowed_project_ids=None, permission_key=None, viewer_can_hr=True, viewer_can_reports=True):
    import base64
    cursor = None
    if before:
        try:
            stamp, ident = json.loads(base64.urlsafe_b64decode(before.encode()))
            cursor = (datetime.fromisoformat(stamp), ident)
            if cursor[0].tzinfo is None or not isinstance(ident, str):
                raise ValueError
        except Exception:
            raise ValueError('invalid cursor') from None
    result = dict(history_available=content_enabled, items=[], next_cursor=None)
    if not content_enabled:
        return result
    u, e = AiUsageRow, AiExchangeRow
    stmt = history_statement(workspace_id, actor_id, retention_days).where(u.scope == scope)
    blocked = []
    if allowed_project_ids is not None:
        c = AiConversationCaseRead
        blocked.append(select(c.conversation_id).where(c.workspace_id == workspace_id,c.actor_id == actor_id,
            c.project_id.not_in(allowed_project_ids)))
        blocked.append(select(u.conversation_id).where(u.workspace_id == workspace_id,u.actor_id == actor_id,
            u.scope == 'project',u.project_id.not_in(allowed_project_ids),func.coalesce(u.error_code,'') != 'ai_forbidden'))
    if permission_key is not None:
        blocked.append(select(u.conversation_id).where(u.workspace_id == workspace_id,u.actor_id == actor_id,
            u.permission_key.is_not(None),u.permission_key != permission_key,func.coalesce(u.error_code,'') != 'ai_forbidden'))
    if not viewer_can_hr:
        c = AiConversationWorkspaceRead
        blocked.append(select(c.conversation_id).where(c.workspace_id == workspace_id,c.actor_id == actor_id,c.marker == 'attendance'))
    if not viewer_can_reports:
        c = AiConversationWorkspaceRead
        blocked.append(select(c.conversation_id).where(c.workspace_id == workspace_id,c.actor_id == actor_id,c.marker.like('report:%')))
    if blocked:
        stmt = stmt.where(u.conversation_id.not_in(union(*blocked)))
    if project_id is not None:
        stmt = stmt.where(u.project_id == project_id)
    # Rank only retained, authorized exchanges so a deleted/expired first turn
    # cannot supply a title. One statement also keeps titles and counts consistent.
    ranked = stmt.with_only_columns(
        u.conversation_id.label('id'), u.scope, u.project_id, u.id.label('usage_id'),
        func.min(case((u.provenance_version == 1, 1), else_=0)).over(partition_by=u.conversation_id).label('tracked'),
        func.max(u.created_at).over(partition_by=u.conversation_id).label('updated_at'),
        func.count().over(partition_by=u.conversation_id).label('turns'),
        func.row_number().over(partition_by=u.conversation_id,
            order_by=(u.created_at, u.id)).label('rank'),
    ).subquery()
    page = select(ranked).where(ranked.c.rank == 1).order_by(ranked.c.updated_at.desc(), ranked.c.id.desc())
    if cursor:
        page = page.where(or_(ranked.c.updated_at < cursor[0], and_(
            ranked.c.updated_at == cursor[0], ranked.c.id < cursor[1])))
    bounded = page.limit(limit + 1).subquery()
    statement = select(bounded, e.question).join(e, and_(
        e.usage_id == bounded.c.usage_id, e.workspace_id == workspace_id, e.actor_id == actor_id)
    ).order_by(bounded.c.updated_at.desc(), bounded.c.id.desc())
    with sessions() as db:
        rows = db.execute(statement).mappings().all()
        for row in rows[:limit]:
            result['items'].append(dict(id=row['id'], title=conversation_title(row['question']), scope=row['scope'],
                project_id=row['project_id'], authorization_basis='recorded' if row['tracked'] else 'legacy_workspace', updated_at=iso(row['updated_at']), turns=row['turns']))
    if len(rows) > limit:
        last = result['items'][-1]
        result['next_cursor'] = base64.urlsafe_b64encode(json.dumps([last['updated_at'], last['id']]).encode()).decode()
    return result


def conversation(sessions, workspace_id, actor_id, conversation_id, *, content_enabled, retention_days):
    if not content_enabled:
        return None
    u = AiUsageRow
    with sessions() as db:
        stmt = history_statement(workspace_id, actor_id, retention_days).where(u.conversation_id == conversation_id)
        rows = db.execute(stmt.order_by(u.created_at.desc(), u.id.desc()).limit(201)).all()
        rows.reverse()
        if not rows:
            return None
        first, content = db.execute(stmt.order_by(u.created_at, u.id).limit(1)).first()
        messages = [dict(role=role, content=text, at=iso(exchange.created_at), usage_id=usage.id)
            for usage, exchange in rows for role, text in [('user', exchange.question), ('assistant', exchange.answer)] if text]
        return dict(id=conversation_id, title=conversation_title(content.question), scope=first.scope,
            project_id=first.project_id, authorization_basis='recorded' if all(u.provenance_version == 1 for u, _ in rows) else 'legacy_workspace', messages=messages[-200:], truncated=len(messages)>200 or len(rows)>200)


def delete_conversation(sessions, workspace_id, actor_id, conversation_id):
    with sessions.begin() as db:
        g = AiConversationGeneration
        db.execute(update(g).where(g.workspace_id == workspace_id, g.actor_id == actor_id,
            g.conversation_id == conversation_id).values(generation=g.generation + 1))
        ids = select(AiUsageRow.id).where(AiUsageRow.workspace_id == workspace_id,
            AiUsageRow.actor_id == actor_id, AiUsageRow.conversation_id == conversation_id)
        delete_read_metadata(db, ids)
        for model in (AiConversationCaseRead,AiConversationWorkspaceRead):
            db.execute(delete(model).where(model.workspace_id == workspace_id,model.actor_id == actor_id,model.conversation_id == conversation_id))
        db.execute(delete(AiExchangeRow).where(AiExchangeRow.usage_id.in_(ids),
            AiExchangeRow.workspace_id == workspace_id, AiExchangeRow.actor_id == actor_id))
