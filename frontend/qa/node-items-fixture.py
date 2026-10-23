"""Serve the built UI against synthetic node-evidence data computed by the real backend code. Run from the worktree root.

Open http://127.0.0.1:8767/?scenario=partial#view=project&project=<id>&tab=flow with scenario nosignal, partial, alldone, restricted,
unknownheavy, uncertain or nulllabel (the last three reshape the partial payload the way a real case would arrive)."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + str(ROOT / '.runtime/node-items-fixture.db')
os.environ['UPLOAD_DIR'] = str(ROOT / '.runtime/node-items-fixture-uploads')
os.environ['APP_ENV'] = 'development'
os.environ['DEMO_MODE'] = 'true'
sys.path.insert(0, str(ROOT))
from backend.test_project_progress import chain_state, set_points
from backend.node_assignment.evidence import production_signal
from backend.node_assignment.domain import NodeKey
from backend.node_assignment.service import hide_report_figures

state, pid, _ = chain_state()
state['projects'] = [p for p in state['projects'] if p['id'] == pid]
project = state['projects'][0]
project.update(name='工程進度驗收 · 合成測量案件', case_type='formal', execution_system='workbench', case_visibility='new_case', execution_allowed=True)
for node in project['nodes']:
    node['tasks'] = []
state['source_status'] = dict(status='ready', last_sync='2026-10-17T09:00:00+08:00', message='合成資料')
fixture = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', "import {assignmentFixture} from './frontend/fixtures/node-assignments.mjs'; console.log(JSON.stringify(assignmentFixture().list))"], cwd=ROOT))
fixture['code'] = project['code']
fixture['summary'] = dict(done=3,total=9,current_node='field')
for node in fixture['nodes']:
    node.update(tasks=dict(done=0,total=0), owners=[], progress=0, record_id='lark-'+node['key'], auto_done=dict(rule='confirmation',reason='已建立工程確認單與合約明細') if node['key'] in ['sales','pm','confirmation'] else None, derived_status='已完成' if node['key'] in ['sales','pm','confirmation'] else '未開始')


SCENARIOS = {
    'nosignal': {},
    'partial': {'外業': [('10', '0'), ('20', '5'), ('4', '4')], '圖資': [('3', '0'), ('2', '2')]},
    'alldone': {'外業': [('10', '0'), ('20', '0'), ('4', '0')]},
    'restricted': {'外業': [('10', '0'), ('20', '5'), ('4', '4')], '圖資': [('3', '0'), ('2', '2')]},
    'unknownheavy': {'外業': [('10', '0'), ('20', '5'), ('4', '4')]},
    'uncertain': {'外業': [('10', '0'), ('20', '5'), ('4', '4')]},
    'nulllabel': {'外業': [('10', '0'), ('20', '5'), ('4', '4')]},
}


def reshape(scenario, evidence):
    items = evidence['work_items']
    if scenario == 'unknownheavy':
        evidence['progress'] = dict(percent='99.9', earned_points='10', planned_points='10', items_done=1, items_total=100, known_items=1, unknown_items=99)
        evidence['items_total'] = 100
        evidence['work_items'] = items[:1] + [dict(items[1], status='no_signal', planned_points=None, remaining_points=None)] * 2
    elif scenario == 'uncertain':
        items[1].update(link_basis='ambiguous', status='no_signal', planned_points=None, remaining_points=None)
        items[2].update(link_basis='unlinked', status='no_signal', planned_points=None, remaining_points=None)
    elif scenario == 'nulllabel':
        items[0].update(code=None, name=None)
        items[1].update(code=None)
        items[2].update(name=None)
OPEN = ('待處理', '進行中')


def payload(scenario):
    scene, vis, _ = chain_state()
    for category, values in SCENARIOS[scenario].items():
        set_points(scene, vis, category, values)
    signals = production_signal(next(p for p in scene['projects'] if p['id'] == vis), scene)
    body = copy.deepcopy(fixture)
    for node in body['nodes']:
        signal = signals.get(NodeKey(node['key'])) if node['key'] in ('field', 'control', 'mapping', 'report') else None
        if signal is None:
            node.update(evidence=None, can_submit_hint=False)
            continue
        first = node['key'] == 'field'
        status = ('進行中' if signal.started else '待處理') if first else '未開始'
        node.update(derived_status=status, evidence={**signal.public(), 'drives_status': first and signal.started},
                    can_submit_hint=signal.can_submit and status in OPEN)
        if first:
            reshape(scenario, node['evidence'])
    if scenario == 'restricted':
        hide_report_figures(body)
    return body


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'frontend/dist'), **kwargs)
    def do_GET(self):
        path = urlparse(self.path).path
        if not path.startswith('/api/'):
            return super().do_GET()
        scenario = parse_qs(urlparse(self.headers.get('Referer', '')).query).get('scenario', ['partial'])[0]
        code = 200
        if path == '/api/session':
            user = next(u for u in state['users'] if u['id'] == 'u-manager')
            body = dict(user=user,users=state['users'],features=dict(node_assignment=True,reports=True), mode='demo',auth_configured=False,environment='test',workspace_id='node-items-fixture')
        elif path == '/api/workspace':
            body = state
        elif path.endswith('/start-sop'):
            body = dict(project_id=pid,code=project['code'],eligible=False,can_start=True,already_started=True,seeds_optional=True,seeds_pending=0,blockers=[],warnings=[],nodes=[],chain_note='合成資料，節點由 Lark 建立',preview_hash='x')
        elif path.endswith('/node-assignments'):
            body = payload(scenario)
        else:
            code, body = 404, dict(detail='fixture endpoint absent')
        out = json.dumps(body,ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(out)))
        self.end_headers()
        self.wfile.write(out)

print(f'Fixture project {pid}', flush=True)
ThreadingHTTPServer(('127.0.0.1', 8767), Handler).serve_forever()
