"""Authenticated freshness reads and permission-preserving refresh triggers."""
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class RefreshRequest(BaseModel):
    datasets: list[Literal['sources', 'roster', 'attendance']] = Field(min_length=1, max_length=3)
    wait: bool = False
    force: bool = False


def refresh(coordinator, wid, datasets, *, wait=False, force=False):
    """Share response semantics between the live and legacy manual endpoints."""
    previous = coordinator.status(wid)['datasets']
    if force and any(previous[d]['status'] == 'refreshing' for d in datasets):
        raise HTTPException(409, '資料正在重新讀取，請稍後再試')
    try:
        results = [coordinator.ensure(wid, d, wait=wait, force=force) for d in datasets]
    except Exception:
        return JSONResponse({'detail': 'Lark 資料暫時無法讀取',
                             'freshness': coordinator.status(wid)}, status_code=502)
    freshness = coordinator.status(wid)
    if any(r['status'] == 'already_running' for r in results):
        return JSONResponse({'detail': '資料正在重新讀取，請稍後再試',
                             'freshness': freshness}, status_code=409)
    if wait and any(r['status'] != 'fresh' for r in results):
        return JSONResponse({'detail': 'Lark 資料暫時無法讀取',
                             'freshness': freshness}, status_code=502)
    pending = (any(r['status'] != 'fresh' for r in results)
               or (not wait and (force or any(previous[d]['status'] != 'fresh' for d in datasets))))
    return JSONResponse({'freshness': freshness}, status_code=202 if pending else 200)


def register(app, identity, coordinator, *, authorize=None):
    @app.get('/api/live/status')
    def status(request: Request):
        data, user = identity(request)
        return JSONResponse({'freshness': coordinator.status(data['wid'])},
                            headers={'Cache-Control': 'no-store'})

    @app.post('/api/live/refresh')
    def trigger(body: RefreshRequest, request: Request):
        data, user = identity(request)
        wid = data['wid']
        if (data.get('mode') != 'lark' or wid.startswith(('demo-', 'test-'))
                or not coordinator.status(wid)['enabled']):
            raise HTTPException(403, '即時讀取僅限已啟用的公司正式工作區')
        datasets = list(dict.fromkeys(body.datasets))
        for dataset in datasets:
            if body.force or dataset == 'roster':
                if authorize is None:
                    raise HTTPException(403, '需要資料同步權限')
                authorize(wid, dataset, user)
        return refresh(coordinator, wid, datasets, wait=body.wait, force=body.force)
