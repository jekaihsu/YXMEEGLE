"""Pure case admission decisions. Node presence and execution status are never evidence."""
from datetime import datetime, timezone

POLICY_VERSION = 'sop-admission-v1'
SYSTEM_ACTOR = 'system:auto-enroll'


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def decide_policy(facts, *, enabled=False, since=None):
    if facts.get('ambiguous') or not facts.get('identity_verified'):
        return 'needs_review', '案件識別待核對'
    if facts.get('local_quote_creation'):
        return 'managed', '本機建立案件'
    cutoff = timestamp(since)
    first = timestamp(facts.get('first_seen_at'))
    if facts.get('known_existing') or facts.get('source_baseline'):
        return 'legacy', '既有案件，維持原流程'
    if cutoff and first and first < cutoff:
        return 'legacy', '首次准入早於啟用基準'
    if enabled and cutoff and first and first >= cutoff:
        return 'managed', '已驗證新案於啟用基準後首次准入'
    return 'legacy', '自動帶入尚未啟用' if not enabled or not cutoff else '缺少可核實的首次准入時間'


def identity_key(project):
    if project.get('planning_origin') == 'local':
        return 'local:' + project['id']
    identity = project.get('source_identity') or {}
    parts = [identity.get(k) for k in ('base_token', 'table_id', 'record_id')]
    return '|'.join(parts) if all(isinstance(p, str) and p for p in parts) else None


def ambiguous(project):
    assignment = project.get('execution_assignment') or {}
    return bool(project.get('migration_review_required') or project.get('migration_history')
                or project.get('source_conflicts', {}).get('identity')
                or assignment.get('basis') == 'merged_ownership_requires_review'
                or project.get('intake_status') in {'multiple_confirmations', 'unresolved_confirmation'})


def protected_node_changes(policies, before, after, *, protect_unclassified=False):
    """Return protected node IDs changed by a local workspace command."""
    changed = []
    after_cases = {p['id']: p for p in after}
    for project in before:
        policy = policies.get(project['id'])
        if not policy and not protect_unclassified:
            continue
        managed = policy is not None and policy.policy == 'managed'
        allowed = set(policy.node_keys) if managed else set()
        current_project = after_cases.get(project['id'], {})
        current = {n['id']: n for n in current_project.get('nodes', [])}
        if not managed and any(project.get(k) != current_project.get(k) for k in
                ('status','execution_status','pm_id','admin_id','supervisor_id','started_at','completed_at')):
            changed.append(project['id'])
        original_ids = {n['id'] for n in project.get('nodes', [])}
        changed.extend(n['id'] for n in current.values() if n['id'] not in original_ids and n['key'] not in allowed)
        for node in project.get('nodes', []):
            if node['key'] in allowed:
                continue
            fresh = current.get(node['id'])
            keys = ('tasks','status','owner_id','supervisor_id','collaborator_ids','started_at','completed_at')
            if fresh is None or any(node.get(k) != fresh.get(k) for k in keys):
                changed.append(node['id'])
    return changed
