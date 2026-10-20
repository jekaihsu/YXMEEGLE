"""Add captured entries to backend/sop_import/api-examples.json from real calls against a throwaway demo app.

Usage: python3 scripts/sop_import_examples.py
The app runs on a temporary SQLite file with no Lark configuration. The original preview, apply and sop_tasks
entries keep their recorded values because frontend tests read them; amend() only adds the fields later slices
introduced, computed by the same backend code. Every other entry is replaced by this run. IDs and timestamps differ
per run.
"""
import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from backend import storage  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.models import BusinessRow, WorkspaceRow  # noqa: E402
from backend.seed import seed  # noqa: E402
from backend.sop_import.catalog import load_catalog, publish, stage  # noqa: E402
from backend.sop_import.domain import CONDITIONAL, NODE_MAP, Applicability, Lifecycle  # noqa: E402
from backend.sop_import.models import LocalTask  # noqa: E402
from backend.sop_import.service import Context, Service  # noqa: E402
from backend.v4_sources import import_v4  # noqa: E402

OUT = ROOT / 'backend' / 'sop_import' / 'api-examples.json'
CAPS = ['sop_task_read', 'sop_task_import', 'sop_task_work', 'sop_task_read_source', 'create_local_case']
QUOTE = {'報價編號': '115588', '工程名稱': '新昇案-33筆地號(鑽探)', '行號單位': '永達能源工程股份有限公司',
         '詢價日期': 1787068800000, '第一次聯繫日期': 1787068800000, '報價日期': 1786291200000,
         '提供給PM日期': 1786291200000, '報價期限': 1787500800000, '回傳單日期': 1789574400000,
         '契約價格(未稅)': 24000, '工程編號': 'C115264', '狀態': '成案', '此案確認單': [],
         '報價負責人': [{'id': 'ou_quote_owner', 'name': '吳柏頤'}], '案件負責人': [{'id': 'ou_case_pm', 'name': '林育寬'}]}


def call(client, method, path, body=None, status=200):
    response = client.request(method, path, json=body)
    assert response.status_code == status, (path, response.status_code, response.text)
    return response.json()


def setup(app):
    with app.state.sessions.begin() as db:
        workspace = db.scalar(select(WorkspaceRow))
        state = storage.load(db, BusinessRow, workspace)
        for user in state['users']:
            if user['id'] == 'u-pm':
                user['capabilities'] = sorted(set(user.get('capabilities', [])) | set(CAPS))
        source = seed(True)
        record = {'kind': 'quote', 'base_token': 'quote-base', 'table_id': 'quote-table', 'record_id': 'recQuote115588',
                  'fields': deepcopy(QUOTE)}
        import_v4(source, [record])
        case = source['projects'][0]
        case.update(case_visibility='source_reference', execution_system='pending', pm_id='u-pm')
        state['projects'].append(case)
        state['source_quotes'] = [{'id': 'quote-base/quote-table/recQuote115588', 'source_kind': 'quote',
                                   'source_identity': {k: record[k] for k in ('base_token', 'table_id', 'record_id')},
                                   'source_missing': False, 'project_id': case['id'], 'project_ids': [case['id']],
                                   'code': '115588', 'fields': deepcopy(QUOTE), 'readonly': True}]
        workspace.data = storage.save(db, BusinessRow, workspace.id, state)
        workspace.version += 1
        version = stage(db, workspace.id, 'plumb-v0.2-1', load_catalog(), source_verified=True)
        publish(db, version, 'u-manager', 100)
        return case['id'], version.id


def suggestions(client, pid, vid):
    url = f'/api/projects/{pid}'
    plan = call(client, 'POST', url + '/sop-import/preview', {'template_version_id': vid, 'node_keys': ['sales', 'pm']})
    call(client, 'POST', url + '/sop-import/apply', {'preview_id': plan['preview_id'], 'request_id': 'examples-import'})
    listing = call(client, 'GET', url + '/sop-tasks?node_key=sales')
    by_key = {t['origin']['source_row_key']: t for t in listing['tasks']}
    proof, indicator, dismissed = (by_key[f'meegle-v137:A:{n}'] for n in (12, 15, 1))
    accepted = call(client, 'POST', f"{url}/sop-tasks/{proof['id']}/suggestion",
                    {'action': 'accept_suggestion', 'facts_hash': proof['suggestion']['facts_hash'],
                     'expected_revision': proof['revision']})
    stale = call(client, 'POST', f"{url}/sop-tasks/{indicator['id']}/suggestion",
                 {'action': 'accept_suggestion', 'facts_hash': '0' * 64, 'expected_revision': indicator['revision']}, 409)
    dismiss = call(client, 'POST', f"{url}/sop-tasks/{dismissed['id']}/suggestion",
                   {'action': 'dismiss_suggestion', 'facts_hash': dismissed['suggestion']['facts_hash'], 'reason': '待補佐證'})
    bulk = call(client, 'POST', url + '/sop-tasks/suggestions/accept',
                {'tasks': [{'task_id': indicator['id'], 'facts_hash': indicator['suggestion']['facts_hash'],
                            'expected_revision': indicator['revision']}], 'confirm': True, 'reason': '回簽附件已上傳'})
    return {'sop_tasks_with_suggestions': {**listing, 'tasks': [proof, indicator]},
            'accept_suggestion': accepted, 'accept_suggestion_stale': stale, 'dismiss_suggestion': dismiss,
            'accept_suggestions': bulk}


def amend(examples):
    rows = {r['source_row_key']: r for r in load_catalog()['case_sop_rows']}
    preview = examples['preview']
    selected = preview['selection']['node_keys']

    def outcomes(items):
        for item in items:
            item['node_keys'] = [k for k in NODE_MAP.values()
                                 if k in selected and k in rows[item['source_row_key']]['proposed_import']['target_branch_node_keys']]
        whole = set(selected) == set(NODE_MAP.values())
        return [item for item in items if item['node_keys'] or whole]
    preview['outcomes'] = outcomes(preview['outcomes'])
    examples['apply']['exclusions'] = outcomes(examples['apply']['exclusions'])
    if isinstance(preview['expires_at'], int):
        preview['expires_at'] = 1792496832.94495
    listing = examples['sop_tasks']
    user = {'id': 'u-pm', 'role': 'pm', 'active': True, 'capabilities': CAPS}
    ctx = Context('w', user, {}, {'id': listing['project_id'], 'case_type': 'intake', 'pm_id': 'u-pm'}, None)
    service = Service(None, writes_enabled=lambda: True)
    for task in listing['tasks']:
        keys = {n['node_key'] for n in task['nodes']}
        task['node_keys'] = [k for k in NODE_MAP.values() if k in keys]
        task['instance_scope'] = task['origin']['instance_scope']
        task['is_shared'] = task['instance_scope'] != 'case' or len(keys) > 1
        task['is_conditional'] = rows[task['origin']['source_row_key']]['raw']['meegle_id'] in CONDITIONAL
        state = LocalTask(state=Lifecycle(task['state']), applicability=Applicability(task['applicability']),
                          participants=task['participants'], local=task['local'], previous_state=None)
        task['allowed_actions'] = service.task_actions(ctx, state, task['suggestion'])


def task_commands(client, pid, vid):
    url = f'/api/projects/{pid}'
    target = next(t for t in call(client, 'GET', url + '/sop-tasks')['tasks'] if t['origin']['source_row_key'] == 'meegle-v137:A:3')
    edited = call(client, 'PATCH', f"{url}/sop-tasks/{target['id']}", {'expected_revision': target['revision'], 'title': '通知業主報價成立（本案）'})
    started = call(client, 'POST', f"{url}/sop-tasks/{target['id']}/transition",
                   {'expected_revision': edited['revision'], 'action': 'start'})
    created = call(client, 'POST', url + '/sop-tasks', {'title': '確認圖資格式', 'node_keys': ['sales']})
    preview = url + '/sop-import/preview'
    return {'templates': call(client, 'GET', '/api/sop-templates'),
            'sop_assignees': call(client, 'GET', url + '/sop-assignees'), 'task_edit': edited, 'task_transition': started,
            'manual_task': created,
            'preview_error_node_mapping_invalid': call(client, 'POST', preview, {'template_version_id': vid, 'node_keys': ['sales', 'N02']}, 422),
            'preview_error_row_not_importable': call(client, 'POST', preview, {'template_version_id': vid, 'node_keys': ['sales'],
                                                                                'row_keys': ['meegle-v137:A:19']}, 422),
            'preview_error_applicability_unresolved': call(client, 'POST', preview, {'template_version_id': vid, 'node_keys': ['sales'],
                                                                                      'row_keys': ['meegle-v137:A:7']}, 422)}


def register(client):
    return {'quotes': call(client, 'GET', '/api/quotes?q=115588'), 'quote': call(client, 'GET', '/api/quotes/115588')}


def local_case(client):
    form = {'name': '新竹科學園區地形測量', 'pm_id': 'u-pm', 'client': '竹科管理局', 'description': '初步詢價',
            'official_quote_no': '115950', 'node_keys': ['sales']}
    draft = call(client, 'POST', '/api/quotes/preview', form)
    body = {'draft_id': draft['draft_id'], 'request_id': 'examples-local-case'}
    created = call(client, 'POST', '/api/quotes', body)
    return {'quote_preview': draft, 'quote_create': created, 'quote_create_replay': call(client, 'POST', '/api/quotes', body),
            'quote_request': call(client, 'GET', '/api/quotes/requests/examples-local-case'),
            'quote_number_taken': call(client, 'POST', '/api/quotes/preview', {**form, 'official_quote_no': '115588'}, 409),
            'quotes_with_local': call(client, 'GET', '/api/quotes?q=115950')}


def main():
    with tempfile.TemporaryDirectory() as folder:
        config = {'DATABASE_URL': f'sqlite:///{folder}/examples.db', 'UPLOAD_DIR': f'{folder}/uploads',
                  'SESSION_SECRET': 'examples-secret' * 4, 'APP_ENV': 'development', 'DEMO_MODE': 'true',
                  'SOP_TASK_WRITES_ENABLED': 'true', 'LOCAL_CASE_CREATION_ENABLED': 'true'}
        app = create_app(config)
        with TestClient(app) as client:
            client.get('/api/session')
            call(client, 'POST', '/api/demo/session', {'user_id': 'u-pm'})
            pid, vid = setup(app)
            captured = {**suggestions(client, pid, vid), **task_commands(client, pid, vid), **register(client),
                        **local_case(client)}
        app.state.engine.dispose()
    examples = json.loads(OUT.read_text())
    amend(examples)
    examples.update(captured)
    OUT.write_text(json.dumps(examples, ensure_ascii=False, indent=2) + '\n')
    print('\n'.join(sorted(captured)))


if __name__ == '__main__':
    main()
