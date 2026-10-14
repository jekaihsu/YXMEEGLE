"""Live-read settings; rollout remains opt-in."""
import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LiveReadConfig:
    enabled: bool = False
    source_ttl_seconds: float = 60
    roster_ttl_seconds: float = 60
    attendance_ttl_seconds: float = 300
    max_rps: float = 5
    blocking_timeout_seconds: float = 10
    lease_seconds: float = 120
    budget_seconds: float = 100
    request_timeout_seconds: float = 10
    attendance_budget_seconds: float = 40
    roster_budget_seconds: float = 30
    source_budget_seconds: float = 60
    table_rps: float = 2
    read_workers: int = 3
    records_api: str = 'list'

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env

        def number(key, default, minimum, maximum=None):
            try:
                value = float(env.get('LARK_LIVE_READ_' + key, default))
                if not math.isfinite(value):
                    value = default
            except (TypeError, ValueError):
                value = default
            return min(maximum, max(minimum, value)) if maximum else max(minimum, value)

        enabled = str(env.get('LARK_LIVE_READ_ENABLED', 'false')).lower() == 'true'
        legacy_default = 60 if enabled else 300
        return cls(
            enabled=enabled,
            source_ttl_seconds=number('SOURCE_TTL_SECONDS', legacy_default, 30),
            roster_ttl_seconds=number('ROSTER_TTL_SECONDS', legacy_default, 30),
            attendance_ttl_seconds=number('ATTENDANCE_TTL_SECONDS', 300, 60),
            max_rps=number('MAX_RPS', 5, .01, 10),
            blocking_timeout_seconds=number('BLOCKING_TIMEOUT_SECONDS', 10, .01),
            lease_seconds=number('LEASE_SECONDS', 120, 60),
            budget_seconds=number('BUDGET_SECONDS', 100, 10),
            request_timeout_seconds=number('REQUEST_TIMEOUT_SECONDS', 10, .1, 15),
            attendance_budget_seconds=number('ATTENDANCE_BUDGET_SECONDS', 40, 1, 60),
            roster_budget_seconds=number('ROSTER_BUDGET_SECONDS', 30, 1, 60),
            source_budget_seconds=number('SOURCE_BUDGET_SECONDS', 60, 1, 75),
            table_rps=number('TABLE_RPS', 2, .01, 2),
            read_workers=int(number('READ_WORKERS', 3, 1, 3)),
            records_api=env.get('LARK_BITABLE_RECORDS_API', 'list')
            if env.get('LARK_BITABLE_RECORDS_API', 'list') in ('list', 'search') else 'list',
        )

    def dataset_budget(self, dataset):
        return min(self.budget_seconds, getattr(self, {
            'sources': 'source', 'roster': 'roster', 'attendance': 'attendance'
        }[dataset] + '_budget_seconds'))
