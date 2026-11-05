"""Bounded, credential-free structured diffs for immutable action receipts."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import re
import secrets
import unicodedata

SENSITIVE = {'access_token', 'refresh_token', 'app_secret', 'client_secret',
             'session_secret', 'password', 'migration_archive', 'raw_fields',
             'raw_snapshot', 'snapshot', 'attendance_identity', 'salary',
             'salary_amount', 'private_notes','oauth_identity',
             'company_admin_authorization'}


def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k.lower() not in SENSITIVE
                and not any(term in k.lower() for term in ('password', 'secret', 'token'))}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return deepcopy(value)


def entities(state):
    result = {}
    for p in state.get('projects', []):
        result[('project', p['id'])] = {k: v for k, v in p.items() if k not in ('nodes', 'comments', 'daily_reports', 'files')}
        for n in p.get('nodes', []):
            result[('node', n['id'])] = {**{k: v for k, v in n.items() if k not in ('tasks', 'review_cycles')}, 'project_id': p['id']}
            for t in n.get('tasks', []):
                result[('task', t['id'])] = {**t, 'project_id': p['id']}
            for review in n.get('review_cycles', []):
                if review.get('id'):
                    result[('review', review['id'])] = {**review, 'project_id': p['id'], 'node_id': n['id']}
        for f in p.get('files', []):
            result[('file', f['id'])] = {**f, 'project_id': p['id']}
        for comment in p.get('comments', []):
            result[('comment', comment['id'])] = {**comment, 'project_id': p['id']}
    for kind in ('users', 'approvals', 'delegations', 'input_mappings', 'work_schedules'):
        for item in state.get(kind, []):
            result[(kind, str(item.get('id', item.get('key', ''))))] = item
    return deepcopy(result)


def changes(before, state):
    after = entities(state)
    result = []
    for key in sorted(before.keys() | after.keys()):
        left, right = before.get(key, {}), after.get(key, {})
        if left == right:
            continue
        fields = {k for k in left.keys() | right.keys() if left.get(k) != right.get(k)}
        project_id = key[1] if key[0]=='project' else right.get('project_id', left.get('project_id'))
        result.append({'kind': key[0], 'id': key[1], 'project_id': project_id,
                       'before': scrub({k: left.get(k) for k in fields}),
                       'after': scrub({k: right.get(k) for k in fields})})
    return result


ACTION_COLUMN_LIMIT = 120
_SAFE_ACTION = re.compile(r'[A-Za-z0-9_.:\-]{1,%d}' % ACTION_COLUMN_LIMIT)


def _printable(value):
    return ''.join(c for c in value if unicodedata.category(c) not in ('Cc', 'Cf', 'Cs', 'Co', 'Cn'))


def record(model, wid, actor_id, action, *, result='success', request_id=None, details=None):
    # Rejected input is untrusted: never store it verbatim. Anything that is not a
    # plain identifier (oversize, NUL/control/format chars, odd unicode) is replaced
    # by a fixed-size digest so the varchar column and PostgreSQL text/JSON accept it.
    details = dict(details or {})
    if not isinstance(action, str) or not _SAFE_ACTION.fullmatch(action):
        raw = action if isinstance(action, str) else repr(action)
        digest = hashlib.sha256(raw.encode('utf-8', 'surrogatepass')).hexdigest()
        details.update(action_rejected=True, action_length=len(raw), action_sha256=digest)
        action = 'rejected_action:' + digest[:16]
    if isinstance(request_id, str):
        request_id = _printable(request_id)[:ACTION_COLUMN_LIMIT]
    return model(id=secrets.token_hex(16), workspace_id=wid, actor_id=actor_id,
                 action=action, created_at=datetime.now(timezone.utc).isoformat(),
                 data={'result': result, 'request_id': request_id, **scrub(details)})
