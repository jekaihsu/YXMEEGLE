from contextlib import nullcontext
import json
import threading
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.concurrency import run_in_threadpool

from ..production_access import hr_view_allowed
from ..request_timing import timed_lock
from .domain import Failure, require
from .service import Context, Service, authorize, has_reader_grant, can_manage

PREFIX = '/api/projects/{project_id}'
ROSTER_FAILURE_RETRY_SECONDS = 30
MAX_BODY = 64 * 1024
ERROR_TEXT = {'local_node_only': '請使用此案件的正式節點流程', 'local_node_blocked': '節點目前無法操作', 'node_revision_conflict': '節點已更新，請重新載入後再試', 'legacy_case_requires_opt_in': '舊案需先確認套用 SOP', 'node_not_enrolled': '此節點尚未套用 SOP', 'node_already_started_or_finished': '已開始或已完成的節點不能套用 SOP', 'case_identity_unresolved': '案件識別待核對', 'confirmation_required': '請確認套用的節點', 'case_not_found': '找不到此案件或沒有讀取權限', 'result_note_required': '請填寫結果說明', 'task_revision_conflict': '任務已被更新，請重新載入後再試',
              'sop_import_forbidden': '你沒有操作此 SOP 任務的權限', 'completion_evidence_missing': '此任務需先完成佐證或審核',
              'applicability_unresolved': '需先確認任務適用', 'invalid_transition': '目前任務狀態不可執行此操作'}


def register(app, *, identity, load_case, sessions, cfg, quote_view=None, workspace=None, persist_case=None, phase=None, load_assignees=None, load_tasks=None):
    flag = lambda name: lambda: str(cfg.get(name, 'false')).lower() == 'true'
    service = Service(sessions, writes_enabled=flag('SOP_TASK_WRITES_ENABLED'),
                      local_cases_enabled=flag('LOCAL_CASE_CREATION_ENABLED'),
                      auto_enabled=flag('SOP_AUTO_ENROLL_ENABLED'), auto_since=lambda: cfg.get('SOP_AUTO_ENROLL_SINCE'))

    roster_refresh_lock = threading.Lock()
    roster_retry_at = 0

    def context(request, project_id, case_loader=load_case):
        from .authority import global_manager

        def roster(fresh=False):
            nonlocal roster_retry_at
            if fresh and hasattr(request.state, 'sop_roster_error'):
                raise request.state.sop_roster_error
            if fresh and not hasattr(request.state, 'sop_roster'):
                with timed_lock(roster_refresh_lock):
                    try:
                        require(service.clock() >= roster_retry_at, 'roster_unavailable', 503)
                        request.state.sop_roster = service.roster_provider(fresh=True)
                        require(not service.roster_required or request.state.sop_roster is not None, 'roster_unavailable', 503)
                    except Failure as exc:
                        if exc.code != 'roster_unavailable':
                            raise
                        if service.clock() >= roster_retry_at:
                            roster_retry_at = service.clock() + ROSTER_FAILURE_RETRY_SECONDS
                        request.state.sop_roster_error = exc
                        raise
            if hasattr(request.state, 'sop_roster'):
                return request.state.sop_roster
            return service.roster_provider()

        data, user = identity(request)
        require(user.get('active', True), 'sop_import_forbidden', 403)
        assigned_only = not has_reader_grant(user)
        with (phase(request, 'load') if phase else nullcontext()):
            state, project = case_loader(data, user, project_id)
        ctx = Context(data['wid'], user, state, project, lambda: context(request, project_id, case_loader),
                      assigned_only=False)
        ctx.roster_required = service.roster_required
        ctx.roster_loader = roster
        ctx.roster = roster()
        participant = assigned_only and service.participates(data['wid'], user['id'], project_id)
        roster_identity = data.get('mode') == 'lark' or user.get('oauth_identity', {}).get('open_id') == user['id']
        executor_transition = request.url.path.endswith('/transition') and (not assigned_only or service.participates(
            data['wid'], user['id'], project_id, executor_task_id=request.path_params['task_id']))
        needs_authority = not project.get('sop_assigned_only') and not executor_transition
        if (ctx.roster_required and roster_identity and not global_manager(ctx) and needs_authority
                and (ctx.roster is None or request.method != 'GET')):
            try:
                ctx.refresh_roster(service.roster_provider)
                require(ctx.roster is not None, 'roster_unavailable', 503)
            except Failure as exc:
                if request.method != 'GET' or exc.code != 'roster_unavailable':
                    raise
        ctx.assigned_only = assigned_only and not can_manage(ctx)
        require(not ctx.assigned_only or participant, 'sop_import_forbidden', 403)
        if project.get('sop_assigned_only'):
            ctx.assigned_only = True
        authorize(ctx)
        return ctx

    def respond(run):
        try:
            body, status = run(), 200
        except Failure as exc:
            body, status = {'code': exc.code, 'detail': ERROR_TEXT.get(exc.code, exc.code), **exc.context}, exc.status
        except HTTPException as exc:
            code = {401: 'session_expired', 403: 'identity_forbidden', 404: 'case_not_found',
                    409: 'workspace_conflict'}.get(exc.status_code, 'invalid_request')
            body, status = {'code': code, 'detail': ERROR_TEXT.get(code, code)}, exc.status_code
        except (IntegrityError, OperationalError):
            body, status = {'code': 'import_unavailable', 'detail': 'import_unavailable'}, 503
        return JSONResponse(body, status_code=status, headers={'Cache-Control': 'no-store'})

    async def mutation(request, project_id, run, resolve=None, *, refresh_roster=True):
        try:
            ctx = await run_in_threadpool(resolve or context, request, project_id)
        except (Failure, HTTPException) as exc:
            def denied():
                raise exc
            return respond(denied)
        try:
            length = request.headers.get('content-length')
            if length is not None:
                require(length.isascii() and length.isdigit() and int(length) <= MAX_BODY, 'invalid_request')
            raw = bytearray()
            async for chunk in request.stream():
                require(len(raw) + len(chunk) <= MAX_BODY, 'invalid_request')
                raw.extend(chunk)
        except Failure as exc:
            return JSONResponse({'code': exc.code, 'detail': exc.code}, status_code=exc.status,
                                headers={'Cache-Control': 'no-store'})

        def execute():
            require(len(raw) <= MAX_BODY, 'invalid_request')
            try:
                body = json.loads(raw)
            except (ValueError, RecursionError):
                raise Failure('invalid_request') from None
            require(isinstance(body, dict), 'invalid_request')
            from .authority import global_manager
            if refresh_roster and isinstance(ctx, Context) and not global_manager(ctx):
                ctx.refresh_roster(service.roster_provider)
            return run(ctx, body)
        return await run_in_threadpool(respond, execute)

    @app.post(PREFIX + '/sop/ensure')
    def ensure(request: Request, project_id: str):
        from .ensure import ensure_local
        from ..node_assignment.errors import Failure as NodeFailure

        def run():
            try:
                data, user = identity(request)
                require(user.get('active', True), 'sop_import_forbidden', 403)
                _, project = load_case(data, user, project_id)
                if project.get('case_type') != 'intake' and str(project.get('code') or '').strip():
                    nodes = getattr(app.state, 'node_assignment', None)
                    if nodes is None:
                        return {'state': 'not_ready', 'reason': 'writes_disabled'}
                    return nodes.ensure_sop(request, project_id)
                return ensure_local(service, context(request, project_id))
            except (Failure, NodeFailure) as exc:
                if exc.code == 'roster_unavailable':
                    raise Failure('roster_unavailable', 503) from None
                if exc.code in {'sop_import_forbidden', 'forbidden'}:
                    raise Failure(exc.code, 403) from None
                if exc.status == 404:
                    raise Failure(exc.code, 404) from None
                reason = {'import_unavailable': 'writes_disabled', 'template_unavailable': 'no_template'}.get(exc.code, exc.code)
                return {'state': 'not_ready', 'reason': reason}
        return respond(run)

    @app.get('/api/sop-templates')
    def templates(request: Request):
        def run():
            data, user = identity(request)
            return service.templates(data['wid'], user)
        return respond(run)

    @app.get('/api/sop-templates/{version_id}')
    def template(request: Request, version_id: str):
        def run():
            data, user = identity(request)
            return service.templates(data['wid'], user, version_id)
        return respond(run)

    @app.post('/api/sop-templates/{version_id}/publish')
    def publish(request: Request, version_id: str):
        def run():
            data, user = identity(request)
            return service.publish_version(data['wid'], user, version_id)
        return respond(run)

    @app.get('/api/sop-import/readiness')
    def readiness(request: Request):
        def run():
            data, user = identity(request)
            return service.readiness(data['wid'], user)
        return respond(run)

    @app.post(PREFIX + '/sop-import/opt-in')
    async def opt_in(request: Request, project_id: str):
        return await mutation(request, project_id, service.opt_in)

    @app.post(PREFIX + '/sop-import/retry')
    async def retry(request: Request, project_id: str):
        return await mutation(request, project_id, service.retry_enrollment)

    @app.get(PREFIX + '/sop-tasks')
    def tasks(request: Request, project_id: str, node_key: str = None):
        return respond(lambda: service.overview(context(request, project_id, load_tasks or load_case), node_key))

    @app.post(PREFIX + '/sop-import/preview')
    async def preview(request: Request, project_id: str):
        return await mutation(request, project_id, service.preview)

    @app.post(PREFIX + '/sop-import/apply')
    async def apply(request: Request, project_id: str):
        return await mutation(request, project_id, service.apply)

    @app.get(PREFIX + '/sop-assignees')
    def assignees(request: Request, project_id: str, node_key: str = None, scope: str = None, q: str = None, limit: int = None, cursor: str = None):
        return respond(lambda: service.assignees(context(request, project_id, load_assignees or load_case), lambda user: hr_view_allowed(user, cfg), node_key=node_key, scope=scope, q=q, limit=limit, cursor=cursor))

    @app.get(PREFIX + '/sop-import/runs/{request_id}')
    def receipt(request: Request, project_id: str, request_id: str):
        return respond(lambda: service.receipt(context(request, project_id), request_id))

    @app.post(PREFIX + '/sop-tasks')
    async def manual(request: Request, project_id: str):
        return await mutation(request, project_id, service.manual)

    @app.patch(PREFIX + '/sop-tasks/{task_id}')
    async def patch(request: Request, project_id: str, task_id: str):
        return await mutation(request, project_id, lambda ctx, body: service.mutate(ctx, task_id, body))

    @app.post(PREFIX + '/sop-tasks/{task_id}/test-tag')
    async def test_tag(request: Request, project_id: str, task_id: str):
        return await mutation(request, project_id, lambda ctx, body: service.tag_test(ctx, task_id, body))

    @app.post(PREFIX + '/sop-tasks/{task_id}/cleanup-test')
    async def cleanup_test(request: Request, project_id: str, task_id: str):
        return await mutation(request, project_id, lambda ctx, body: service.cleanup_test(ctx, task_id, body))

    @app.post(PREFIX + '/sop-tasks/{task_id}/transition')
    async def transition(request: Request, project_id: str, task_id: str):
        return await mutation(request, project_id, lambda ctx, body: service.mutate(ctx, task_id, body, transition=True), refresh_roster=False)

    @app.post(PREFIX + '/sop-nodes/{node_key}')
    async def local_node(request: Request, project_id: str, node_key: str):
        from .local_nodes import mutate
        return await mutation(request, project_id, lambda ctx, body: mutate(service, ctx, node_key, body))

    @app.post(PREFIX + '/sop-tasks/close-node')
    async def close_node(request: Request, project_id: str):
        return await mutation(request, project_id, service.close_node)

    @app.post(PREFIX + '/sop-tasks/suggestions/accept')
    async def accept_suggestions(request: Request, project_id: str):
        return await mutation(request, project_id, service.accept_suggestions)

    @app.post(PREFIX + '/sop-tasks/{task_id}/suggestion')
    async def suggestion(request: Request, project_id: str, task_id: str):
        return await mutation(request, project_id, lambda ctx, body: service.decide_suggestion(ctx, task_id, body))

    if quote_view is None:
        return service

    def quotes(request):
        data, user = identity(request)
        state, amounts = quote_view(data, user)
        return data['wid'], state, amounts

    @app.get('/api/quotes')
    def quote_list(request: Request, stage: str = '', q: str = '', offset: int = 0, limit: int = 30):
        return respond(lambda: service.quote_list(*quotes(request), stage=stage, q=q, offset=offset, limit=limit))

    @app.get('/api/quotes/{quote_no}')
    def quote_detail(request: Request, quote_no: str):
        return respond(lambda: service.quote_detail(*quotes(request), quote_no))

    if workspace is None or persist_case is None:
        return service

    def actor(request, _):
        data, user = identity(request)
        return data['wid'], user

    @app.post('/api/quotes/preview')
    async def local_preview(request: Request):
        return await mutation(request, None, lambda who, body: service.local_preview(*who, workspace, body), actor)

    @app.post('/api/quotes')
    async def local_create(request: Request):
        return await mutation(request, None, lambda who, body: service.local_create(*who, persist_case, body, lambda: actor(request, None)), actor)

    @app.get('/api/quotes/requests/{request_id}')
    def local_receipt(request: Request, request_id: str):
        return respond(lambda: service.local_receipt(*actor(request, None), request_id))

    return service
