"""Truth metadata for composed case reads, independent of wire/build timestamps.

A local revision verifies canonical rows, never the age of an upstream source.
Missing source evidence remains null. No source read or scheduling occurs here.
"""
import hashlib
import json
from datetime import datetime, timezone


def explicit_refresh(request):
    directives = request.headers.get('cache-control', '').lower().split(',')
    return any(d.strip().split('=')[0] in ('no-cache', 'no-store', 'max-age')
               and (d.strip().split('=')[0] != 'max-age' or d.strip() == 'max-age=0')
               for d in directives) or request.headers.get('pragma', '').lower() == 'no-cache'


def source_metadata(source, *, revision, verified_at=None, complete=None):
    source = source if isinstance(source, dict) else {}
    stale = source.get('stale') is True or source.get('status') == 'stale'
    return dict(as_of=source.get('as_of') or source.get('fetched_at') or source.get('last_sync'),
                fetched_at=source.get('fetched_at'),
                verified_at=source.get('verified_at') or verified_at,
                changed_at=source.get('changed_at'), local_revision=revision,
                completeness='complete' if complete is True else 'partial' if complete is False else 'unknown',
                stale=stale)


def attach_first_screen(result, state, generation, freshness):
    verified = datetime.now(timezone.utc).isoformat()
    revision = state['version']
    # Disabled coordinator status can use a presentation date as workspace_as_of.
    # Only enabled source evidence or persisted ingestion evidence is trustworthy.
    source = ((freshness.get('datasets') or {}).get('sources') or {}) if freshness.get('enabled') else state.get('source_status', {})
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
    identity = json.dumps([generation, resources, result], sort_keys=True, default=str).encode()
    snapshot_id = hashlib.sha256(identity).hexdigest()
    for meta in resources.values():
        meta['snapshot_id'] = snapshot_id
    result['snapshot'] = dict(snapshot_id=snapshot_id, as_of=project['as_of'],
        fetched_at=project['fetched_at'], verified_at=verified, changed_at=project['changed_at'],
        local_revision=revision, completeness='partial', stale=any(r['stale'] for r in resources.values()),
        resources=resources)
    return result
