"""Roster freshness trigger; callers retain the existing access policy."""
from datetime import datetime, timezone

from ..production_access import DIRECTORY_MAX_AGE_SECONDS, roster_age_seconds
from .config import LiveReadConfig


def ensure_roster_for_admission(coordinator, wid, person, *, now=None, callback=False):
    """Return False on a failed blocking read; reload PersonRow before access checks.

    Ordinary requests use the old roster through the inclusive 900-second
    boundary. OAuth callbacks wait once the soft TTL expires. This result never
    grants admission or replaces company-admin grants and bootstrap recovery.
    """
    config = LiveReadConfig.from_env(coordinator.cfg)
    if (not config.enabled or wid.startswith(('demo-', 'test-'))
            or coordinator.cfg.get('LARK_WORKER_IDENTITY') != 'application'):
        return True
    age = roster_age_seconds(person, now or datetime.now(timezone.utc))
    if age is not None and age < config.roster_ttl_seconds:
        return True
    wait = callback or age is None or age > DIRECTORY_MAX_AGE_SECONDS
    try:
        result = coordinator.ensure(wid, 'roster', wait=wait, force=wait)
    except Exception:
        return not wait
    return not wait or result.get('status') == 'fresh'
