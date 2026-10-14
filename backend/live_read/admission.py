"""Roster freshness trigger; callers retain the existing access policy."""
from datetime import datetime, timezone
from time import perf_counter
import logging

logger = logging.getLogger(__name__)

from ..production_access import roster_age_seconds
from .config import LiveReadConfig


def ensure_roster_for_admission(coordinator, wid, person, *, now=None, callback=False):
    """Return False on a failed blocking read; reload PersonRow before access checks.

    Ordinary requests use the old roster through the inclusive 900-second
    boundary. Only OAuth callbacks wait once the soft TTL expires; every other
    request refreshes in the background so a slow or failing Lark read never
    blocks a page (a stale person is denied by require_access until it lands). This result never
    grants admission or replaces company-admin grants and bootstrap recovery.
    A recent coordinator result also covers people absent from that roster;
    only require_access on the reloaded person can admit them.
    """
    config = LiveReadConfig.from_env(coordinator.cfg)
    if (not config.enabled or wid.startswith(('demo-', 'test-'))
            or coordinator.cfg.get('LARK_WORKER_IDENTITY') != 'application'):
        return True
    clock = now or datetime.now(timezone.utc)
    age = roster_age_seconds(person, clock)
    if age is not None and age < config.roster_ttl_seconds:
        return True
    wait = callback
    started = perf_counter()
    result_class = 'stale'
    try:
        result = coordinator.ensure(wid, 'roster', wait=wait, force=False)
        result_class = 'fresh' if result.get('status') == 'fresh' else 'stale'
    except Exception as exc:
        result_class = type(exc).__name__
        return not wait
    finally:
        if callback:
            logger.info('oauth_roster_wait', extra={'event': 'oauth_roster_wait',
                        'duration_ms': round((perf_counter()-started)*1000, 2),
                        'result_class': result_class})
    return not wait or result.get('status') == 'fresh'
