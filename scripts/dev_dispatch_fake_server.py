"""Local end-to-end dispatch server: the real app, a company-like workspace and an in-memory V4 Bitable.

Never deployed: scripts/deploy_prepare.py ships an explicit list of scripts and this is not on it. No request
leaves the process. Dispatch board and publish reads and writes go to the FakeLark of
backend/test_dispatch_publish_fake.py; every other Lark read is denied (LARK_LIVE_READ_TRANSPORT=deny).

Usage:
  .venv/bin/python scripts/dev_dispatch_fake_server.py [--port 8000] [--data DIR]
  cd frontend && npm run dev          (Vite proxies /api to localhost:8000)
  open http://localhost:5173/api/dev/login?as=pm

Dev-only endpoints, registered here and nowhere else:
  GET    /api/dev/login?as=<alias>&next=/   sign in as pm, lead, manager, pmfinal or staff
  GET    /api/dev/users                     the aliases and their seats
  GET    /api/dev/faults                    the armed fault, if any
  POST   /api/dev/faults {"fault": ...}     arm one: timeout_after_success, error_before_landing, mismatch
  DELETE /api/dev/faults                    disarm
"""
import argparse
import os
import secrets
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WID = 'lark-company'
# alias -> (open_id, role). Names and roster rows come from the fake roster below.
USERS = {'pm': ('ou_pm', 'pm'), 'lead': ('ou_lead', 'member'), 'manager': ('ou_mgr', 'manager'),
         'pmfinal': ('ou_pmf', 'pm'), 'staff': ('ou_jia', 'member')}
FAULTS = ('timeout_after_success', 'error_before_landing', 'mismatch')


def settings(data):
    return {'DATABASE_URL': f'sqlite:///{data}/dispatch-dev.db', 'UPLOAD_DIR': str(data / 'uploads'),
            'SESSION_SECRET': secrets.token_hex(32), 'APP_ENV': 'development', 'DEMO_MODE': 'false',
            'LARK_LIVE_READ_TRANSPORT': 'deny', 'DISPATCH_BOARD_ENABLED': 'true', 'DISPATCH_WRITE_ENABLED': 'true',
            'LARK_WORKER_IDENTITY': 'application', 'LARK_APP_ID': 'cli_dev_fake', 'LARK_APP_SECRET': 'synthetic',
            'LARK_WORKER_ORGANIZATION': 'company', 'LARK_ALLOWED_TENANTS': 'company', 'DISPATCH_SEAT_GROUP_LEADER': '', 'DISPATCH_SEAT_MANAGER_REVIEW': '',
            'DISPATCH_SEAT_PM_FINAL': ''}


def seed_lark(fake, today):
    from backend.dispatch_board.config import SOURCES
    from backend.dispatch_board.domain import TZ
    from backend.test_dispatch_publish_fake import PEOPLE, SCHEDULE, TASKS

    def at(days, hour=0):
        return int(datetime.combine(today + timedelta(days=days), datetime.min.time(), TZ).timestamp() * 1000
                   + hour * 3_600_000)
    for rid, name, ident, active, rank, groups in [
            ('recP1', '甲', 'ou_jia', True, '組員', ['外業']), ('recP2', '乙', 'ou_yi', True, '組員', ['外業']),
            ('recP3', '丙', 'ou_bing', True, '組員', ['外業']), ('recP4', '離職', 'ou_gone', False, '組員', ['外業']),
            ('recP5', '無帳號', None, True, '組員', ['外業']), ('recP6', '組長', 'ou_lead', True, '組長', ['外業']),
            ('recP7', '經理', 'ou_mgr', True, '經理', ['外業']), ('recP8', '專案PM', 'ou_pmf', True, '組員', ['PM']),
            ('recP9', '派工PM', 'ou_pm', True, '組員', ['PM'])]:
        fake.add(PEOPLE, rid, {'姓名': name, '在職': active, 'Lark帳號': [{'id': ident}] if ident else None,
                               '職級': rank, '所屬組別': groups})
    instruments, vehicles = SOURCES['instruments'].table_id, SOURCES['vehicles'].table_id
    fake.add(instruments, 'recI1', {'儀器名稱': 'GNSS-01', '啟用': True, '狀態': '正常'})
    fake.add(instruments, 'recI2', {'儀器名稱': 'GNSS-02', '啟用': True, '狀態': '送修-損壞'})
    fake.add(instruments, 'recI3', {'儀器名稱': '全站儀-01', '啟用': True, '狀態': '正常'})
    fake.add(vehicles, 'recV1', {'車牌': 'SYN-001', '啟用': True})
    fake.add(vehicles, 'recV2', {'車牌': 'SYN-002', '啟用': True})
    fake.add(SOURCES['cases'].table_id, 'recCase1', {'工程確認單編號': 'SYN-001', '工程名稱': '合成示範案'})
    fake.add(SOURCES['cases'].table_id, 'recCase2', {'工程確認單編號': 'SYN-002', '工程名稱': '合成第二案'})
    fake.add(SOURCES['nodes'].table_id, 'recN1', {'節點': '外業', '確認單編號': 'SYN-001'})
    fake.add(SCHEDULE, 'recS1', {'條類型': '出工', '組別': '水深A組', '業別': '外業', '人員': ['recP1'],
                                 '開始日期': at(1, 8), '結束日期': at(1, 12), '工作內容': 'A 區外業', '案件': ['recCase1']})
    fake.add(SCHEDULE, 'recS2', {'條類型': '出工', '人員': ['recP1'], '開始日期': at(2), '結束日期': at(2)})
    fake.add(SCHEDULE, 'recS3', {'條類型': '出工', '儀器': ['recI3'], '開始日期': at(1), '結束日期': at(1),
                                 '工作內容': '全站儀借用（僅日期）'})
    fake.add(SCHEDULE, 'recS4', {'條類型': '出工', '組別': '水深A組', '業別': '外業', '人員': ['recP2'],
                                 '開始日期': at(3, 13), '結束日期': at(3, 17), '工作內容': 'C 區外業'})
    fake.add(TASKS, 'recLegacy', {'標題': '外業：待指派', '狀態': '待處理', '節點指派': ['recN1'], '指派人': [{'id': 'ou_pm'}],
                                  '部門': '外業', '截止日': at(7), '工程確認單': ['recCase1'], '專案編號': 'SYN-001'})
    fake.add(TASKS, 'recDone', {'標題': 'B 區外業', '內容': 'B 區水深測量', '負責人': [{'id': 'ou_bing'}],
                                '指派人': [{'id': 'ou_pm'}], '部門': '外業', '專案編號': 'SYN-001', '工程確認單': ['recCase1'],
                                '任務階段': '正式', '任務種類': '執行', '預定開始': at(2, 8), '預定結束': at(2, 12),
                                '預估人時': 8.0, '組員': [{'id': 'ou_yi'}], '使用儀器': ['recI1'], '排程狀態': '已確認',
                                '排程版本': 1, '命令編號': str(uuid.uuid4()), '讀回時間': at(0, 9), '狀態': '待處理'})
    fake.add(TASKS, 'recNext', {'標題': '控制測量：待排', '狀態': '待處理', '指派人': [{'id': 'ou_pm'}], '部門': '外業',
                                '專案編號': 'SYN-002', '工程確認單': ['recCase2'], '任務種類': '執行'})


class Faults:
    """One-shot faults on 任務 traffic, applied in front of the fake Bitable."""

    def __init__(self, fake, tasks_table):
        self.fake, self.tasks = fake, tasks_table
        self.lock = threading.Lock()
        self.armed, self.after_write = None, False

    def arm(self, fault):
        with self.lock:
            self.armed = fault

    def _take(self, *names):
        with self.lock:
            if self.armed in names:
                fault, self.armed = self.armed, None
                return fault
        return None

    def __call__(self, request):
        import httpx
        parts = request.url.path.split('/')
        task = len(parts) > 7 and parts[7] == self.tasks
        write = task and ((request.method == 'POST' and parts[8:] == ['records'])
                          or (request.method == 'PUT' and len(parts) == 10))
        single = task and request.method == 'GET' and len(parts) == 10
        if write:
            fault = self._take('timeout_after_success', 'error_before_landing')
            if fault == 'error_before_landing':
                return httpx.Response(200, json={'code': 1254001, 'msg': 'dev fault: WrongRequestBody'})
            response = self.fake(request)
            if fault == 'timeout_after_success':
                raise httpx.ReadTimeout('dev fault: timeout after the write landed', request=request)
            self.after_write = True
            return response
        if single:
            readback, self.after_write = self.after_write, False
            if readback and self._take('mismatch'):
                body = self.fake(request).json()
                body['data']['record']['fields']['預定結束'] += 3_600_000
                return httpx.Response(200, json=body)
        return self.fake(request)


def seed_workspace(app):
    from backend import storage
    from backend.app import BusinessRow, WorkspaceRow
    from backend.policy import upgrade
    from backend.seed import seed
    from backend.test_dispatch_publish_fake import NAMES
    state = upgrade(seed())
    state.update(environment='production', projects=[])
    state['settings']['external_enabled'] = True
    template = state['users'][0]
    state['users'] = [{**template, 'id': ident, 'name': NAMES[ident], 'role': role, 'department': '外業',
                       'avatar': NAMES[ident][:1], 'capabilities': []} for ident, role in USERS.values()]
    with app.state.sessions.begin() as db:
        if db.get(WorkspaceRow, WID) is None:
            row = WorkspaceRow(id=WID, version=state['version'], data={})
            db.add(row)
            db.flush()
            row.data = storage.save(db, BusinessRow, WID, state)


def dev_routes(app, faults):
    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse, RedirectResponse
    from backend.app import AuthRow

    def login(request: Request):
        alias, target = request.query_params.get('as', 'pm'), request.query_params.get('next', '/')
        if alias not in USERS:
            raise HTTPException(404, f'unknown dev user; choose one of {sorted(USERS)}')
        if not target.startswith('/') or target.startswith('//'):
            target = '/'
        sid = 'dev-' + secrets.token_hex(12)
        with app.state.sessions.begin() as db:
            db.add(AuthRow(id=sid, data={'wid': WID, 'expires': time.time() + 8 * 3600}))
        response = RedirectResponse(target, status_code=303)
        response.set_cookie('meegle_session', app.state.signer.dumps(
            {'mode': 'lark', 'sid': sid, 'wid': WID, 'uid': USERS[alias][0]}), httponly=True, samesite='lax', path='/')
        return response

    def users():
        return {'users': [{'alias': alias, 'open_id': ident, 'role': role} for alias, (ident, role) in USERS.items()],
                'seats': {'group_leader_confirmed': '組長 of the proposal department (lead)',
                          'manager_review': '經理 of the department (manager)',
                          'pm_final': 'session users with role pm (pm, pmfinal)'}}

    async def set_fault(request: Request):
        if request.method == 'DELETE':
            faults.arm(None)
        elif request.method == 'POST':
            fault = (await request.json()).get('fault')
            if fault not in FAULTS:
                return JSONResponse({'detail': f'fault must be one of {list(FAULTS)}'}, status_code=422)
            faults.arm(fault)
        return {'armed': faults.armed, 'available': list(FAULTS)}

    app.add_api_route('/api/dev/login', login, methods=['GET'])
    app.add_api_route('/api/dev/users', users, methods=['GET'])
    app.add_api_route('/api/dev/faults', set_fault, methods=['GET', 'POST', 'DELETE'])
    # The SPA fallback (GET /{path:path}) is registered first when frontend/dist exists; dev routes go in front.
    added = app.router.routes[-3:]
    del app.router.routes[-3:]
    app.router.routes[:0] = added


def build(data):
    """The real app on a fresh synthetic database, wired to the fake Bitable. Returns (app, fake, faults)."""
    cfg = settings(Path(data))
    os.environ.update(cfg)
    import httpx
    from backend.app import create_app
    from backend.dispatch_board.domain import TZ
    from backend.test_dispatch_publish_fake import TASKS, FakeLark
    fake = FakeLark()
    seed_lark(fake, datetime.now(TZ).date())
    faults = Faults(fake, TASKS)
    app = create_app(cfg, dispatch_transport=httpx.MockTransport(faults))
    seed_workspace(app)
    dev_routes(app, faults)
    return app, fake, faults


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--data', help='database directory; a fresh temporary one by default')
    args = parser.parse_args()
    data = Path(args.data or tempfile.mkdtemp(prefix='dispatch-dev-'))
    data.mkdir(parents=True, exist_ok=True)
    app, _, _ = build(data)
    import uvicorn
    print(f'dispatch dev server on http://127.0.0.1:{args.port} (data {data}); '
          f'sign in at /api/dev/login?as=pm|lead|manager|pmfinal|staff')
    uvicorn.run(app, host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
