"""Roster freshness trigger; callers retain the existing access policy."""
from datetime import datetime, timezone

from ..production_access import DIRECTORY_MAX_AGE_SECONDS, roster_age_seconds, access_mode
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
    clock = now or datetime.now(timezone.utc)
    age = roster_age_seconds(person, clock)
    if age is not None and age < config.roster_ttl_seconds:
        return True
    recovery_eligible = (access_mode(person, coordinator.cfg.get('LARK_APP_ID'),
                                    now=clock, cfg=coordinator.cfg,
                                    tenant=wid.removeprefix('lark-')) != 'denied'
                         and (age is None or age > DIRECTORY_MAX_AGE_SECONDS))
    wait = callback or (not recovery_eligible and (age is None or age > DIRECTORY_MAX_AGE_SECONDS))
    try:
        result = coordinator.ensure(wid, 'roster', wait=wait, force=wait and age is not None)
    except Exception:
        return not wait
    return not wait or result.get('status') == 'fresh'
