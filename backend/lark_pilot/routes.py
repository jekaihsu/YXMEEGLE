"""Default-off GET route with the existing identity and source authorizer."""
from fastapi import Request
from fastapi.responses import JSONResponse

from .sample import PilotReader, empty_result


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
        authorize(wid, 'sources', user)
        with PilotReader(cfg) as reader:
            return JSONResponse(reader.read(), headers=headers)
