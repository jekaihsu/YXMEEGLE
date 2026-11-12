"""Truth metadata for composed case reads, independent of wire/build timestamps.

A local revision verifies canonical rows, never the age of an upstream source.
Missing source evidence remains null. No source read or scheduling occurs here.
"""
import hashlib
import json
from datetime import datetime, timezone


class SnapshotRevisionChanged(Exception):
    """Retry one consistent capture when its workspace revision advances."""


def explicit_refresh(request):
    directives = request.headers.get('cache-control', '').lower().split(',')
    return any(d.strip().split('=')[0] in ('no-cache', 'no-store', 'max-age')
               and (d.strip().split('=')[0] != 'max-age' or d.strip() == 'max-age=0')
               for d in directives) or request.headers.get('pragma', '').lower() == 'no-cache'


def source_metadata(source, *, revision, verified_at=None, complete=None):
    source = source if isinstance(source, dict) else {}
    as_of = source.get('as_of') or source.get('fetched_at') or source.get('last_sync')
    age = source.get('age_seconds')
    if as_of:
        try:
            stamp = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                from zoneinfo import ZoneInfo
                stamp = stamp.replace(tzinfo=ZoneInfo('Asia/Taipei'))
            age = max(0, (datetime.now(timezone.utc) - stamp).total_seconds())
        except (ValueError, TypeError):
            pass
    # No assumed producer cadence; future timestamps clamp to zero age.
    ttl = source.get('ttl_seconds')
    stale = (source.get('stale') is True or source.get('status') == 'stale'
             or (age is not None and ttl is not None and age >= ttl))
    return dict(as_of=source.get('as_of') or source.get('fetched_at') or source.get('last_sync'),
                fetched_at=source.get('fetched_at'),
                verified_at=source.get('verified_at') or verified_at,
                changed_at=source.get('changed_at'), local_revision=revision,
                completeness='complete' if complete is True else 'partial' if complete is False else 'unknown',
                stale=stale if (age is not None and ttl is not None) or stale else None,
                age_seconds=age, ttl_seconds=ttl, status=source.get('status'), last_error=source.get('last_error'))


def attach_first_screen(result, state, generation, freshness):
    verified = datetime.now(timezone.utc).isoformat()
    revision = state['version']
    # Disabled coordinator status can use a presentation date as workspace_as_of.
    # Only enabled source evidence or persisted ingestion evidence is trustworthy.
    source = ((freshness.get('datasets') or {}).get('sources') or {}) if freshness.get('enabled') else state.get('source_status', {})
    # Live-read TTL describes polling freshness, not manual/batch ingestion.
    # With live reads off we preserve ingestion age but cannot infer staleness
    # without an explicit ingestion cadence. An explicit stale signal still wins.
    source = dict(source, ttl_seconds=source.get('ttl_seconds') if freshness.get('enabled') else None)
    project = source_metadata(source, revision=revision,
                              complete=source.get('complete'))
    resources = {'project': project}
    for name in ('tasks', 'assignments', 'start', 'progress'):
        part = result[name]
        body = part.get('body')
        success = 200 <= part['status'] < 300 and part['status'] != 202
        # SOP tasks are canonical local rows; successful capture verifies them now.
        local = name == 'tasks'
        meta = source_metadata(body, revision=revision,
            verified_at=verified if success and local else None,
            complete=success and not (isinstance(body, dict) and body.get('complete') is False))
        part['snapshot'] = meta
        resources[name] = meta
    def stable(value):
        if isinstance(value, dict):
            return {k: stable(v) for k, v in value.items()
                    if k not in ('verified_at', 'age_seconds', 'task_capabilities_checked_at')}
        if isinstance(value, (list, tuple)):
            return [stable(v) for v in value]
        return value
    identity = json.dumps(stable([generation, resources, result]), sort_keys=True, default=str).encode()
    snapshot_id = hashlib.sha256(identity).hexdigest()
    for meta in resources.values():
        meta['snapshot_id'] = snapshot_id
    result['snapshot'] = dict(snapshot_id=snapshot_id, as_of=project['as_of'],
        fetched_at=project['fetched_at'], verified_at=verified, changed_at=project['changed_at'],
        local_revision=revision, completeness='partial', stale=True if any(r['stale'] is True for r in resources.values()) else (None if any(r['stale'] is None for r in resources.values()) else False),
        resources=resources)
    return result
