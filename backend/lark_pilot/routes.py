"""Default-off GET route with the existing identity and source authorizer."""
from datetime import datetime, timezone
import math

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from ..live_read.config import LiveReadConfig
from ..production_access import roster_age_seconds
from .sample import PilotReader, empty_result

PILOT_ROSTER_MAX_AGE_SECONDS = 60


def register(app, *, identity, authorize, cfg):
    @app.get('/api/lark-pilot/shadow')
    def shadow(request: Request):
        headers = {'Cache-Control': 'no-store'}
        if str(cfg.get('LARK_PILOT_READONLY_ENABLED', 'false')).lower() != 'true':
            return JSONResponse({**empty_result(), 'code': 'pilot_disabled', 'detail': '唯讀試行尚未啟用'}, status_code=404, headers=headers)
        try:
            data, user = identity(request)
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail, 'code': getattr(exc, 'code', 'pilot_read_failed')},
                                status_code=exc.status_code, headers={**(exc.headers or {}), **headers})
        wid = data['wid']
        if data.get('mode') != 'lark' or wid.startswith(('demo-', 'test-')):
            return JSONResponse({**empty_result(), 'code': 'pilot_not_company_workspace', 'detail': '此工作區未啟用唯讀試行'}, status_code=404, headers=headers)
        try:
            # Config parsing otherwise substitutes defaults for invalid TTL input.
            raw_ttl = float(cfg.get('LARK_LIVE_READ_ROSTER_TTL_SECONDS', 60))
            if not math.isfinite(raw_ttl):
                raise ValueError('Invalid roster TTL')
            ceiling = min(PILOT_ROSTER_MAX_AGE_SECONDS,
                          LiveReadConfig.from_env(cfg).roster_ttl_seconds)
        except (TypeError, ValueError, OverflowError):
            ceiling = None
        age = roster_age_seconds(user, datetime.now(timezone.utc))
        if ceiling is None or age is None or age > ceiling:
            body = {'detail': '公司名冊核實已逾唯讀試行期限，請先重新載入工作區',
                    'code': 'pilot_config_invalid' if ceiling is None else
                            'pilot_roster_missing' if age is None else 'pilot_roster_stale'}
            if ceiling is not None and age is not None:
                body['ceiling_seconds'] = int(ceiling)
            return JSONResponse(body, status_code=403, headers=headers)
        try:
            authorize(wid, 'sources', user)
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail,
                                 'code': 'source_authorization_denied' if exc.status_code == 403 else 'pilot_read_failed'},
                                status_code=exc.status_code, headers={**(exc.headers or {}), **headers})
        with PilotReader(cfg) as reader:
            return JSONResponse(reader.read(), headers=headers)
