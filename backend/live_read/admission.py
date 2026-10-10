"""Roster freshness trigger; callers retain the existing access policy."""
from datetime import datetime, timezone

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
    try:
        result = coordinator.ensure(wid, 'roster', wait=wait, force=False)
    except Exception:
        return not wait
    return not wait or result.get('status') == 'fresh'
