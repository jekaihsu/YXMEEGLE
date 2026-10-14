"""HTTP routes. Every route answers 404 while NODE_ASSIGNMENT_ENABLED is off."""
import json
import re
from dataclasses import replace
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .domain import NodeAction, NodeKey
from .errors import Failure
from .operations import (
    find_task, parse_create_task, parse_node_command, parse_patch_task, plan_create_task, plan_node,
    plan_patch_task, request_id)
from .service import Context, NodeAssignmentService

PREFIX = '/api/projects/{project_id}/node-assignments'
MAX_BODY = 16 * 1024
NODE_ROUTE_ACTIONS = {a.value: a for a in NodeAction if a is not NodeAction.CREATE_TASK}
TASK_ID = re.compile(r'rec[A-Za-z0-9]{1,40}')


def register(app, *, identity, load_case, sessions, receipt_model, audit_model, cfg, skipped_nodes,
             transport=None, client_options=None, clock=None):
    """load_case(session_data, user, project_id) -> (state, project) for a case visible to that user."""
    options = {'transport': transport, 'client_options': client_options}
    if clock is not None:
        options['clock'] = clock
    service = NodeAssignmentService(cfg, sessions=sessions, receipt_model=receipt_model, audit_model=audit_model,
                                    skipped_nodes=skipped_nodes, **options)
    enabled = service.config.enabled

    def respond(result=None, failure=None):
        if failure is not None:
            return JSONResponse(failure.body(), status_code=failure.status, headers={'Cache-Control': 'no-store'})
        status, body, replayed = result
        headers = {'Cache-Control': 'no-store'}
        if replayed:
            headers['Idempotent-Replayed'] = 'true'
        return JSONResponse(body, status_code=status, headers=headers)

    def disabled():
        return respond(failure=Failure('disabled', '節點指派功能尚未啟用'))

    def context(request, project_id):
        data, user = identity(request)
        state, project = load_case(data, user, project_id)

        def authorize():
            fresh_data, fresh_user = identity(request)
            if fresh_data['wid'] != data['wid'] or fresh_user['id'] != user['id'] or not fresh_user.get('active', True):
                raise Failure('forbidden', '登入身分已變更，請重新整理後再操作')
        return Context(data['wid'], user, state, project, authorize)

    def node_key(value):
        try:
            return NodeKey(value)
        except ValueError:
            raise Failure('not_found', '沒有這個節點') from None

    def guarded(run):
        try:
            return respond(run())
        except Failure as exc:
            return respond(failure=exc)

    def body_of(raw):
        if len(raw) > MAX_BODY:
            raise Failure('payload_too_large', '請求內容過大，請縮減文字')
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise Failure('invalid', '請求內容必須是有效的 JSON') from None
        if not isinstance(body, dict):
            raise Failure('invalid', '請求內容必須是 JSON 物件')
        return body

    async def mutation(request, project_id, prepare):
        """Authorize and load the case before reading any input, then plan."""
        if not enabled:
            return disabled()
        raw = await request.body()
        return await run_in_threadpool(guarded, lambda: prepare(context(request, project_id), body_of(raw)))

    def payload(body):
        return {'body': {k: v for k, v in body.items() if k != 'request_id'}}

    @app.get(PREFIX)
    def overview(request: Request, project_id: str):
        if not enabled:
            return disabled()
        return guarded(lambda: (200, service.overview(context(request, project_id)), False))

    @app.get(PREFIX + '/nodes/{key}')
    def detail(request: Request, project_id: str, key: str):
        if not enabled:
            return disabled()
        return guarded(lambda: (200, service.detail(context(request, project_id), node_key(key)), False))

    @app.post(PREFIX + '/nodes/{key}/tasks')
    async def create_task(request: Request, project_id: str, key: str):
        def prepare(ctx, body):
            target, rid, command = node_key(key), request_id(body), parse_create_task(body)

            def plan(s, resumed):
                return plan_create_task(s, command, resumed.client_token if resumed else str(uuid4()))
            return service.mutate(ctx, target, 'create_task', rid, payload(body), plan)
        return await mutation(request, project_id, prepare)

    @app.patch(PREFIX + '/nodes/{key}/tasks/{task_id}')
    async def update_task(request: Request, project_id: str, key: str, task_id: str):
        def prepare(ctx, body):
            target = node_key(key)
            if not TASK_ID.fullmatch(task_id):
                raise Failure('not_found', '沒有這個任務')
            rid, command = request_id(body), parse_patch_task(body)

            def plan(s, resumed):
                current = replace(command, expected_revision=resumed.base_revision) if resumed else command
                return plan_patch_task(s, find_task(s, task_id), current)
            return service.mutate(ctx, target, 'update_task', rid, {'task_id': task_id, **payload(body)}, plan)
        return await mutation(request, project_id, prepare)

    @app.post(PREFIX + '/nodes/{key}/{action}')
    async def node_action(request: Request, project_id: str, key: str, action: str):
        def prepare(ctx, body):
            target = node_key(key)
            if action not in NODE_ROUTE_ACTIONS:
                raise Failure('not_found', '不支援的節點操作')
            act = NODE_ROUTE_ACTIONS[action]
            rid, command = request_id(body), parse_node_command(act, body)

            def plan(s, resumed):
                return plan_node(s, command, resumed.base_revision if resumed else command.expected_revision)
            return service.mutate(ctx, target, act.value, rid, payload(body), plan)
        return await mutation(request, project_id, prepare)

    return service
