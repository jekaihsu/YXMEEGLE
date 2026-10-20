import json
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.concurrency import run_in_threadpool

from .domain import Failure, require
from .service import Context, Service, authorize

PREFIX = '/api/projects/{project_id}'
MAX_BODY = 64 * 1024


def register(app, *, identity, load_case, sessions, cfg):
    service = Service(sessions, writes_enabled=lambda: str(cfg.get('SOP_TASK_WRITES_ENABLED', 'false')).lower() == 'true')

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
            body, status = {'code': exc.code, 'detail': exc.code}, exc.status
        except HTTPException as exc:
            code = {401: 'session_expired', 403: 'sop_import_forbidden', 404: 'case_not_found'}.get(exc.status_code, 'invalid_request')
            body, status = {'code': code, 'detail': code}, exc.status_code
        except (IntegrityError, OperationalError):
            body, status = {'code': 'import_unavailable', 'detail': 'import_unavailable'}, 503
        return JSONResponse(body, status_code=status, headers={'Cache-Control': 'no-store'})

    async def mutation(request, project_id, run):
        try:
            ctx = await run_in_threadpool(context, request, project_id)
        except (Failure, HTTPException) as exc:
            def denied():
                raise exc
            return respond(denied)
        raw = await request.body()

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

    return service
