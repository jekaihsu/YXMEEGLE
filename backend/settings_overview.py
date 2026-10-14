"""Settings evidence from existing workspace snapshots, without remote reads."""
from fastapi import Request
from fastapi.responses import JSONResponse

from .node_assignment.config import NodeAssignmentConfig
from .policy import CAPABILITIES
from .production_access import hr_view_allowed
from .source_health import build_source_health, _count, _time


def build_overview(data, user, state, cfg, snapshot=None, freshness=None):
    freshness = freshness or {}
    manager = user.get('role') == 'manager' and not user.get('manager_revoked')
    formal = data.get('mode') == 'lark' and state.get('environment') == 'production'
    config = NodeAssignmentConfig.from_env(cfg)
    sources = []
    # The cache carries workspace-wide counts. Only maintenance readers receive them.
    diagnostics = manager or 'manage_sources' in user.get('capabilities', [])
    if formal and diagnostics and snapshot:
        health = build_source_health(snapshot, freshness.get('sources'), diagnostic=True, viewer_filtered=False)
        for row in health['sources']:
            states = (row.get('data_state') or {}).get('states', [])
            sources.append(dict(name=row.get('name', '未命名來源'),
                                readState='complete' if row.get('health') == 'healthy' else '・'.join(states),
                                last_attempt_at=row.get('last_attempt'), last_success_at=row.get('last_success'),
                                source_as_of=None, loaded_count=row.get('loaded_count'), total_count=None,
                                count_scope='workspace_visible', complete=not states or states == ['complete_empty'],
                                last_error_code='source_read_failed' if 'read_failed' in states else None))
    directory = {'status': 'restricted', 'last_success_at': None}
    if hr_view_allowed(user, cfg):
        status = state.get('people_directory_status', {})
        directory = { 'status': status.get('status', 'unknown'),
                      'last_success_at': _time(status.get('last_success_at')),
                      'roster_size': _count(status.get('source_count')),
                      'matched_accounts': _count(status.get('valid_people')) }
    checks = []
    if diagnostics:
        tables = snapshot.get('tables', []) if formal and snapshot else []
        for name, table_id in [('節點指派', config.node_table), ('任務', config.task_table), ('人員名單', config.people_table)]:
            table = next((t for t in tables if t.get('base_token') == config.base and t.get('table_id') == table_id), None)
            if table and (table.get('authorized', True) is not True or table.get('status') in ('forbidden', 'unauthorized')):
                continue
            read = table and table.get('status') in ('ready', 'partial') and (_count(table.get('pages_read')) or 0) > 0
            checks.append({'name': name, 'status': table['status'] if read else 'unknown',
                           'last_success_at': _time(table.get('last_sync', snapshot.get('last_sync'))) if read else None,
                           'last_error_code': 'source_read_failed' if table and table.get('status') == 'error' else None})
    datasets = []
    for key in ('sources', 'roster', 'attendance'):
        item = freshness.get(key, {})
        datasets.append({'name': key, 'status': item.get('status', 'unknown'),
                         'last_success_at': _time(item.get('as_of')),
                         'last_error_code': 'read_failed' if item.get('last_error') else None})
    return {'user': {'name': user.get('name', ''), 'role': user.get('role', 'member'),
                     'permissions': ['read_own_work'] + [c for c in user.get('capabilities', []) if c in CAPABILITIES]},
            'environment': state.get('environment', 'demo' if data.get('mode') == 'demo' else 'unknown'),
            'identity_mode': cfg.get('LARK_WORKER_IDENTITY') if cfg.get('LARK_WORKER_IDENTITY') in ('application', 'user') else 'unknown',
            'features': {'node_assignment': config.enabled, 'change_extension': False, 'routines': False},
            'sources': sources, 'sources_access': 'maintenance' if diagnostics else 'restricted',
            'directory': directory, 'datasets': datasets, 'node_connection': checks,
            'manager_details_available': bool(manager and formal)}


def register(app, identity, load, sessions, workspace_model, cache_model, cfg):
    @app.get('/api/settings/overview')
    def overview(request: Request):
        data, user = identity(request)
        with sessions() as db:
            state = load(db, db.get(workspace_model, data['wid']))
            cache = db.get(cache_model, data['wid'])
            snapshot = cache.data if cache else None
        coordinator = getattr(app.state, 'live_read', None)
        freshness = coordinator.status(data['wid']).get('datasets', {}) if coordinator else {}
        return JSONResponse(build_overview(data, user, state, cfg, snapshot, freshness),
                            headers={'Cache-Control': 'no-store'})
