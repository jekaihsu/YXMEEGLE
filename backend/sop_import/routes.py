import json
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.concurrency import run_in_threadpool

from ..production_access import hr_view_allowed
from .domain import Failure, require
from .service import Context, Service, authorize

PREFIX = '/api/projects/{project_id}'
MAX_BODY = 64 * 1024


def register(app, *, identity, load_case, sessions, cfg, quote_view=None, workspace=None, persist_case=None):
    flag = lambda name: lambda: str(cfg.get(name, 'false')).lower() == 'true'
    service = Service(sessions, writes_enabled=flag('SOP_TASK_WRITES_ENABLED'),
                      local_cases_enabled=flag('LOCAL_CASE_CREATION_ENABLED'))

    def context(request, project_id):
        data, user = identity(request)
        state, project = load_case(data, user, project_id)
        ctx = Context(data['wid'], user, state, project, lambda: context(request, project_id))
        authorize(ctx)
        return ctx

    def respond(run):
        try:
            body, status = run(), 200
        except Failure as exc:
            body, status = {'code': exc.code, 'detail': exc.code, **exc.context}, exc.status
        except HTTPException as exc:
            code = {401: 'session_expired', 403: 'sop_import_forbidden', 404: 'case_not_found',
                    409: 'workspace_conflict'}.get(exc.status_code, 'invalid_request')
            body, status = {'code': code, 'detail': code}, exc.status_code
        except (IntegrityError, OperationalError):
            body, status = {'code': 'import_unavailable', 'detail': 'import_unavailable'}, 503
        return JSONResponse(body, status_code=status, headers={'Cache-Control': 'no-store'})

    async def mutation(request, project_id, run, resolve=None):
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
            return run(ctx, body)
        return await run_in_threadpool(respond, execute)

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

    @app.get(PREFIX + '/sop-tasks')
    def tasks(request: Request, project_id: str, node_key: str = None):
        return respond(lambda: service.overview(context(request, project_id), node_key))

    @app.post(PREFIX + '/sop-import/preview')
    async def preview(request: Request, project_id: str):
        return await mutation(request, project_id, service.preview)

    @app.post(PREFIX + '/sop-import/apply')
    async def apply(request: Request, project_id: str):
        return await mutation(request, project_id, service.apply)

    @app.get(PREFIX + '/sop-assignees')
    def assignees(request: Request, project_id: str):
        return respond(lambda: service.assignees(context(request, project_id), lambda user: hr_view_allowed(user, cfg)))

    @app.get(PREFIX + '/sop-import/runs/{request_id}')
    def receipt(request: Request, project_id: str, request_id: str):
        return respond(lambda: service.receipt(context(request, project_id), request_id))

    @app.post(PREFIX + '/sop-tasks')
    async def manual(request: Request, project_id: str):
        return await mutation(request, project_id, service.manual)

    @app.patch(PREFIX + '/sop-tasks/{task_id}')
    async def patch(request: Request, project_id: str, task_id: str):
        return await mutation(request, project_id, lambda ctx, body: service.mutate(ctx, task_id, body))

    @app.post(PREFIX + '/sop-tasks/{task_id}/transition')
    async def transition(request: Request, project_id: str, task_id: str):
        return await mutation(request, project_id, lambda ctx, body: service.mutate(ctx, task_id, body, transition=True))

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
