"""Offline case reads: python -B -m backend.benchmark_case_detail [--profile].

Uses fictional company-scale data in temporary SQLite; no Lark readers run.
Setup and fixture persistence are excluded from request measurements.
"""
import argparse
import cProfile
from contextlib import contextmanager
import io
import json
from pathlib import Path
import pstats
import statistics
from tempfile import TemporaryDirectory
from time import perf_counter

from .test_perf_budget import count_queries, scaled_client


@contextmanager
def case_client(directory, projects, source_records=0):
    with scaled_client(directory, projects, upgraded=True,
                       WORKSPACE_SHELL_ENABLED='true', REPORTS_ENABLED='false',
                       LARK_ALLOWED_TENANTS='case-perf' if source_records else '') as (app, client):
        if source_records:
            app.state.cfg['LARK_WORKER_ORGANIZATION'] = 'case-perf'
            from .app import AuthRow, BusinessRow, CacheRow, PersonRow, WorkspaceRow
            from .perf_fixture import build_scaled_workspace
            from .policy import upgrade
            from . import storage
            state = build_scaled_workspace(projects)
            state['environment'] = 'production'
            records = []
            for collection in ('source_quotes', 'source_confirmations', 'contract_items'):
                for item in state[collection]:
                    item['source_kind'] = item['kind']
                    records.append(dict(item['source_identity'], kind=item['kind'], fields=item['fields']))
            while len(records) < source_records:
                records.append(dict(base_token='base', table_id='daily', record_id=f'rec{len(records)}',
                    kind='daily', fields={'案件編號': 'C115000', '工作內容': 'Fictional field observation ' * 8}))
            state['source_visible_record_ids'] = ['|'.join(r[k] for k in ('base_token','table_id','record_id')) for r in records]
            stamp = '2026-10-01T00:00:00+08:00'
            state['source_status'] = dict(status='ready', last_sync=stamp)
            upgrade(state)
            wid = 'lark-case-perf'
            with app.state.sessions.begin() as db:
                row = WorkspaceRow(id=wid, version=1, data={})
                db.add(row); db.flush()
                row.data = storage.save(db, BusinessRow, wid, state)
                db.add(AuthRow(id='offline-perf', data=dict(wid=wid, expires=9999999999)))
                for person in state['users']:
                    db.add(PersonRow(organization_id=wid, person_id=person['id'], data=person))
                db.add(CacheRow(id=wid, data=dict(status='ready', last_sync=stamp, records=records,
                    tables=[dict(base_token='base', table_id=table, status='ready', pages_read=1)
                            for table in ('tbl','daily')])))
            client.cookies.clear()
            client.cookies.set('meegle_session', app.state.signer.dumps(dict(mode='lark', wid=wid, uid='u-manager', sid='offline-perf')))
        yield app, client


def dense_case(lines=400):
    """One large fictional imported case, with two tasks/evidence links per line."""
    from .test_case_detail import fixture, task
    state = fixture('test')
    project = state['projects'][0]
    state['projects'] = [project]
    state['source_confirmations'] = state['source_confirmations'][:1]
    state['contract_items'], state['source_work_items'], project['files'] = [], [], []
    node = project['nodes'][0]
    project['nodes'] = [node]
    node['tasks'] = []
    for i in range(lines):
        cid = f'b/con/k{i}'
        state['contract_items'].append(dict(id=cid, project_id='p', title=f'Line {i}',
            confirmation_ids=['b/conf/c1'], item_number=str(i)))
        for j in range(2):
            tid = f't{i}-{j}'
            node['tasks'].append(task(tid, tid))
            state['source_work_items'].append(dict(id=f'b/rep/{tid}', project_id='p',
                contract_ids=[cid], category='外業'))
            project['files'].append(dict(id=f'f{tid}', name=f'{tid}.pdf', node_id=node['id'], task_id=tid))
    return state


def measure_dense(rounds=7):
    from .case_detail import build_case_detail
    from .case_navigation import case_navigation
    state = dense_case()
    result = {'contracts': 400, 'tasks': 800}
    for name, build in (('tree', lambda: build_case_detail(state, 'p', confirmation_key='b/conf/c1')),
                        ('navigation', lambda: case_navigation(state, 'p'))):
        samples = []
        for _ in range(rounds):
            started = perf_counter()
            build()
            samples.append((perf_counter() - started) * 1000)
        result[name + '_p50_ms'] = round(statistics.median(samples), 2)
    return result


def run(projects=319, rounds=7, profile=False, source_records=0):
    result = {'projects': projects, 'rounds': rounds, 'source_records': source_records,
              'dense_case': measure_dense(rounds), 'endpoints': {}}
    with TemporaryDirectory(prefix='case-detail-perf-') as directory:
        with case_client(Path(directory), projects, source_records) as (app, client):
            for path in ('/api/projects/p001', '/api/projects/p001/navigation',
                         '/api/case-detail/p001', '/api/projects/p001/progress'):
                samples, timings, sizes, queries = [], [], [], []
                for _ in range(rounds):
                    with count_queries(app.state.engine) as sql:
                        started = perf_counter()
                        response = client.get(path, headers={'Accept-Encoding': 'identity'})
                        samples.append((perf_counter() - started) * 1000)
                    assert response.status_code == 200, (path, response.text)
                    sizes.append(len(response.content))
                    queries.append(sql['queries'])
                    timings.append(response.headers.get('Server-Timing'))
                result['endpoints'][path] = dict(p50_ms=round(statistics.median(samples), 2),
                    max_ms=round(max(samples), 2), payload_bytes=max(sizes),
                    queries=max(queries), server_timing=timings[-1])
                if profile:
                    # Profile the actual synchronous handler on this thread.
                    from starlette.requests import Request
                    route = next(r for r in app.routes if getattr(r, 'path', None) ==
                                 path.replace('p001', '{project_id}'))
                    request = Request({'type': 'http', 'method': 'GET', 'path': path,
                        'query_string': b'', 'headers': [(b'cookie',
                        f'meegle_session={client.cookies.get("meegle_session")}'.encode())]})
                    profiler = cProfile.Profile()
                    profiler.runcall(route.endpoint, request, 'p001')
                    stream = io.StringIO()
                    pstats.Stats(profiler, stream=stream).sort_stats('cumulative').print_stats(18)
                    result['endpoints'][path]['profile'] = stream.getvalue()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--projects', type=int, default=319)
    parser.add_argument('--rounds', type=int, default=7)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--source-records', type=int, default=0, help='synthetic Lark-mode source cache size; external reads stay disabled')
    args = parser.parse_args()
    print(json.dumps(run(args.projects, args.rounds, args.profile, args.source_records), indent=2))
