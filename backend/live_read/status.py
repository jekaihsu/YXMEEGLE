"""Public freshness projection; this module performs no network reads."""
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import LiveReadConfig

DATASETS = ('sources', 'roster', 'attendance')
TAIPEI = ZoneInfo('Asia/Taipei')


def timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=TAIPEI)
    return value.astimezone(TAIPEI)


def ttl_seconds(cfg, dataset):
    config = cfg if isinstance(cfg, LiveReadConfig) else LiveReadConfig.from_env(cfg)
    return getattr(config, {'sources': 'source', 'roster': 'roster',
                            'attendance': 'attendance'}[dataset] + '_ttl_seconds')


def freshness(rows, cfg, now, enabled, workspace_as_of=None):
    now = timestamp(now)
    datasets = {}
    for dataset in DATASETS:
        row = rows.get(dataset) or {}
        as_of = row.get('as_of') if enabled else workspace_as_of
        age = max(0, int((now - timestamp(as_of)).total_seconds())) if as_of else None
        ttl = ttl_seconds(cfg, dataset)
        status = 'never' if as_of is None else ('fresh' if age < ttl else 'stale')
        if row.get('last_error'):
            status = 'blocked' if row.get('error_code') == 'ReadBlocked' else 'error'
        if row.get('lease_until') and timestamp(row['lease_until']) > now:
            status = 'refreshing'
        if not enabled or dataset not in rows:
            status = 'unconfigured' if not enabled else 'never'
        datasets[dataset] = dict(as_of=as_of, fetched_at=row.get('fetched_at'),
                                 age_seconds=age, ttl_seconds=ttl, status=status,
                                 fingerprint=row.get('fingerprint'), changed_at=row.get('changed_at'),
                                 last_error=row.get('last_error'),
                                 lark=row.get('lark') or dict(calls=0, retries=0, duration_ms=0))
        if row.get('error_code'):
            datasets[dataset]['error_code'] = row['error_code']
        if dataset == 'roster':
            datasets[dataset]['hard_max_age_seconds'] = 900
    return dict(server_time=now.isoformat(), enabled=enabled, datasets=datasets)
