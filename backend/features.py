"""Business scope approved on 2026-09-27; not an end-user setting."""
FEATURE_LEARNING = False
LEARNING_DISABLED_MESSAGE = '業主裁示停用：訓練、能力認定及考評暫停'


def require_learning():
    from .workflow import require
    require(FEATURE_LEARNING, LEARNING_DISABLED_MESSAGE, 404)

from fastapi import HTTPException

FEATURES = {'change_extension': '變更與展延', 'routines': '追蹤與檢討'}
CONFIG_KEYS = {'change_extension': 'FEATURE_CHANGE_EXTENSION', 'routines': 'FEATURE_ROUTINES'}


def resolve_features(cfg):
    return {name: str(cfg.get(key, 'false')).lower() == 'true' for name, key in CONFIG_KEYS.items()}


def enabled(state, feature):
    return state.get('features', {}).get(feature) is True


def require_feature(flags, feature):
    if flags.get(feature) is not True:
        raise HTTPException(403, {'code': 'feature_disabled', 'feature': feature,
                                 'message': FEATURES[feature] + '尚未開放', 'retryable': False},
                            headers={'Cache-Control': 'no-store'})


TASK_FEATURES = {
    ('sop_rule_id', 'quote_followup'): 'routines',
    ('completion_scope', 'post_completion_followup'): 'routines',
    ('origin', 'sop_followups'): 'routines',
    ('origin', 'recurring'): 'routines',
    ('origin', 'approval_round'): 'change_extension',
}


def task_features(task, origin=None):
    origins = {origin}
    if task.get('sop_round'):
        origins.add('approval_round')
    for (field, value), feature in TASK_FEATURES.items():
        if (value in origins if field == 'origin' else task.get(field) == value):
            yield feature


def task_enabled(state, task, origin=None):
    return all(enabled(state, feature) for feature in task_features(task, origin))


def require_task_features(state, tasks, origin=None):
    for task in tasks:
        for feature in task_features(task, origin):
            require_feature(state.get('features', {}), feature)


def guard_task_scope(state, project_id, node_id=None, task_ids=None):
    project = next((p for p in state.get('projects', []) if p['id'] == project_id), None)
    if project is None:
        return
    for node in project.get('nodes', []):
        if node_id and node['id'] != node_id:
            continue
        require_task_features(state, [t for t in node['tasks'] if task_ids is None or t['id'] in task_ids])
    if task_ids is not None:
        require_task_features(state, [t for t in project.get('sop_followups', []) if t['id'] in task_ids], 'sop_followups')


def action_feature(body):
    action = body['action']
    if action.startswith('recurring_') or action == 'sop_followup_complete':
        return 'routines'
    if action.startswith('approval_') or action in ('change_resume', 'sop_round_open'):
        return 'change_extension'
    return None


def guard_action(state, body):
    feature = action_feature(body)
    if body['action']=='job_retry' and any(job['id']==(body.get('payload') or {}).get('id') and job['kind']=='digest' for job in state.get('jobs', [])):
        feature='routines'
    if feature:
        require_feature(state.get('features', {}), feature)
    action = body['action']
    payload = body.get('payload') or {}
    if action == 'task_batch_complete' and isinstance(payload.get('items'), list):
        for item in payload['items']:
            if isinstance(item, dict) and isinstance(item.get('task_id'), str):
                guard_task_scope(state, item.get('project_id'), item.get('node_id'), {item.get('task_id')})
    task_ids = {ident for key in ('task_ids', 'work_item_ids')
                for ident in (payload.get(key) if isinstance(payload.get(key), list) else [])
                if isinstance(ident, str)}
    if isinstance(payload.get('dates'), list):
        task_ids.update(item['task_id'] for item in payload['dates']
                        if isinstance(item, dict) and isinstance(item.get('task_id'), str))
    if body.get('task_id'):
        task_ids.add(body['task_id'])
    if action.startswith('approval_') or action in ('change_resume', 'sop_round_open'):
        approval = next((a for a in state.get('approvals', [])
                         if a['id'] == payload.get('approval_id')), None)
        if approval:
            guard_task_scope(state, approval['project_id'], task_ids=approval.get('task_ids', []))
    if task_ids:
        guard_task_scope(state, body.get('project_id'), task_ids=task_ids)
    if action.startswith('review_') or action in ('node_complete', 'financial_finalize'):
        guard_task_scope(state, body.get('project_id'), body.get('node_id'))


def mock_allowed(state):
    return state.get('environment') in ('demo', 'test')
