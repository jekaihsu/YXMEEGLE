"""Version-bound node waivers. Native Lark submission is deliberately unavailable."""
from copy import deepcopy

from .policy import FINANCIAL
from .source_lifecycle import declared, needs_review
from .workflow import require, find, now, uid, event

POLICY = 'node-skip-pm-and-supervisor-20260927'


def skip_seats(p, n):
    return {'pm': p.get('pm_id', ''),
            'supervisor': n.get('supervisor_id') or p.get('supervisor_id', '')}


def snapshot(ws, p, n, scope_version=1):
    seats = skip_seats(p, n)
    value={
        'policy': POLICY, 'workspace_policy': ws.get('policy_version'),
        'project_id': p['id'], 'project_code': p['code'], 'project_revision': p['revision'],
        'sop_version': p.get('sop_version'), 'node_id': n['id'], 'node_key': n['key'],
        # Imported contract scope does not necessarily increment local revision.
        # Keep source timestamps out; immutable fields/relations define this scope.
        'quotes': sorted(p.get('quotes', []),key=lambda x:x['id']),
        'source_records': sorted(p.get('source_records', []),key=lambda x:x['id']),
        'source_scope_hash': p.get('source_scope_hash'),
        'owner_id': n.get('owner_id'), 'collaborator_ids': n.get('collaborator_ids', []),
        'seats': seats, 'seat_active': {seat: any(u['id'] == ident and u.get('active', True)
            for u in ws['users']) for seat, ident in seats.items()},
        'requirements': n.get('requirements', []),
        'tasks': [{k: v for k, v in task.items() if k != 'comments'} for task in n['tasks']],
        'evidence': [e for e in p.get('evidence', []) if e.get('node_id') == n['id']],
        'files': [f for f in p.get('files', []) if f.get('node_id') == n['id']],
    }
    if scope_version in (2,3):
        from .approval_scope import task_scope, quote_work_scope
        for key in ('quotes','source_records','source_scope_hash'):value.pop(key)
        value['quote_work_scope']=quote_work_scope(p.get('quotes',[]))
        value['scope_version']=scope_version
        value['project_existence']={key:bool(p.get(key)) for key in ('source_missing','archived_at','migrated_to')}
        value['node_existence']={key:bool(n.get(key)) for key in ('source_missing','archived_at','migrated_to')}
        value['tasks']=[dict(task_scope(task),status=task.get('status')) for task in n['tasks']]
        if scope_version==3:
            from .approval_scope import file_scope,quote_work_scope_v3
            value['files']=[file_scope(f) for f in value['files']]
            value['quote_work_scope']=quote_work_scope_v3(p.get('quotes',[]))
    return deepcopy(value)


def fingerprint(ws, p, n, reason='', impact='',scope_version=1):
    from .operations import digest
    return digest({'snapshot': snapshot(ws, p, n,scope_version), 'reason': reason, 'impact': impact})


def current(ws, p, n, item):
    version=item.get('skip_scope_version',1)
    return (version in (1,2,3) and item.get('content_hash') == fingerprint(ws, p, n, item.get('reason', ''), item.get('impact', ''),version)
            and n['key'] not in FINANCIAL
            and not p.get('archived_at') and not p.get('migrated_to')
            and not n.get('archived_at') and not n.get('source_completed') and n.get('status') not in ('completed', 'archived', 'superseded')
            and not needs_review(p) and declared(p) not in ('中止', '已結案'))


def valid_votes(ws, p, n, item):
    seats = skip_seats(p, n)
    actors = {}
    for vote in item.get('votes', []):
        actor = vote.get('actor_id'); seat = vote.get('seat')
        if (vote.get('result') == 'approved' and vote.get('content_hash') == item.get('content_hash')
                and seats.get(seat) == actor
                and any(u['id'] == actor and u.get('active', True) for u in ws['users'])):
            actors[seat] = actor
    return set(actors) == {'pm', 'supervisor'} and len(set(actors.values())) == 2


def valid_waiver(ws, p, n):
    item = next((r for r in ws.get('node_skip_requests', []) if r['id'] == n.get('skip_request_id')
                 and r.get('project_id') == p['id'] and r.get('node_id') == n['id']), None)
    if not item or n['status']!='approved_skipped' or item['status']!='applied' or not current(ws,p,n,item): return False
    if item.get('simulated'):
        return ws.get('environment')!='production' and valid_votes(ws,p,n,item)
    from .native_requests import receipt_valid
    return receipt_valid(ws,p,n,item,require_fresh=False)


def refresh_skips(ws, p):
    for item in ws.get('node_skip_requests', []):
        if item.get('project_id') != p['id']: continue
        n = next((n for n in p['nodes'] if n['id'] == item['node_id']), None)
        if item['status'] not in ('pending','approved','applied'):
            if n and n.get('skip_request_id')==item['id'] and item['status'] in ('withdrawn','rejected','invalidated'):
                if n['status']=='approved_skipped': n['status']=item['previous_node_status']
                n.pop('skip_request_id',None)
            continue
        if n and current(ws, p, n, item) and (item['status'] != 'applied' or valid_waiver(ws, p, n)):
            continue
        item.update(status='invalidated', invalidated_reason='案件、節點內容或核准職責已變更，須重新申請')
        if item.get('native_binding',{}).get('attempted'):
            item['remote_resolution_required']=True
        item['history'].append({'action': 'invalidated', 'created_at': now(),
                                'message': item['invalidated_reason']})
        if n and n.get('skip_request_id') == item['id']:
            if n['status'] == 'approved_skipped':
                n['status'] = item['previous_node_status']
            n.pop('skip_request_id', None)


def skip_summary(ws, p, n):
    item = next((r for r in reversed(ws.get('node_skip_requests', []))
                 if r['project_id'] == p['id'] and r['node_id'] == n['id']), None)
    if not item:
        return None
    valid = valid_waiver(ws, p, n)
    return {'request_id': item['id'], 'status': item['status'], 'valid': valid,
            'simulated': item.get('simulated', False),
            'label': ('核准跳過（模擬）' if item.get('simulated') else '核准跳過') if valid else '跳過申請：' + {
                'draft': '草稿', 'pending': '待核准', 'approved': '待套用',
                'rejected': '已駁回', 'withdrawn': '已撤回', 'invalidated': '已失效',
                'applied': '須重新核對'}.get(item['status'], item['status'])}


def apply_skip(ws, user, body, demo=False):
    action = body['action']; data = body.get('payload') or {}
    require(user.get('active', True), '帳號已停權')
    p = find(ws['projects'], body.get('project_id'), '案件')
    n = find(p['nodes'], body.get('node_id'), '節點')
    requests = ws.setdefault('node_skip_requests', [])
    refresh_skips(ws, p)
    require(n['key'] not in FINANCIAL, '計價與結案仍須雙方核對及結清，不能申請跳過', 409)
    require(not p.get('archived_at') and not p.get('migrated_to') and not n.get('archived_at')
            and not n.get('source_completed')
            and p.get('execution_status') != 'completed'
            and not needs_review(p) and declared(p) not in ('中止', '已結案')
            and n['status'] not in ('completed', 'archived', 'superseded'),
            '已完成、封存或中止的案件／節點不能申請跳過', 409)
    seats = skip_seats(p, n)
    if action == 'node_skip_create':
        from .business_policy import can_business_override
        require(user['id'] in (p.get('pm_id'), n.get('owner_id'), seats['supervisor'])
                or can_business_override(user), '只有 PM、節點負責人或主管可提出申請')
        require(n['status'] != 'approved_skipped', '此節點已有生效的跳過核准', 409)
        require(not any(r['project_id'] == p['id'] and r['node_id'] == n['id']
                        and (r['status'] in ('draft', 'pending', 'approved', 'applied') or r.get('remote_resolution_required')) for r in requests),
                '此節點已有進行中的跳過申請，請先處理或撤回', 409)
        reason = str(data.get('reason') or '').strip(); impact = str(data.get('impact') or '').strip()
        require(reason and impact, '請填寫跳過原因與對交付、時程的影響', 422)
        item = dict(id=uid(), project_id=p['id'], node_id=n['id'],
                    version=1 + max((r.get('version', 1) for r in requests
                                     if r['project_id'] == p['id'] and r['node_id'] == n['id']), default=0),
                    status='draft', reason=reason, impact=impact, simulated=bool(demo),
                    seats=seats, votes=[],skip_scope_version=3,snapshot=snapshot(ws, p, n,3),
                    content_hash=fingerprint(ws, p, n, reason, impact,3), created_by=user['id'], created_at=now(),
                    previous_node_status=n['status'], history=[])
        requests.append(item)
    else:
        item = find(requests, data.get('id'), '跳過申請')
        require(item['project_id'] == p['id'] and item['node_id'] == n['id'], '申請不屬於此節點', 409)
        if action == 'node_skip_withdraw':
            require(not item.get('native_binding',{}).get('attempted'),
                    '已送出 Lark 的申請須使用撤回審批入口，查回取消後才完成撤回',409)
            require(user['id'] in (item['created_by'], p.get('pm_id')), '只有申請人或 PM 可撤回')
            require(item['status'] in ('draft', 'pending', 'approved'), '此申請不能撤回', 409)
            require(str(data.get('reason') or '').strip(), '撤回需填寫原因', 422)
            item['status'] = 'withdrawn'
        else:
            native_apply=action=='node_skip_apply' and not demo and not item.get('simulated')
            if native_apply:
                from .native_requests import receipt_valid
                require(receipt_valid(ws,p,n,item,require_fresh=True),'原生審批回執未核實、已過期或範圍已變更，請先重新查回',409)
            else: require(demo and item.get('simulated'), '請透過原生 Lark 送審入口；草稿已保留，節點未跳過', 503)
            require(current(ws, p, n, item), '申請內容或負責人已變更，請撤回後重新申請', 409)
            require(all(seats.values()) and len(set(seats.values())) == 2,
                    '需指派兩位不同的 PM 與該組主管', 409)
            require(all(any(u['id'] == ident and u.get('active', True) for u in ws['users'])
                        for ident in seats.values()), '核准人尚未啟用', 409)
            if action == 'node_skip_submit':
                require(user['id'] in (item['created_by'], p.get('pm_id')), '只有申請人或 PM 可送出')
                require(item['status'] == 'draft', '僅草稿可以送出', 409)
                item.update(status='pending', submitted_at=now())
            elif action == 'node_skip_vote':
                require(item['status'] == 'pending', '此申請不在待核准狀態', 409)
                seat = data.get('seat'); result = data.get('result')
                require(seat in seats and user['id'] == seats[seat], '僅指定 PM／該組主管本人可核准')
                require(result in ('approved', 'rejected'), '核准結果錯誤', 422)
                require(not any(v['actor_id'] == user['id'] for v in item['votes']), '同一人不能重複核准或兼任兩票', 409)
                if result == 'rejected': require(str(data.get('reason') or '').strip(), '駁回需填寫原因', 422)
                item['votes'].append(dict(seat=seat, actor_id=user['id'], result=result,
                    reason=data.get('reason', ''), content_hash=item['content_hash'], created_at=now(), simulated=True))
                if result == 'rejected': item['status'] = 'rejected'
                elif valid_votes(ws, p, n, item): item['status'] = 'approved'
            elif action == 'node_skip_apply':
                require(user['id'] == p.get('pm_id'), '只有 PM 可套用跳過核准')
                require(item['status'] == 'approved' and (native_apply or valid_votes(ws, p, n, item)), '需 PM 與主管兩位不同人核准', 409)
                item.update(status='applied', applied_at=now(), applied_by=user['id'])
                n.update(status='approved_skipped', skip_request_id=item['id'])
            else:
                require(False, '未知跳過申請操作', 422)
    item['history'].append(dict(action=action, actor_id=user['id'], created_at=now(),
                               message=data.get('reason') or action, simulated=bool(demo)))
    from .operations import refresh_project_state
    refresh_project_state(p, ws)
    event(ws, user, action, p['id'], n['id'], message=data.get('reason') or action)
    return True
