"""One metadata-only row per question, with SQL dashboard aggregations."""
from datetime import datetime, timezone
import logging
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, func, select, case
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


def today():
    return datetime.now(TAIPEI).date().isoformat()


def record(sessions, **values):
    try:
        created = datetime.now(timezone.utc)
        with sessions.begin() as db:
            db.add(AiUsageRow(created_at=created, day=created.astimezone(TAIPEI).date().isoformat(), **values))
    except Exception:
        # Exception strings can contain SQL parameters; only report the failure type.
        logger.error('ai_usage_write_failed')


def daily_tokens(sessions, workspace_id, actor_id):
    with sessions() as db:
        return db.scalar(select(func.coalesce(func.sum(AiUsageRow.input_tokens + AiUsageRow.output_tokens), 0))
                         .where(AiUsageRow.workspace_id == workspace_id, AiUsageRow.actor_id == actor_id,
                                AiUsageRow.day == today()))


def query(sessions, workspace_id, start, end, actor=None, provider=None):
    row = AiUsageRow
    filters = [row.workspace_id == workspace_id, row.day >= start, row.day <= end]
    if provider:
        filters.append(row.provider == provider)
    people_filters = filters[:]
    if actor:
        filters.append(row.actor_id == actor)
    metrics = [func.count().label('questions'), func.coalesce(func.sum(row.input_tokens), 0).label('input_tokens'),
               func.coalesce(func.sum(row.output_tokens), 0).label('output_tokens'),
               func.coalesce(func.sum(row.cost_micro_usd), 0).label('cost_micro_usd')]

    def public(result):
        value = dict(result)
        value['cost_usd'] = int(value.pop('cost_micro_usd')) / 1_000_000
        for key in ('questions', 'input_tokens', 'output_tokens'):
            value[key] = int(value[key])
        if 'last_at' in value:
            value['last_at'] = iso(value['last_at'])
        return value

    with sessions() as db:
        totals = public(db.execute(select(*metrics, func.sum(case((row.cost_micro_usd.is_(None), 1), else_=0))
                                          .label('unpriced_calls')).where(*filters)).mappings().one())
        totals['unpriced_calls'] = totals['unpriced_calls'] or 0
        groups = {}
        for name, columns in (
            ('by_person', [row.actor_id, func.max(row.actor_name).label('name'), func.max(row.created_at).label('last_at')]),
            ('by_day', [row.day]), ('by_provider', [row.provider]),
        ):
            key = columns[0]
            groups[name] = [public(r) for r in db.execute(select(*columns, *metrics).where(*filters)
                                                         .group_by(key).order_by(key)).mappings()]
        people = [dict(r) for r in db.execute(select(row.actor_id, func.max(row.actor_name).label('name'))
                  .where(*people_filters).group_by(row.actor_id).order_by(row.actor_id)).mappings()]
        recent = [dict(created_at=iso(r.created_at), actor_id=r.actor_id, name=r.actor_name, provider=r.provider,
                       input_tokens=r.input_tokens, output_tokens=r.output_tokens,
                       cost_usd=None if r.cost_micro_usd is None else r.cost_micro_usd / 1_000_000,
                       latency_ms=r.latency_ms, status=r.status)
                  for r in db.scalars(select(row).where(*filters).order_by(row.created_at.desc(), row.id.desc()).limit(50))]
    return dict(range={'from': start, 'to': end}, totals=totals, **groups, people=people, recent=recent)


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()
