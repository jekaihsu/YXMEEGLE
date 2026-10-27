"""Local snapshot read probe. Run: python -m scripts.read_performance_probe --output receipt.json.

Synthetic SQLite fixture; not a staging benchmark. Counts all decoded SQL JSON
values (including metadata), not cursor.rowcount, which is -1 for SELECTs.
"""
import argparse
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median
from time import perf_counter
from sqlalchemy import event
from backend.test_perf_budget import scaled_client, count_queries
from backend.test_shell import ON
from backend.app import BusinessRow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--projects', type=int, default=319)
    parser.add_argument('--samples', type=int, default=7)
    parser.add_argument('--sop-reader', action='store_true', help='Grant only sop_task_read in the fictional fixture; writes remain off')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory, scaled_client(Path(directory), args.projects, **ON) as (app, client):
        if args.samples < 1:
            parser.error('--samples must be positive')
        if args.sop_reader:
            wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
            with app.state.sessions.begin() as db:
                person = db.get(BusinessRow, (wid, 'users', 'u-manager'))
                person.data = {**person.data, 'capabilities': [*person.data.get('capabilities', []), 'sop_task_read']}
        paths = ['/api/session', '/api/settings/overview', '/api/projects/p001', '/api/workspace',
                 '/api/projects/p001/sop-tasks', '/api/projects/p001/sop-assignees']
        result = {'fixture_projects': args.projects, 'samples': args.samples, 'sop_reader': args.sop_reader, 'environment': 'local SQLite/demo; live reads off; shell/index on', 'endpoints': {}}
        decoded = [0, 0]
        selecting_business = [False]
        def before_sql(conn, cursor, statement, parameters, context, many):
            selecting_business[0] = 'FROM business_records' in statement
        event.listen(app.state.engine, 'before_cursor_execute', before_sql)
        def deserialize(raw):
            decoded[0] += 1
            if selecting_business[0]: decoded[1] += 1
            return json.loads(raw)
        app.state.engine.dialect._json_deserializer = deserialize
        # Fresh SQL compilation is needed after changing the diagnostic deserializer.
        app.state.engine.clear_compiled_cache()
        app.state.engine.dialect._type_memos.clear()
        for path in paths:
            rows = []
            for _ in range(args.samples + 1):
                decoded[:] = [0, 0]
                with count_queries(app.state.engine) as stats:
                    started = perf_counter()
                    response = client.get(path)
                    elapsed = (perf_counter() - started) * 1000
                rows.append({'ms': round(elapsed, 2), 'status': response.status_code, 'bytes': len(response.content),
                             'sql_queries': stats['queries'], 'decoded_json_values': decoded[0], 'business_rows': decoded[1], 'server_timing': response.headers.get('server-timing')})
            warm = rows[1:]
            times = sorted(r['ms'] for r in warm)
            result['endpoints'][path] = {'first': rows[0], 'median_ms': median(times), 'p95_ms': times[-1], 'range_ms': [times[0], times[-1]], 'warm': warm}
        # No global decode/query counters during concurrent reads: these are process-wide.
        with ThreadPoolExecutor(max_workers=3) as pool:
            def read(path):
                started = perf_counter(); response = client.get(path)
                return {'path': path, 'ms': round((perf_counter()-started)*1000, 2), 'status': response.status_code}
            result['concurrent_three_reads'] = list(pool.map(read, paths[:3]))
        event.remove(app.state.engine, 'before_cursor_execute', before_sql)
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(json.dumps({path: {k:v for k,v in receipt.items() if k!='warm'} for path,receipt in result['endpoints'].items()}, indent=2))


if __name__ == '__main__':
    main()
