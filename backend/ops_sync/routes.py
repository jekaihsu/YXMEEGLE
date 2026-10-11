"""Flag-gated local/mock API over the ops_sync engine. Registered only when FEATURE_LARK_AUTHORITATIVE_OPS is on, so with
the flag off these paths do not exist (404). The adapter is the in-workspace mock: nothing here talks to Lark.

Authorization reuses the app's existing session identity and project-lead rule (`operations.lead`); there is no new
auth model. The acting identity is always the signed-in user, never a body field.
"""
from fastapi import Request
from fastapi.responses import JSONResponse

from ..input_validation import json_object
from ..operations import lead
from ..workflow import fail, find, require
from . import flow as F
from . import values as V
from .clock import SystemClock
from .adapter import BINDING, MockLarkAdapter
from .commands import CommandEnvelope
from .eligibility import PersonIdentity
from .engine import CONFIRMED, CONFLICT, FAILED, QUEUED, UNKNOWN_S, WAITING, IdentityCollision, OpsEngine
from .workspace_store import WorkspaceStore
from .unit import JointOperations

ADAPTER_NAMESPACE = 'ops_sync_mock_lark'
APPROVAL_FIELDS = ('case.deadline', 'node.deadline')
NOTICE = '本機模擬（mock）垂直切片：未連線 Lark，不會讀寫任何 Lark 資料。'
UI_STATES = {WAITING: 'waiting_approval', QUEUED: 'pending', UNKNOWN_S: 'unknown', CONFIRMED: 'confirmed',
             CONFLICT: 'conflict', FAILED: 'failed'}


def project_of(entity_id):
    parts = entity_id.split(':')
    if len(parts) < 2 or parts[0] not in ('case', 'node') or not parts[1]:
        fail('找不到對應的案件', 404)
    return parts[1]


def _value_view(blob):
    if not isinstance(blob, dict) or blob.get('t') not in ('set', 'clear'):
        return {'kind': 'unknown', 'value': None}
    return {'kind': blob['t'], 'value': blob.get('v')}


def command_view(cmd):
    env = cmd['envelope']
    return {'command_id': env['command_id'], 'entity_id': env['entity_id'], 'field_id': env['field_id'],
            'state': UI_STATES[cmd['state']], 'reason': cmd['reason'], 'actor': env['actor'],
            'expected': _value_view(env['expected']), 'expected_revision': env['expected_revision'],
            'intended': _value_view(env['intended']), 'attempts': len(cmd['attempts']),
            'reconcile': cmd['reconcile'] and {k: cmd['reconcile'][k] for k in ('phase', 'reads', 'blocker')},
            'created_at': cmd['created_at']}


def conflict_view(item):
    return {'conflict_id': item['conflict_id'], 'command_id': item['command_id'], 'entity_id': item['entity_id'],
            'field_id': item['field_id'], 'reason': item['reason'], 'open': not item['resolution'],
            'expected': {**_value_view(item['expected']['value']), 'revision': item['expected']['revision']},
            'current': {**_value_view(item['current']['value']), 'revision': item['current']['revision']},
            'intended': _value_view(item['intended']), 'resolution': item['resolution'] and item['resolution']['mode']}


def _value(body, key):
    raw = body.get(key)
    if isinstance(raw, dict) and raw.get('t') == 'clear':
        return V.CLEAR
    if isinstance(raw, dict) and raw.get('t') == 'set' and isinstance(raw.get('v'), str):
        return V.SetValue(raw['v'])
    fail(f'{key} 必須是 {{"t":"set","v":…}} 或 {{"t":"clear"}}', 422)


def register(app, identity, load, sessions, WorkspaceRow, clock=None):
    clk = clock or SystemClock()

    def engine_for(wid, authorizer=None):
        factory = app.state.ops_store_for
        require(factory is not None, '功能未啟用', 404)
        mock = MockLarkAdapter(WorkspaceStore(sessions, wid, namespace=ADAPTER_NAMESPACE))
        return OpsEngine(factory(wid), mock, clock=clock, authorizer=authorizer, approval_required=APPROVAL_FIELDS), mock

    def access(request, entity_id=None):
        data, user = identity(request)
        with sessions() as db:
            row = db.get(WorkspaceRow, data['wid'])
            require(row is not None, '工作區不存在', 404)
            state = load(db, row)
        if entity_id is None:
            return data, user, state
        project = find(state['projects'], project_of(entity_id), '案件')
        require(lead(user, project), '只有案件負責人可操作營運同步', 403)
        return data, user, state

    def visible(user, state, entity_id):
        parts = entity_id.split(':')
        project = next((p for p in state['projects'] if len(parts) > 1 and p['id'] == parts[1]), None)
        return bool(project and lead(user, project))

    def guarded(fn):
        try:
            return fn()
        except IdentityCollision as exc:
            fail(str(exc), 409)
        except V.OpsError as exc:
            fail(f'{exc.code}: {exc}', 409 if exc.code in ('conflict_not_open', 'baseline_changed', 'baseline_unavailable')
                 else 404 if exc.code == 'unknown_entity' else 422)

    def snapshot(engine, user, state):
        snap = engine.snapshot()
        cmds = [command_view(c) for c in sorted(snap['commands'].values(), key=lambda c: c['seq'])
                if visible(user, state, c['envelope']['entity_id'])]
        conflicts = [conflict_view(c) for c in snap['conflicts'].values() if visible(user, state, c['entity_id'])]
        return {'notice': NOTICE, 'live': False, 'commands': cmds, 'conflicts': conflicts}

    # -- synthetic local vertical flow (all fixture data; mock adapter only) --------------------------------------
    def flow_ctx(request, entity_id=None, body=None):
        data, user, state = access(request, entity_id)
        fx = F.Fixtures(clk, user['id'], entity_id is not None)
        domain, deadlines = fx.services(app.state.ops_store_for(data['wid']))
        guarded(lambda: F.sync(domain, state))
        engine, mock = engine_for(data['wid'], fx.authorizer())
        require(MockLarkAdapter.live is False, '僅限本機模擬', 403)
        return data, user, state, fx, domain, deadlines, engine, mock

    def flow_view(user, state, fx, domain, engine, extra=None):
        led = {p['id'] for p in state['projects'] if lead(user, p)}
        snap = snapshot(engine, user, state)
        return {**snap, 'mapping_notice': F.MAPPING_NOTICE, 'roster': F.roster_view(fx), 'mock_outcomes': list(F.MOCK_OUTCOMES),
                'entities': F.entities_view(domain, lambda pid: pid in led, fx),
                'dispatch_denial': F.dispatch_denial(engine.snapshot()), **(extra or {})}

    def flow_ids(body):
        entity_id, command_id = body.get('entity_id'), body.get('command_id')
        require(isinstance(entity_id, str) and isinstance(command_id, str) and command_id.strip(), '缺少 entity_id 或 command_id', 422)
        return entity_id, command_id

    def inject(mock, outcome, entity_id, field_id):
        require(outcome in (None, *F.MOCK_OUTCOMES), '不支援的模擬情境', 422)
        if outcome in ('timeout_after_commit', 'permission_lost'):
            mock.inject(outcome)
        elif outcome == 'concurrent_edit':
            mock.direct_edit(entity_id, field_id, V.SetValue(F.person('u-manager').key) if 'pm' in field_id or 'resp' in field_id
                             else V.SetValue('2026-12-31'))

    def run_dispatch(engine, mock, body, entity_id, field_id):
        inject(mock, body.get('mock_outcome'), entity_id, field_id)
        guarded(engine.run_once)

    @app.get('/api/ops-sync/flow')
    def flow(request: Request):
        data, user, state = access(request)
        fx = F.Fixtures(clk, user['id'], False)
        domain, _ = fx.services(app.state.ops_store_for(data['wid']))
        guarded(lambda: F.sync(domain, state))
        engine, _ = engine_for(data['wid'], fx.authorizer())
        return JSONResponse(flow_view(user, state, fx, domain, engine))

    @app.post('/api/ops-sync/flow/assign')
    async def flow_assign(request: Request):
        body = await json_object(request)
        entity_id, command_id = flow_ids(body)
        people = body.get('person_ids')
        require(isinstance(people, list) and all(isinstance(p, str) for p in people), 'person_ids 必須是人員代號清單', 422)
        data, user, state, fx, domain, deadlines, engine, mock = flow_ctx(request, entity_id)
        is_case = entity_id.startswith('case:')
        candidates = V.CLEAR if not people else guarded(lambda: [F.person(p) for p in people])
        field_id = 'case.pm' if is_case else 'node.responsible'
        intended = V.CLEAR if not people else V.SetValue(candidates[0].key)
        unit = JointOperations(domain, deadlines, engine)
        base = guarded(lambda: unit.read(entity_id, field_id))
        envelope = unit.envelope(body, user['id'], entity_id, command_id, field_id, intended, base)
        result = guarded(lambda: unit.assign(envelope, base, fx.actor, candidates, body.get('reason') or ''))
        if result['status'] in ('denied', 'conflict'):
            fail(F.reason_text(result['reason']), 422)
        if not result['duplicate'] and (result['status'] in ('assigned', 'cleared') or
                                        result['status'] == 'unchanged' and intended != base.fresh['value']):
            run_dispatch(engine, mock, body, entity_id, field_id)
        command = next((c for c in snapshot(engine, user, state)['commands'] if c['command_id'] == command_id), None)
        return JSONResponse(flow_view(user, state, fx, domain, engine, {'outcome': {'status': result['status'], 'duplicate': result['duplicate']},
                                                                        'command': command}))

    @app.post('/api/ops-sync/flow/propose')
    async def flow_propose(request: Request):
        body = await json_object(request)
        entity_id, command_id = flow_ids(body)
        intended, expected_rev = body.get('intended'), body.get('expected_revision')
        require(isinstance(intended, str), 'intended 必須是日期字串', 422)
        data, user, state, fx, domain, deadlines, engine, mock = flow_ctx(request, entity_id)
        expected = V.SetValue(body['expected']) if isinstance(body.get('expected'), str) else V.CLEAR
        field_id = 'case.deadline' if entity_id.startswith('case:') else 'node.deadline'
        unit = JointOperations(domain, deadlines, engine)
        base = guarded(lambda: unit.read(entity_id, field_id))
        envelope = guarded(lambda: unit.envelope(body, user['id'], entity_id, command_id, field_id,
                                               V.SetValue(V.normalize_date(intended)), base))
        result = guarded(lambda: unit.propose(envelope, base, expected, expected_rev, fx.actor))
        if result['status'] == 'denied':
            fail(F.reason_text(result['reason']), 422)
        if result['status'] != 'waiting_approval':
            fail(F.reason_text(result['reason']), 409 if result['status'] == 'conflict' else 422)
        command = next((c for c in snapshot(engine, user, state)['commands'] if c['command_id'] == command_id), None)
        return JSONResponse(flow_view(user, state, fx, domain, engine, {'outcome': {'status': 'proposed', 'duplicate': result['duplicate']},
                                                                        'command': command}))

    @app.post('/api/ops-sync/flow/decide')
    async def flow_decide(request: Request):
        """MOCK decision on a proposal. Approval is granted only by consuming a mock receipt through the domain approval
        path, which binds it to the delivery command (YXS-49). The signed-in user is never an approver."""
        body = await json_object(request)
        entity_id, command_id = flow_ids(body)
        decision = body.get('decision')
        require(decision in F.DECISIONS, 'decision 必須是 approved、rejected 或 stale', 422)
        data, user, state, fx, domain, deadlines, engine, mock = flow_ctx(request, entity_id)
        require(fx.actor not in F.APPROVERS, '模擬核准人不得為操作者', 403)
        prop = deadlines.proposal(entity_id, command_id)
        require(prop is not None, '找不到申請', 404)
        field_id = prop['field_id']
        receipt = None if decision == 'rejected' else F.mock_receipt(deadlines, entity_id, command_id, decision)
        unit = JointOperations(domain, deadlines, engine)
        out = guarded(lambda: unit.decide(entity_id, command_id, decision, F.APPROVERS[0], receipt))
        status, reason, duplicate = out['status'], out.get('reason'), out['duplicate']
        if decision == 'approved' and status == 'denied':
            fail(F.reason_text(reason), 422)
        if decision == 'approved' and status == 'confirmed' and not duplicate:
            run_dispatch(engine, mock, body, entity_id, field_id)
        command = next((c for c in snapshot(engine, user, state)['commands'] if c['command_id'] == command_id), None)
        return JSONResponse(flow_view(user, state, fx, domain, engine, {
            'outcome': {'status': status, 'reason': reason, 'reason_text': F.reason_text(reason), 'duplicate': duplicate,
                        'decision': decision, 'mock': True}, 'command': command}))

    @app.post('/api/ops-sync/flow/resume-dispatch')
    async def flow_resume(request: Request):
        body = await json_object(request)
        data, user, state = access(request)
        require(any(lead(user, p) for p in state['projects']), '只有案件負責人可恢復派送', 403)
        fx = F.Fixtures(clk, user['id'], True)
        domain, _ = fx.services(app.state.ops_store_for(data['wid']))
        engine, _ = engine_for(data['wid'], fx.authorizer())
        reason = body.get('reason')
        require(reason is None or isinstance(reason, str), 'reason 必須是字串', 422)
        guarded(lambda: engine.resume_dispatch(reason))
        guarded(engine.run_once)
        return JSONResponse(flow_view(user, state, fx, domain, engine))

    @app.post('/api/ops-sync/flow/reconcile')
    async def flow_reconcile(request: Request):
        """Re-read a delivery whose outcome is unknown. Never creates or changes intent: the domain record already holds it."""
        body = await json_object(request)
        command_id = body.get('command_id')
        data, user, state = access(request)
        engine, _ = engine_for(data['wid'])
        cmd = engine.snapshot()['commands'].get(command_id) if isinstance(command_id, str) else None
        require(cmd is not None, '找不到指令', 404)
        data, user, state, fx, domain, _, engine, _ = flow_ctx(request, cmd['envelope']['entity_id'])
        guarded(lambda: (engine.request_recovery(command_id), engine.run_once()))
        return JSONResponse(flow_view(user, state, fx, domain, engine))

    @app.post('/api/ops-sync/flow/resolve-conflict')
    async def flow_resolve(request: Request):
        """Resolve an open seat conflict THROUGH the domain: the chosen person goes through the same eligibility / role /
        history gates as an assignment before the engine writes it, so the domain seat, projection and mock converge."""
        body = await json_object(request)
        conflict_id, command_id, mode = body.get('conflict_id'), body.get('command_id'), body.get('resolution')
        require(isinstance(conflict_id, str) and isinstance(command_id, str) and command_id.strip(), '缺少 conflict_id 或 command_id', 422)
        require(mode in ('keep_current', 'apply_intended'), 'resolution 必須是 keep_current 或 apply_intended', 422)
        data, user, state = access(request)
        conflict = engine_for(data['wid'])[0].snapshot()['conflicts'].get(conflict_id)
        require(conflict is not None, '找不到衝突', 404)
        entity_id, field_id = conflict['entity_id'], conflict['field_id']
        data, user, state, fx, domain, deadlines, engine, mock = flow_ctx(request, entity_id)
        require(field_id in ('case.pm', 'node.responsible'), '期限衝突請以新的期限申請處理', 422)
        if conflict['resolution']:
            require(conflict['resolution']['command_id'] == command_id, '此衝突已處理', 409)
            return JSONResponse(flow_view(user, state, fx, domain, engine))
        expected, expected_rev = _value(body, 'expected'), body.get('expected_revision')
        unit = JointOperations(domain, deadlines, engine)
        base = guarded(lambda: unit.read(entity_id, field_id))
        require(V.encode(base.fresh['value']) == V.encode(expected) and base.fresh['revision'] == expected_rev,
                F.reason_text('baseline_changed'), 409)
        target = expected if mode == 'keep_current' else V.decode(conflict['intended'])
        try:
            candidates = V.CLEAR if target is V.CLEAR else [PersonIdentity.from_key(target.value)]
        except ValueError:
            fail('衝突中的值不是有效的人員代號，無法處理', 422)
        envelope = CommandEnvelope(command_id, entity_id, field_id, expected, expected_rev, target, user['id'], 'app',
                                   engine._now(), BINDING, resolves=conflict_id, resolution=mode)
        result = guarded(lambda: unit.assign(envelope, base, fx.actor, candidates,
                                            body.get('reason') or f'conflict {mode}', conflict_id, mode))
        if result['status'] in ('denied', 'conflict'):
            fail(F.reason_text(result['reason']), 422)
        run_dispatch(engine, mock, body, entity_id, field_id)
        command = next((c for c in snapshot(engine, user, state)['commands'] if c['command_id'] == command_id), None)
        return JSONResponse(flow_view(user, state, fx, domain, engine, {'outcome': {'status': result['status'], 'duplicate': False},
                                                                        'command': command}))
