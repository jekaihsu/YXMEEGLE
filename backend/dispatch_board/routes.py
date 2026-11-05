"""Authenticated, feature-gated dispatch reads."""
from datetime import date, datetime, timedelta
from contextlib import asynccontextmanager
import re

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from ..data_state import data_state
from ..node_assignment.cache import permission_failure
from .config import DispatchBoardConfig
from .domain import TZ, Window
from .lark_table import source_snapshot
from .service import DispatchBoardService

URL = '/api/v2/dispatch/board'


def parameters(query, *, today=None):
    if set(query) - {'from', 'to', 'group'}:
        raise ValueError('unsupported query parameter')
    today = today or datetime.now(TZ).date()

    def parse(key, default):
        value = query.get(key, default.isoformat())
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError(f'{key} must be YYYY-MM-DD')
        return date.fromisoformat(value)

    start = parse('from', today)
    end = parse('to', start + timedelta(days=6))
    group = query.get('group') or None
    if group and (len(group) > 100 or any(ord(ch) < 32 for ch in group)):
        raise ValueError('invalid group')
    return Window(start, end, group)


def register(app, *, identity, allow, cfg, service=None):
    if not DispatchBoardConfig.from_env(cfg).enabled:
        return None
    service = service or DispatchBoardService(cfg)
    lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def dispatch_lifespan(app):
        try:
            async with lifespan(app) as state:
                yield state
        finally:
            service.close()

    app.router.lifespan_context = dispatch_lifespan

    @app.get(URL)
    def board(request: Request):
        try:
            data, user = identity(request)
            if (data.get('mode') != 'lark' or str(data.get('wid', '')).startswith(('test-', 'demo-'))
                    or not allow(data, user)):
                raise HTTPException(403, '需要 PM 或主管權限及公司正式工作區')
            try:
                window = parameters(request.query_params)
            except (ValueError, OverflowError):
                raise HTTPException(422, '日期區間須為 YYYY-MM-DD，起日不晚於迄日，最多 62 天') from None
            with source_snapshot():
                status, body = service.board(data['wid'], window)
        except HTTPException as exc:
            status = exc.status_code
            body = {'detail': str(exc.detail)}
            if status == 403:
                body['source'] = {'quality': data_state('forbidden')}
        except Exception as exc:
            denied = permission_failure(exc)
            status = 403 if denied else 503
            body = {'source': {'quality': {'states': ['forbidden' if denied else 'read_failed'],
                                          'reason': 'source_forbidden' if denied else 'schedule_read_failed'}}}
        return JSONResponse(body, status_code=status, headers={'Cache-Control': 'no-store'})

    return service
