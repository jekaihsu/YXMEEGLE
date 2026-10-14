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


def mock_allowed(state):
    return state.get('environment') in ('demo', 'test')
