"""Attributed subcontract applicability: PM collects, group supervisor confirms."""
from copy import deepcopy
from .sop_contracts import VERSION, applicability, decorate_task
from .workflow import require, find, now, uid, event

GROUPS = frozenset(('field', 'control', 'mapping', 'report'))
RULES = frozenset(('always', 'subcontract', *(f'subcontract_{g}' for g in GROUPS)))


def validate_template(template):
    for node in template.get('nodes', []):
        for item in node.get('task_definitions', []):
            rule=item.get('applicability','always')
            require(isinstance(rule,str) and rule in RULES,
                    '此 SOP 適用條件尚無核定入口，不能發布或保存為可執行定義', 422)


def _supervisors(p, groups):
    if not groups:
        return {'project': p.get('supervisor_id')}
    result = {}
    for group in groups:
        node = next((n for n in p['nodes'] if n['key'] == group), None)
        require(node is not None, '下包組別沒有對應節點', 422)
        result[group] = node.get('supervisor_id') or p.get('supervisor_id')
    return result


def _materialize(ws, p, actor):
    """Only add this release's approved conditional work; never replace history."""
    from .sop_contracts import approved_definitions
    from .sources import new_task
    from .workflow_rules import inherit_new_task
    for node in p['nodes']:
        if node.get('status') == 'completed':
            continue
        for definition in approved_definitions(node['key']):
            rule = definition['applicability']
            if rule == 'always':
                continue
            applies = applicability(p, definition)
            matches = [t for t in node['tasks'] if t.get('sop_task_key') == definition['key']]
            require(len(matches) <= 1, 'SOP 任務識別重複，請先核對', 409)
            if applies is True and not matches:
                task = decorate_task(new_task(uid(), definition['title'], None), definition, p['sop_version'])
                node['tasks'].append(task)
                inherit_new_task(ws, p, node, task, actor)
            elif applies is False and matches and matches[0].get('status') != 'completed':
                task = matches[0]
                task.setdefault('sop_contract_history', []).append({
                    'at': now(), 'actor_id': actor['id'], 'before': {'required': task.get('required')},
                    'after': {'required': False}, 'reason': '主管確認本次下包不適用'})
                task['required'] = False
        node['sop_applicability_pending'] = [item for item in node.get('sop_applicability_pending', [])
            if applicability(p, {'applicability': item['rule']}) is None]


def apply_applicability(ws, user, body):
    from .case_cutover import require_execution
    from .workflow_rules import assignable
    p = find(ws['projects'], body.get('project_id'), '案件')
    require_execution(ws, p)
    require(assignable(ws, user), '操作人員須為已核實在職人員', 403)
    data = body.get('payload') or {}
    if body['action'] == 'sop_applicability_propose':
        require(user['id'] == p.get('pm_id'), '需案件 PM 彙整下包需求', 403)
        applies, groups = data.get('applies'), data.get('groups', [])
        require(type(applies) is bool and isinstance(groups, list) and
                all(isinstance(g, str) and g in GROUPS for g in groups) and len(groups) == len(set(groups)),
                '需指定是否下包與有效、不重複的作業組別', 422)
        require(bool(groups) == applies, '有下包需指定作業組別；無下包不得指定組別', 422)
        reason = data.get('reason')
        require(isinstance(reason, str) and 0 < len(reason.strip()) <= 2000, '需填寫下包範圍及理由（最多 2000 字）', 422)
        prior = p.get('sop_applicability_proposal')
        stale=bool(prior and prior.get('status')=='pending' and
                   (prior['supervisors']!=_supervisors(p,prior['groups']) or prior['proposed_by']!=p.get('pm_id')))
        require(not prior or prior.get('status') == 'returned' or stale,
                '已有下包決定或待確認提案；範圍變更須另走核定變更流程', 409)
        supervisors = _supervisors(p, groups)
        require(all(ident and any(u['id'] == ident and assignable(ws, u) for u in ws['users'])
                    for ident in supervisors.values()), '尚未指派有效的對應主管', 409)
        record = dict(id=uid(), applies=applies, groups=sorted(groups), reason=reason.strip(),
                      proposed_by=user['id'], proposed_at=now(), supervisors=supervisors,
                      confirmations=[], status='pending', contract_version=VERSION)
        if prior:
            archived=deepcopy(prior)
            if stale:archived.update(status='invalidated',reason='PM 或主管異動，由目前 PM 重新彙整')
            p.setdefault('sop_applicability_history', []).append(archived)
        p['sop_applicability_proposal'] = record
    else:
        record = p.get('sop_applicability_proposal')
        require(record and record['id'] == data.get('proposal_id') and record['status'] == 'pending',
                '提案已變更或已處理，請核對最新版本', 409)
        require(record['supervisors'] == _supervisors(p, record['groups']) and
                record['proposed_by'] == p.get('pm_id'), 'PM 或主管已變更，原提案不能直接核准', 409)
        require(user['id'] in record['supervisors'].values(), '需提案指定的對應組主管確認', 403)
        require(user['id'] != record['proposed_by'], '需求彙整與主管確認須由不同人操作', 403)
        require(data.get('result') in ('approved', 'returned'), '確認結果錯誤', 422)
        if data['result'] == 'returned':
            reason = data.get('reason')
            require(isinstance(reason, str) and 0 < len(reason.strip()) <= 2000, '退回需填理由（最多 2000 字）', 422)
            record.update(status='returned', returned_by=user['id'], returned_at=now(), return_reason=reason.strip())
        else:
            require(not any(c['actor_id'] == user['id'] for c in record['confirmations']), '本人已確認此提案', 409)
            record['confirmations'].append(dict(actor_id=user['id'], at=now()))
            if set(record['supervisors'].values()) <= {c['actor_id'] for c in record['confirmations']}:
                record.update(status='approved', approved_at=now())
                decisions = p.setdefault('sop_applicability', {})
                for rule in RULES - {'always'}:
                    group = rule.removeprefix('subcontract_')
                    decisions[rule] = dict(applies=record['applies'] if rule == 'subcontract' else group in record['groups'],
                        contract_version=VERSION, decided_by=user['id'], reason=record['reason'],
                        proposal_id=record['id'], confirmations=deepcopy(record['confirmations']), decided_at=now())
                _materialize(ws, p, user)
    event(ws, user, body['action'], p['id'], message='PM 彙整／對應主管確認下包適用性；未完成或跳過任何工作')
    return True
