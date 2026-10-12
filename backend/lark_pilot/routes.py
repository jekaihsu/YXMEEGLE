"""Default-off GET route with the existing identity and source authorizer."""
from datetime import datetime, timezone
import math

from fastapi import Request
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
            return JSONResponse(empty_result(), status_code=404, headers=headers)
        data, user = identity(request)
        wid = data['wid']
        if data.get('mode') != 'lark' or wid.startswith(('demo-', 'test-')):
            return JSONResponse(empty_result(), status_code=404, headers=headers)
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
            return JSONResponse({'detail': '公司名冊核實已逾唯讀試行期限，請先重新載入工作區'},
                                status_code=403, headers=headers)
        authorize(wid, 'sources', user)
        with PilotReader(cfg) as reader:
            return JSONResponse(reader.read(), headers=headers)
