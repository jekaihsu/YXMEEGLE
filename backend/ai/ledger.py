"""One metadata-only row per question, with SQL dashboard aggregations."""
from datetime import datetime, timezone
import logging
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, CheckConstraint, func, select, case, and_, delete, inspect
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateColumn
from ..models import Base

TAIPEI = ZoneInfo('Asia/Taipei')
logger = logging.getLogger(__name__)


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


def record(sessions, **values):
    created = datetime.now(timezone.utc)
    values = dict(created_at=created, day=created.astimezone(TAIPEI).date().isoformat(), **values)
    values.setdefault('id', str(uuid4()))
    for attempt in range(2):
        try:
            with sessions.begin() as db:
                if db.get(AiUsageRow, values['id']) is None:
                    db.add(AiUsageRow(**values))
            return
        except Exception:
            if attempt == 1:
                logger.error('ai_usage_write_failed')


def daily_tokens(sessions, workspace_id, actor_id):
    with sessions() as db:
        return db.scalar(select(func.coalesce(func.sum(AiUsageRow.input_tokens + AiUsageRow.output_tokens), 0))
                         .where(AiUsageRow.workspace_id == workspace_id, AiUsageRow.actor_id == actor_id,
                                AiUsageRow.day == today()))


def query(sessions, workspace_id, start, end, actor=None, provider=None, rating=None, scope=None):
    row = AiUsageRow
    rating_row = AiFeedbackRow
    joined = row.__table__.outerjoin(rating_row, and_(row.id == rating_row.usage_id, row.actor_id == rating_row.actor_id))
    filters = [row.workspace_id == workspace_id, row.day >= start, row.day <= end]
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
        recent = [dict(created_at=iso(r.created_at), actor_id=r.actor_id, name=r.actor_name, provider=r.provider, scope=r.scope,
                       input_tokens=r.input_tokens, output_tokens=r.output_tokens,
                       cost_usd=None if r.cost_micro_usd is None else r.cost_micro_usd / 1_000_000,
                       latency_ms=r.latency_ms, status=r.status,
                       rating={1: 'up', -1: 'down'}.get(f.rating) if f else None, reason=f.reason if f else None)
                  for r, f in db.execute(select(row, rating_row).select_from(joined).where(*filters).order_by(row.created_at.desc(), row.id.desc()).limit(50))]
        reasons = dict.fromkeys(('wrong', 'incomplete', 'slow', 'other', 'unspecified'), 0)
        reasons.update(dict(db.execute(select(func.coalesce(rating_row.reason, 'unspecified'), func.count()).select_from(joined)
            .where(*filters, rating_row.rating == -1).group_by(rating_row.reason)).all()))
    return dict(range={'from': start, 'to': end}, totals=totals, **groups, people=people, recent=recent, reasons=reasons)


def iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


ADDED_USAGE_COLUMNS = ('scope', 'project_id')


def column_ddl(name, dialect):
    column = AiUsageRow.__table__.c[name]
    return 'ALTER TABLE ai_usage ADD COLUMN ' + str(CreateColumn(column).compile(dialect=dialect))


def ensure_schema(engine):
    """Create the AI tables and add columns introduced after a table first shipped; create_all never alters existing tables."""
    Base.metadata.create_all(engine, tables=[AiUsageRow.__table__, AiFeedbackRow.__table__], checkfirst=True)
    for name in ADDED_USAGE_COLUMNS:
        with engine.begin() as connection:
            if name in {c['name'] for c in inspect(connection).get_columns('ai_usage')}:
                continue
            try:
                connection.exec_driver_sql(column_ddl(name, connection.dialect))
            except DBAPIError:
                if name not in {c['name'] for c in inspect(engine).get_columns('ai_usage')}:
                    raise
    for index in AiUsageRow.__table__.indexes:
        index.create(engine, checkfirst=True)

