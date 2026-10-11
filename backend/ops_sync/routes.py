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
from . import values as V
from .adapter import MockLarkAdapter
from .commands import CommandEnvelope
from .engine import CONFIRMED, CONFLICT, FAILED, QUEUED, UNKNOWN_S, WAITING, IdentityCollision, OpsEngine
from .workspace_store import WorkspaceStore

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
    def engine_for(wid):
        factory = app.state.ops_store_for
        require(factory is not None, '功能未啟用', 404)
        mock = MockLarkAdapter(WorkspaceStore(sessions, wid, namespace=ADAPTER_NAMESPACE))
        return OpsEngine(factory(wid), mock, clock=clock, approval_required=APPROVAL_FIELDS), mock

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
            fail(f'{exc.code}: {exc}', 409 if exc.code in ('conflict_not_open', 'baseline_changed', 'baseline_unavailable') else 422)

    def snapshot(engine, user, state):
        snap = engine.snapshot()
        cmds = [command_view(c) for c in sorted(snap['commands'].values(), key=lambda c: c['seq'])
                if visible(user, state, c['envelope']['entity_id'])]
        conflicts = [conflict_view(c) for c in snap['conflicts'].values() if visible(user, state, c['entity_id'])]
        return {'notice': NOTICE, 'live': False, 'commands': cmds, 'conflicts': conflicts}

    @app.get('/api/ops-sync/status')
    def status(request: Request):
        data, user, state = access(request)
        engine, _ = engine_for(data['wid'])
        return JSONResponse(snapshot(engine, user, state))

    @app.post('/api/ops-sync/commands')
    async def submit(request: Request):
        body = await json_object(request)
        entity_id = body.get('entity_id')
        require(isinstance(entity_id, str) and isinstance(body.get('command_id'), str), '缺少 entity_id 或 command_id', 422)
        data, user, state = access(request, entity_id)
        engine, _ = engine_for(data['wid'])
        field_id = body.get('field_id')
        envelope = CommandEnvelope(
            body['command_id'], entity_id, field_id, _value(body, 'expected'), body.get('expected_revision'),
            _value(body, 'intended'), user['id'], 'app', body.get('occurred_at') or engine._now(),
            body.get('schema_binding_version') or '')

        def run():
            engine.observe(entity_id, [field_id] if field_id in V.FIELD_TYPES else None)
            result = engine.submit(envelope)
            if not result['duplicate']:
                engine.run_once()
            return result
        result = guarded(run)
        view = next((c for c in snapshot(engine, user, state)['commands'] if c['command_id'] == body['command_id']), None)
        return JSONResponse({'accepted': True, 'duplicate': result['duplicate'], 'command': view})

    @app.post('/api/ops-sync/conflicts/{conflict_id}/resolve')
    async def resolve(conflict_id: str, request: Request):
        body = await json_object(request)
        data, user, state = access(request)
        engine, _ = engine_for(data['wid'])
        conflict = engine.snapshot()['conflicts'].get(conflict_id)
        require(conflict is not None, '找不到衝突', 404)
        access(request, conflict['entity_id'])
        mode = body.get('resolution')
        envelope = CommandEnvelope(
            body.get('command_id') or '', conflict['entity_id'], conflict['field_id'], _value(body, 'expected'),
            body.get('expected_revision'), _value(body, 'intended'), user['id'], 'app', engine._now(),
            body.get('schema_binding_version') or '', resolves=conflict_id, resolution=mode)
        guarded(lambda: engine.resolve_conflict(envelope, conflict_id, mode))
        guarded(engine.run_once)
        return JSONResponse(snapshot(engine, user, state))

    @app.post('/api/ops-sync/reconcile')
    async def reconcile(request: Request):
        body = await json_object(request)
        command_id = body.get('command_id')
        data, user, state = access(request)
        engine, _ = engine_for(data['wid'])
        cmd = engine.snapshot()['commands'].get(command_id) if isinstance(command_id, str) else None
        require(cmd is not None, '找不到指令', 404)
        access(request, cmd['envelope']['entity_id'])
        guarded(lambda: (engine.request_recovery(command_id), engine.run_once()))
        return JSONResponse(snapshot(engine, user, state))
