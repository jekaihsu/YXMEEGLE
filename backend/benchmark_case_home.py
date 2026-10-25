"""Local-only case/home read benchmark: python -B -m backend.benchmark_case_home --output /tmp/home.json.

Fresh fictional 319-case SQLite database per run. No credentials, live Lark or
persistent data. Warm samples exclude the first request; no timing assertions.
"""
import argparse
import json
import socket
import tempfile
from pathlib import Path
from statistics import median
from time import perf_counter
from unittest.mock import patch

from .test_perf_budget import count_queries, scaled_client
from .test_node_assignment_routes import BASE, project
from .node_assignment.cache import Cached
from .node_assignment.domain import NODE_LABELS


def fixture(state):
    for p in state['projects']:
        p['source_records'] = [dict(project()['source_records'][0],
            url=f"https://example.invalid/base/{BASE}?table=tblmSQrcCs9vPQZx&record=rec{p['id']}")]


def offline_assignments(app):
    service = app.state.home_panels
    service.assignment_unavailable = lambda *_: None
    rows = [{'record_id': f"rec{p}-{key.value}", 'fields': {
        '指派鍵': f'C11{5000+p}|{label}', '確認單編號': f'C11{5000+p}', '節點': label,
        '工程確認單': [f'recp{p+1:03d}'], '狀態': '未開始', '負責人': [{'id': 'ou_015'}]}}
        for p in range(319) for key, label in NODE_LABELS.items()]
    service.assignment_sources = lambda *_, **__: ({
        'node_assignments': Cached(rows, False, 1790000000),
        'tasks': Cached([], False, 1790000000)}, None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--samples', type=int, default=7)
    args = parser.parse_args()
    if args.samples < 1: parser.error('--samples must be positive')
    def forbidden(*_, **__): raise AssertionError('benchmark attempted external I/O')
    result = {'fixture': {'projects': 319, 'tasks': 7018, 'daily_reports': 9000},
              'environment': 'fictional local SQLite/demo; live reads disabled; assignment cache mocked', 'profiles': {}}
    with tempfile.TemporaryDirectory(prefix='yx-home-') as directory, patch.object(socket, 'create_connection', forbidden):
        with scaled_client(Path(directory), 319, upgraded=True, mutate=fixture,
                           INDEX_TABLES_ENABLED='true', WORKSPACE_SHELL_ENABLED='true') as (app, client):
            assert client.post('/api/demo/session', json={'user_id': 'ou_015'}).status_code == 200
            decoded = [0]
            def deserialize(raw):
                decoded[0] += 1
                return json.loads(raw)
            app.state.engine.dialect._json_deserializer = deserialize
            app.state.engine.clear_compiled_cache()
            app.state.engine.dialect._type_memos.clear()
            for profile in ('disabled_assignments', 'mocked_assignments'):
                if profile == 'mocked_assignments': offline_assignments(app)
                paths = ['/api/projects?view=portfolio', '/api/home-panels?panel=assigned&limit=100',
                         '/api/home-panels?panel=confirmation&limit=100']
                if profile == 'disabled_assignments':
                    paths += ['/api/company-dashboard?offset=0&limit=5', '/api/my-work']
                results = {}
                for path in paths:
                    samples = []
                    for _ in range(args.samples + 1):
                        decoded[0] = 0
                        with count_queries(app.state.engine) as sql:
                            started = perf_counter()
                            response = client.get(path)
                            elapsed = (perf_counter() - started) * 1000
                        assert response.status_code == 200, (path, response.status_code, response.text[:200])
                        samples.append({'ms': round(elapsed, 2), 'queries': sql['queries'],
                            'decoded_json_values': decoded[0], 'bytes': len(response.content),
                            'wire_bytes': int(response.headers.get('content-length', 0))})
                    results[path] = {'first': samples[0], 'median_ms': round(median(s['ms'] for s in samples[1:]), 2),
                                     'warm': samples[1:]}
                result['profiles'][profile] = results
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
