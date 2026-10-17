"""Serve the built UI against synthetic project-progress data. Run from the worktree root."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + str(ROOT / '.runtime/progress-fixture.db')
os.environ['UPLOAD_DIR'] = str(ROOT / '.runtime/progress-fixture-uploads')
os.environ['APP_ENV'] = 'development'
os.environ['DEMO_MODE'] = 'true'
sys.path.insert(0, str(ROOT))
from backend.test_project_progress import chain_state, RawReader
from backend.project_progress import build_project_progress, ReportsView
from backend.reports.snapshot import SnapshotStore

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

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'frontend/dist'), **kwargs)
    def do_GET(self):
        path = urlparse(self.path).path
        if not path.startswith('/api/'):
            return super().do_GET()
        scenario = parse_qs(urlparse(self.headers.get('Referer', '')).query).get('scenario', ['normal'])[0]
        code = 200
        if path == '/api/session':
            user = next(u for u in state['users'] if u['id'] == 'u-manager')
            body = dict(user=user,users=state['users'],features=dict(node_assignment=True,reports=True), mode='demo',auth_configured=False,environment='test',workspace_id='progress-fixture')
        elif path == '/api/workspace':
            body = state
        elif path.endswith('/start-sop'):
            body = dict(project_id=pid,code=project['code'],eligible=False,can_start=True,already_started=True,seeds_optional=True,seeds_pending=4,blockers=[],warnings=[],nodes=[],chain_note='合成資料，節點由 Lark 建立',preview_hash='fixture',plan_rule_version='1')
        elif path.endswith('/node-assignments'):
            body = fixture
        elif path.endswith('/progress'):
            if scenario == 'failure':
                code, body = 503, dict(detail='合成服務暫不可用')
            else:
                cases = [('case-one','115588','執行中',None)]
                if scenario == 'ambiguous': cases.append(('case-two','C115264','報價中',None))
                store = SnapshotStore(RawReader(cases))
                store.get()
                reports = ReportsView(status=scenario if scenario == 'restricted' else 'cold') if scenario in ['cold','restricted'] else ReportsView(store)
                body = build_project_progress(copy.deepcopy(state),pid,reports=reports,amounts=scenario != 'restricted')
                store.close()
                if scenario not in ['cold','restricted']:
                    body['production']['report_rows'] = [dict(case_key=k,case_code=c,dept='field',week='2026-10-12',basis='points',planned=12.5,actual=0,planned_days=2,actual_days=0,matched_days=0,achievement=None,expected_total=None,done_total=None,remaining=None,status=s) for k,c,s,_ in cases]
        elif path == '/api/reports/progress/case':
            body = dict(case=dict(code='115588',name='合成測量案件',status='執行中',client='合成業主',pm='測試 PM',contract=dict(expected=None,actual=None),billing=dict(billed=None,receivable=None,progress=None),revenue_progress=None,cost_progress=None,expected_points=None,cumulative_points_by_dept=dict(field=None,office=None)),week=dict(week='2026-10-12',dept='field',matched=0,unplanned=0,plan_rows=[dict(date='2026-10-12',group='外業',people='測試人員',items='水準測量',points=12.5)],work_rows=[],truncated=False),meta=dict(fetched_at='2026-10-17T09:00:00+08:00',stale=False,gaps=[],snapshot='fixture'))
        else:
            code, body = 404, dict(detail='fixture endpoint absent')
        payload = json.dumps(body,ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

print(f'Fixture project {pid}', flush=True)
ThreadingHTTPServer(('127.0.0.1', 8766), Handler).serve_forever()
