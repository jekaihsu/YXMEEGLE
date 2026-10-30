"""Repeatable cockpit HTTP measurements with fictional data and mock Lark I/O."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import perf_counter, sleep, time

import httpx
from fastapi.testclient import TestClient

from . import storage
from .app import create_app
from .attendance_schedule import AttendanceScheduleReader
from .live_read.client import LiveLarkClient
from .live_read.rate_limit import TokenBucket
from .live_read.token_cache import TenantTokenCache
from .models import AuthRow, BusinessRow, PersonRow, WorkspaceRow
from .perf_fixture import build_scaled_workspace
from .sources import FIELDS, KNOWN_TABLES, fetch_sources

TABLE_COUNTS = {'tblmSQrcCs9vPQZx':106, 'tblobs4qPy2w9MZ6':573,
                'tblwQPYk3c9RvCU7':701, 'tbl8wRYCUCvbSoJG':213,
                'tblKwSDRg6WaGHYr':201, 'tbl5zPLS0ExWNEty':187,
                'tblrCo8KeZiuJUNh':348, 'tblENZvYAya93Twa':423,
                'tblvV4X1kNVQisVj':106}


class MockLark:
    def __init__(self, latency):
        self.latency, self.calls, self.lock = latency, [], Lock()

    def handle(self, request):
        began = perf_counter()
        sleep(self.latency)
        path = request.url.path
        if path.endswith('/tenant_access_token/internal'):
            body = {'code':0, 'tenant_access_token':'fictional', 'expire':7200}
        elif '/bitable/' in path:
            table = path.split('/tables/')[1].split('/')[0]
            kind = next(tables[table] for tables in KNOWN_TABLES.values() if table in tables)
            if path.endswith('/fields'):
                items = [{'field_name':field, 'type':1, 'field_id':f'f{i}'} for i, field in enumerate(FIELDS[kind])]
                body = {'code':0, 'data':{'items':items, 'has_more':False}}
            else:
                offset = int(request.url.params.get('page_token', '0'))
                size = int(request.url.params['page_size'])
                count = TABLE_COUNTS[table]
                items = [{'record_id':f'rec{table}{i}', 'fields':{FIELDS[kind][0]:f'F{i}'}} for i in range(offset,min(offset+size,count))]
                body = {'code':0, 'data':{'items':items, 'has_more':offset+size<count, 'page_token':str(offset+size)}}
        elif path.endswith('/user_daily_shifts/query'):
            query = json.loads(request.content)
            start = datetime.strptime(str(query['check_date_from']), '%Y%m%d').date()
            end = datetime.strptime(str(query['check_date_to']), '%Y%m%d').date()
            rows = [{'user_id':uid, 'month':(start+timedelta(days=i)).strftime('%Y%m'),
                     'day_no':(start+timedelta(days=i)).day, 'shift_id':f'shift{i}'}
                    for uid in query['user_ids'] for i in range((end-start).days+1)]
            body = {'code':0, 'data':{'user_daily_shifts':rows}}
        elif '/attendance/v1/shifts/' in path:
            body = {'code':0, 'data':{'shift_id':path.rsplit('/',1)[1], 'is_flexible':False,
                                     'punch_time_rule':[{'on_time':'09:00', 'off_time':'17:30'}]}}
        else:
            raise AssertionError(path)
        with self.lock:
            self.calls.append({'path':path, 'duration_ms':round((perf_counter()-began)*1000,3)})
        return httpx.Response(200,json=body)


def canonical(result):
    result = dict(result)
    result.pop('checked_at', None)
    return hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def measure(latency, projects, profile=None, legacy=False):
    with TemporaryDirectory() as directory:
        root = Path(directory)
        cfg = {'DATABASE_URL':f'sqlite:///{root}/bench.db', 'UPLOAD_DIR':str(root/'u'),
               'SESSION_SECRET':'fictional-performance-secret'*3, 'APP_ENV':'development',
               'DEMO_MODE':'false', 'LARK_APP_ID':'bench', 'LARK_APP_SECRET':'fictional',
               'LARK_ALLOWED_TENANTS':'bench', 'LARK_WORKER_ORGANIZATION':'bench',
               'LARK_WORKER_IDENTITY':'application', 'LARK_LIVE_READ_ENABLED':'true',
               'WORKSPACE_SHELL_ENABLED':'true', 'INDEX_TABLES_ENABLED':'true'}
        tables = [dict(base_token=base,table_id=table,kind=kind) for base,known in KNOWN_TABLES.items() for table,kind in known.items()]
        cfg['LARK_SOURCE_TABLES_JSON'] = json.dumps(tables)
        app = create_app(cfg)
        if legacy:
            endpoint = next(route.endpoint for route in app.routes if route.path=='/api/company-dashboard')
            cell = dict(zip(endpoint.__code__.co_freevars,endpoint.__closure__))['public_ws']
            original_workspace = cell.cell_contents
            def legacy_workspace(*args,**kwargs):
                kwargs['task_details'] = True
                return original_workspace(*args,**kwargs)
            cell.cell_contents = legacy_workspace
        state = build_scaled_workspace(projects)
        state['environment'] = 'production'
        state['source_status'] = {'status':'ready','last_sync':'2026-10-14T12:00:00+08:00'}
        person = state['users'][0]
        person.update(identity_app_id='bench',directory_status='employed',directory_last_seen_at=datetime.now(timezone.utc).isoformat(),directory_source={'app_id':'bench','record_id':'fictional'})
        with app.state.sessions.begin() as db:
            row = WorkspaceRow(id='lark-bench',version=1,data={})
            db.add(row)
            db.flush()
            row.data = storage.save(db,BusinessRow,row.id,state)
            db.add(PersonRow(organization_id=row.id,person_id=person['id'],data=person))
            db.add(AuthRow(id='bench-session',data={'wid':row.id,'expires':time()+3600,'access_token':'fictional'}))
        mock = MockLark(latency)
        bucket, tokens = TokenBucket(5), TenantTokenCache()
        def reader():
            return LiveLarkClient(cfg,transport=httpx.MockTransport(mock.handle),bucket=bucket,token_cache=tokens)
        def sources(wid):
            with reader() as client:
                result = fetch_sources('',cfg,client)
                assert result['status']=='ready'
                assert len(result['records'])==sum(TABLE_COUNTS.values())
                return {'fingerprint':'sources','lark':client.metrics}
        def attendance(wid):
            people = [{'id':f'u{i}', 'attendance_identity':{'employee_id':f'e{i}',
                       'app_id':'bench','tenant':'bench','source':'oauth_user_info',
                       'verified_at':'2026-10-14T00:00:00Z','open_id':f'u{i}',
                       'employee_type':'employee_id'}} for i in range(67)]
            with reader() as client:
                from .lark_adapter import LarkAdapter
                adapter = LarkAdapter('',client=client)
                result = AttendanceScheduleReader(adapter,'bench','bench',lambda:None).fetch(people,'2026-10-14','2026-10-27')
                assert len(result['rows'])==938
                return {'fingerprint':'attendance','lark':client.metrics}
        app.state.live_read.refreshers = {'sources':sources,'attendance':attendance,'roster':lambda wid:{'fingerprint':'roster'}}
        client = TestClient(app)
        client.cookies.set('meegle_session',app.state.signer.dumps({'mode':'lark','uid':person['id'],'wid':'lark-bench','sid':'bench-session'}))
        samples = []
        try:
            for temperature in ('cold','warm'):
                if profile and temperature=='warm':
                    import cProfile
                    endpoint = next(route.endpoint for route in app.routes if route.path=='/api/company-dashboard')
                    cell = dict(zip(endpoint.__code__.co_freevars,endpoint.__closure__))['public_ws']
                    public_workspace = cell.cell_contents
                    profiler = cProfile.Profile()
                    def profiled_workspace(*args,**kwargs):
                        return profiler.runcall(public_workspace,*args,**kwargs)
                    cell.cell_contents = profiled_workspace
                start = perf_counter()
                endpoints = []
                for path in ('/api/session','/api/workspace?scope=shell','/api/company-dashboard?limit=40'):
                    began = perf_counter()
                    response = client.get(path)
                    assert response.status_code==200,(path,response.text[:100])
                    endpoints.append({'path':path,'wall_ms':round((perf_counter()-began)*1000,3),'bytes':len(response.content)})
                result = response.json()
                samples.append({'temperature':temperature,'wall_ms':round((perf_counter()-start)*1000,3),
                                'endpoints':endpoints,'cases':result['totals']['cases'],
                                'tasks':result['totals']['tasks_total'],'digest':canonical(result),
                                'completed_lark_calls':len(mock.calls)})
                app.state.live_read.close()
            status = app.state.live_read.status('lark-bench')
            assert status['datasets']['sources']['status']=='fresh',status
            assert status['datasets']['attendance']['status']=='fresh',status
            return {'loads':samples,'lark_calls':mock.calls,'refresh_status':status}
        finally:
            app.state.live_read.close()
            app.state.engine.dispose()
            if profile:
                profiler.dump_stats(profile)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--runs',type=int,default=5)
    parser.add_argument('--latency',type=float,default=.25)
    parser.add_argument('--projects',type=int,default=319)
    parser.add_argument('--profile')
    parser.add_argument('--compare',action='store_true')
    parser.add_argument('--legacy',action='store_true')
    args = parser.parse_args()
    runs = []
    for _ in range(args.runs):
        for side in ('baseline','optimized') if args.compare else ('baseline' if args.legacy else 'optimized',):
            result = measure(args.latency,args.projects,args.profile,legacy=side=='baseline')
            runs.append(dict(result,side=side))
    artifact = {'latency_seconds':args.latency,'projects':args.projects,'table_counts':TABLE_COUNTS,
                'assumptions':'Fictional existing 319-project fixture. Counts from read-only Lark table lists on 2026-10-14. Mock per-call latency. SQLite. No real network.',
                'runs':runs}
    args.output.write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n')
    for run in runs:
        print(json.dumps({'side':run['side'],'loads':run['loads'],'total_lark_calls':len(run['lark_calls'])}))


if __name__=='__main__':
    main()
