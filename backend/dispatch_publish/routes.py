"""HTTP routes. Write routes exist only with DISPATCH_WRITE_ENABLED; the work queue also with the board flag."""
import json
import re

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..dispatch_board.routes import parameters
from .config import DispatchPublishConfig
from .domain import CommandResult, Refusal
from .service import Context, DispatchPublishService

MAX_BODY = 16 * 1024
ID = re.compile(r'[A-Za-z0-9_-]{1,80}')
COMMIT_STATUS = {CommandResult.COMMITTED: 200, CommandResult.FAILED: 502}


def register(app, *, identity, allow, cfg, sessions, audit_model, workspace, transport=None, client_options=None,
             clock=None, reader=None):
    """workspace(wid) -> {'settings': ..., 'environment': ...}; allow(data, user) -> may dispatch."""
    config = DispatchPublishConfig.from_env(cfg)
    if not (config.enabled or config.board_enabled):
        return None
    options = {'transport': transport, 'client_options': client_options, 'reader': reader}
    if clock is not None:
        options['clock'] = clock
    service = DispatchPublishService(cfg, sessions=sessions, audit_model=audit_model, **options)

    def respond(status, body, headers=None):
        return JSONResponse(body, status_code=status, headers={'Cache-Control': 'no-store', **(headers or {})})

    def context(request, need):
        data, user = identity(request)
        if data.get('mode') != 'lark' or str(data.get('wid', '')).startswith(('test-', 'demo-')):
            raise Refusal('forbidden', '派工僅限公司正式工作區')
        dispatcher = bool(allow(data, user))
        permitted = {'dispatch': dispatcher, 'view': dispatcher or bool(config.holds(user['id'])),
                     'manager': user.get('role') == 'manager'}[need]
        if not permitted or not user.get('active', True):
            raise Refusal('forbidden', '需要 PM、主管或核定席次權限')
        return Context(data['wid'], user, workspace(data['wid']), dispatcher)

    async def body_of(request):
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise Refusal('payload_too_large', '請求內容過大')
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            raise Refusal('invalid', '請求內容不是有效的 JSON') from None

    async def guarded(request, need, run, with_body=False):
        try:
            body = await body_of(request) if with_body else None
            ctx = await run_in_threadpool(context, request, need)
            return await run_in_threadpool(run, ctx, body)
        except Refusal as exc:
            return respond(exc.status, exc.body())
        except HTTPException as exc:
            return respond(exc.status_code, {'detail': str(exc.detail)})

    def command_response(ctx, command, replayed=False):
        state = CommandResult(command['state'])
        return respond(COMMIT_STATUS.get(state, 202), service.present_command(ctx, command),
                       {'Idempotent-Replayed': 'true'} if replayed else None)

    def checked(value):
        if not ID.fullmatch(value):
            raise Refusal('not_found', '找不到這筆資料')
        return value

    @app.get('/api/v2/dispatch/work')
    async def work(request: Request):
        def run(ctx, _):
            query = dict(request.query_params)
            scope = query.pop('scope', 'all')
            if scope not in ('mine', 'group', 'all'):
                raise Refusal('invalid', 'scope 須為 mine、group 或 all')
            window = None
            if 'from' in query or 'to' in query:
                try:
                    parsed = parameters({k: v for k, v in query.items() if k in ('from', 'to', 'group')})
                except (ValueError, OverflowError):
                    raise Refusal('invalid', '日期區間須為 YYYY-MM-DD，起日不晚於迄日，最多 62 天') from None
                window = (parsed.start, parsed.end)
            if set(query) - {'from', 'to', 'group'}:
                raise Refusal('invalid', '不支援的查詢參數')
            group = query.get('group') or None
            if group is not None and (len(group) > 100 or any(ord(c) < 32 for c in group)):
                raise Refusal('invalid', 'group 格式不符')
            if scope == 'group' and group is None:
                raise Refusal('invalid', 'scope=group 需要 group')
            status, body = service.work(ctx, window, group, scope)
            return respond(status, body)
        return await guarded(request, 'view', run)

    if not config.enabled:
        return service

    @app.post('/api/v2/dispatch/previews')
    async def create_preview(request: Request):
        return await guarded(request, 'dispatch', lambda ctx, body: respond(200, service.preview(ctx, body)), True)

    @app.get('/api/v2/dispatch/previews/{preview_id}')
    async def read_preview(request: Request, preview_id: str):
        return await guarded(request, 'view', lambda ctx, _: respond(200, service.get_preview(ctx, checked(preview_id))))

    @app.post('/api/v2/dispatch/previews/{preview_id}/decisions')
    async def decide(request: Request, preview_id: str):
        return await guarded(request, 'view',
                             lambda ctx, body: respond(200, service.decide(ctx, checked(preview_id), body)), True)

    @app.post('/api/v2/dispatch/commits')
    async def commit(request: Request):
        def run(ctx, body):
            existing = service.store.command(ctx.wid, body.get('command_id')) if isinstance(body, dict) and isinstance(
                body.get('command_id'), str) else None
            return command_response(ctx, service.commit(ctx, body), replayed=existing is not None)
        return await guarded(request, 'dispatch', run, True)

    @app.get('/api/v2/commands/{command_id}')
    async def read_command(request: Request, command_id: str):
        return await guarded(request, 'view', lambda ctx, _: respond(
            200, service.present_command(ctx, service.get_command(ctx, checked(command_id)))))

    @app.post('/api/v2/commands/{command_id}/reconcile')
    async def reconcile(request: Request, command_id: str):
        return await guarded(request, 'manager',
                             lambda ctx, _: command_response(ctx, service.reconcile(ctx, checked(command_id))))

    @app.get('/api/v2/dispatch/drafts')
    async def list_drafts(request: Request):
        return await guarded(request, 'dispatch',
                             lambda ctx, _: respond(200, {'drafts': service.store.drafts(ctx.wid, ctx.actor)}))

    @app.get('/api/v2/dispatch/drafts/{draft_id}')
    async def read_draft(request: Request, draft_id: str):
        return await guarded(request, 'dispatch', lambda ctx, _: respond(200, service.get_draft(ctx, checked(draft_id))))

    @app.put('/api/v2/dispatch/drafts/{draft_id}')
    async def save_draft(request: Request, draft_id: str):
        return await guarded(request, 'dispatch',
                             lambda ctx, body: respond(200, service.save_draft(ctx, draft_id, body)), True)

    @app.delete('/api/v2/dispatch/drafts/{draft_id}')
    async def delete_draft(request: Request, draft_id: str):
        def run(ctx, _):
            service.store.delete_draft(ctx.wid, ctx.actor, checked(draft_id))
            return respond(200, {'deleted': draft_id})
        return await guarded(request, 'dispatch', run)

    @app.get('/api/v2/dispatch/tasks/{task_id}')
    async def task_form(request: Request, task_id: str):
        return await guarded(request, 'dispatch', lambda ctx, _: respond(200, service.task_form(ctx, checked(task_id))))

    @app.get('/api/v2/dispatch/options')
    async def options(request: Request):
        return await guarded(request, 'dispatch', lambda ctx, _: respond(200, service.options(ctx)))

    return service
