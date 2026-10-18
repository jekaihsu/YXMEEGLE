"""Regenerate docs/dispatch-publish-api-examples.json from real calls against the fake V4 Bitable.

Usage: LARK_LIVE_READ_TRANSPORT=deny python scripts/dispatch_publish_examples.py
Every example is an actual request and response of the slice 2 routes; no Lark request leaves the process.
"""
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.dispatch_publish.routes import register  # noqa: E402
from backend.live_read.token_cache import TenantTokenCache  # noqa: E402
from backend.models import AuditRow, Base  # noqa: E402
from backend.test_dispatch_publish import APPROVERS, CFG, PROPOSAL, ROLES, T0, NoBucket, seed  # noqa: E402
from backend.test_dispatch_publish_fake import SCHEDULE, TASKS, FakeLark, timeout_after  # noqa: E402

OUT = ROOT / 'docs' / 'dispatch-publish-api-examples.json'


class Harness:
    def __init__(self, folder):
        self.engine = create_engine(f'sqlite:///{folder}/examples.db', connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.fake = FakeLark()
        seed(self.fake)
        self.who, self.clock = ['ou_pm'], [T0]
        self.workspace = {'settings': {'external_enabled': True}, 'environment': 'production'}
        self.examples = []

    def client(self, overrides=None):
        app = FastAPI()
        register(app, identity=lambda _r: ({'mode': 'lark', 'wid': 'lark-company'},
                                           {'id': self.who[0], 'role': ROLES[self.who[0]], 'active': True}),
                 allow=lambda _d, user: user['role'] in ('pm', 'manager'), cfg={**CFG, **(overrides or {})},
                 sessions=self.sessions, audit_model=AuditRow, workspace=lambda _wid: self.workspace,
                 transport=httpx.MockTransport(self.fake),
                 client_options={'token_cache': TenantTokenCache(), 'bucket': NoBucket(), 'sleep': lambda _s: None},
                 clock=lambda: self.clock[0])
        return TestClient(app)

    def call(self, name, who, method, path, body=None, client=None, record=True, note=None):
        self.who[0] = who
        response = getattr(client or self.default, method)(path, **({'json': body} if body is not None else {}))
        if record:
            entry = {'name': name, 'actor': {'open_id': who, 'role': ROLES[who]}, 'request': {'method': method.upper(), 'path': path}}
            if body is not None:
                entry['request']['body'] = body
            entry['response'] = {'status': response.status_code, 'body': response.json()}
            if response.headers.get('Idempotent-Replayed'):
                entry['response']['headers'] = {'Idempotent-Replayed': response.headers['Idempotent-Replayed']}
            if note:
                entry['note'] = note
            self.examples.append(entry)
        return response


def approve(h, preview_id, record=False):
    for who, seat in APPROVERS:
        h.call(f'decision {seat}', who, 'post', f'/api/v2/dispatch/previews/{preview_id}/decisions',
               {'seat': seat, 'decision': 'accepted'}, record=record)


def main():
    folder = tempfile.mkdtemp()
    h = Harness(folder)
    h.default = h.client()
    off = h.client({'DISPATCH_WRITE_ENABLED': 'false'})
    h.call('flag off: every slice 2 route is absent', 'ou_pm', 'post', '/api/v2/dispatch/previews', PROPOSAL, client=off)

    blocked = h.call('preview: unknown people block until verified', 'ou_pm', 'post', '/api/v2/dispatch/previews',
                     {**PROPOSAL, 'crew': ['recP3', 'recP2', 'recP1'], 'verifications': {}}).json()
    created = h.call('preview: verified crew, waiting for approval seats', 'ou_pm', 'post', '/api/v2/dispatch/previews',
                     {**PROPOSAL, 'draft_id': 'draft-b-area-01'}).json()
    pid = created['preview_id']
    h.call('read preview', 'ou_lead', 'get', f'/api/v2/dispatch/previews/{pid}')
    h.call('decision: group leader accepts', 'ou_lead', 'post', f'/api/v2/dispatch/previews/{pid}/decisions',
           {'seat': 'group_leader_confirmed', 'decision': 'accepted'})
    h.call('decision refused: wrong order', 'ou_pmf', 'post', f'/api/v2/dispatch/previews/{pid}/decisions',
           {'seat': 'pm_final', 'decision': 'accepted'})
    h.call('decision: manager accepts', 'ou_mgr', 'post', f'/api/v2/dispatch/previews/{pid}/decisions',
           {'seat': 'manager_review', 'decision': 'accepted'})
    h.call('decision: PM final accepts', 'ou_pmf', 'post', f'/api/v2/dispatch/previews/{pid}/decisions',
           {'seat': 'pm_final', 'decision': 'accepted'})
    h.call('commit refused: blockers', 'ou_pm', 'post', '/api/v2/dispatch/commits',
           {'command_id': 'cmd-blocked-0001', 'preview_id': blocked['preview_id']})
    h.workspace['settings']['external_enabled'] = False
    h.call('commit refused: external connection off (no remote call)', 'ou_pm', 'post', '/api/v2/dispatch/commits',
           {'command_id': 'cmd-b-area-0001', 'preview_id': pid})
    h.workspace['settings']['external_enabled'] = True
    committed = h.call('commit: committed after read-back', 'ou_pm', 'post', '/api/v2/dispatch/commits',
                       {'command_id': 'cmd-b-area-0001', 'preview_id': pid}).json()
    h.call('commit replay: same command_id', 'ou_pm', 'post', '/api/v2/dispatch/commits',
           {'command_id': 'cmd-b-area-0001', 'preview_id': pid})
    h.call('commit refused: another command for a live preview', 'ou_pm', 'post', '/api/v2/dispatch/commits',
           {'command_id': 'cmd-b-area-0002', 'preview_id': pid})
    h.call('command status', 'ou_pm', 'get', '/api/v2/commands/cmd-b-area-0001')
    task_id = committed['command']['task_id']

    unknown = h.call('preview: C area', 'ou_pm', 'post', '/api/v2/dispatch/previews',
                     {**PROPOSAL, 'title': 'C 區外業', 'start': '2026-10-21T08:00+08:00', 'end': '2026-10-21T12:00+08:00'},
                     record=False).json()
    approve(h, unknown['preview_id'])
    h.fake.on('POST', f'/{TASKS}/records', timeout_after)
    h.call('commit: timeout after remote success is outcome_unknown (202)', 'ou_pm', 'post', '/api/v2/dispatch/commits',
           {'command_id': 'cmd-c-area-0001', 'preview_id': unknown['preview_id']})
    h.call('command status for a manager: reconcile offered', 'ou_mgr', 'get', '/api/v2/commands/cmd-c-area-0001')
    h.call('reconcile: row found by 命令編號, committed', 'ou_mgr', 'post', '/api/v2/commands/cmd-c-area-0001/reconcile')

    reassign = h.call('preview: reassign the same task', 'ou_pm', 'post', '/api/v2/dispatch/previews',
                      {**PROPOSAL, 'task_id': task_id, 'primary_owner': 'recP2', 'crew': ['recP2'],
                       'start': '2026-10-20T13:00+08:00', 'end': '2026-10-20T17:00+08:00',
                       'verifications': {'person:recP2': '主管核實 L2 資格'}}).json()
    approve(h, reassign['preview_id'])
    h.call('commit: reassignment updates the same task, revision 2', 'ou_pm', 'post', '/api/v2/dispatch/commits',
           {'command_id': 'cmd-b-area-0002r', 'preview_id': reassign['preview_id']})

    first = h.call('preview: D area', 'ou_pm', 'post', '/api/v2/dispatch/previews',
                   {**PROPOSAL, 'title': 'D 區外業', 'crew': ['recP3'], 'instruments': [], 'start': '2026-10-23T08:00+08:00',
                    'end': '2026-10-23T12:00+08:00', 'verifications': {'person:recP3': 'ok'}}, record=False).json()
    second = h.call('preview: E area', 'ou_pm', 'post', '/api/v2/dispatch/previews',
                    {**PROPOSAL, 'title': 'E 區外業', 'crew': ['recP3'], 'instruments': [], 'start': '2026-10-23T10:00+08:00',
                     'end': '2026-10-23T14:00+08:00', 'verifications': {'person:recP3': 'ok'}}, record=False).json()
    approve(h, first['preview_id'])
    approve(h, second['preview_id'])
    gate = Barrier(2, timeout=10)
    h.fake.on('GET', f'/{SCHEDULE}/records', lambda request, proceed: (gate.wait(), proceed())[1], times=2)
    other = h.client()
    h.who[0] = 'ou_pm'
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda args: args[0].post('/api/v2/dispatch/commits', json=args[1]),
                                [(h.default, {'command_id': 'cmd-d-area-0001', 'preview_id': first['preview_id']}),
                                 (other, {'command_id': 'cmd-e-area-0001', 'preview_id': second['preview_id']})]))
    loser = next(r for r in results if r.status_code == 409)
    h.examples.append({'name': 'commit refused: concurrent overlapping commit lost the reservation race',
                       'actor': {'open_id': 'ou_pm', 'role': 'pm'},
                       'request': {'method': 'POST', 'path': '/api/v2/dispatch/commits',
                                   'body': json.loads(loser.request.content)},
                       'response': {'status': 409, 'body': loser.json()}})

    h.call('draft: save', 'ou_pm', 'put', '/api/v2/dispatch/drafts/draft-f-area-01',
           {'proposal': {'title': 'F 區外業', 'crew': ['recP3'], 'kind': 'execution'}})
    h.call('draft: save with a stale version', 'ou_pm', 'put', '/api/v2/dispatch/drafts/draft-f-area-01',
           {'proposal': {'title': 'F 區外業'}, 'version': 0})
    h.call('draft: load', 'ou_pm', 'get', '/api/v2/dispatch/drafts/draft-f-area-01')
    h.call('draft: list mine', 'ou_pm', 'get', '/api/v2/dispatch/drafts')
    pending = h.call('preview: G area awaiting approval', 'ou_pm', 'post', '/api/v2/dispatch/previews',
                     {**PROPOSAL, 'title': 'G 區外業', 'crew': ['recP2'], 'primary_owner': 'recP2', 'instruments': [],
                      'start': '2026-10-24T08:00+08:00', 'end': '2026-10-24T12:00+08:00',
                      'verifications': {'person:recP2': 'ok'}}, record=False).json()
    h.call('decision: return with a reason', 'ou_lead', 'post', f"/api/v2/dispatch/previews/{pending['preview_id']}/decisions",
           {'seat': 'group_leader_confirmed', 'decision': 'returned', 'reason': '週六不出工'})
    h.call('preview: H area awaiting approval', 'ou_pm', 'post', '/api/v2/dispatch/previews',
           {**PROPOSAL, 'title': 'H 區外業', 'crew': ['recP2'], 'primary_owner': 'recP2', 'instruments': [],
            'start': '2026-10-26T08:00+08:00', 'end': '2026-10-26T12:00+08:00',
            'verifications': {'person:recP2': 'ok'}}, record=False)
    h.call('work queue: PM', 'ou_pm', 'get', '/api/v2/dispatch/work?from=2026-10-19&to=2026-10-31&scope=all')
    h.call('work queue: group leader seat holder, mine', 'ou_lead', 'get', '/api/v2/dispatch/work?scope=mine')
    h.call('assign form for an existing task', 'ou_pm', 'get', f'/api/v2/dispatch/tasks/{task_id}')
    h.call('picker options', 'ou_pm', 'get', '/api/v2/dispatch/options')
    h.call('draft: delete (cancel_draft)', 'ou_pm', 'delete', '/api/v2/dispatch/drafts/draft-f-area-01')

    OUT.write_text(json.dumps({
        '_about': 'Generated by scripts/dispatch_publish_examples.py from real calls against the fake V4 Bitable '
                  '(backend/test_dispatch_publish_fake.py). Clock fixed at 2026-10-19T10:00+08:00. Ids prefixed pv_ '
                  'are random per run. Seat holders: ou_lead (group_leader_confirmed), ou_mgr (manager_review), '
                  'ou_pmf (pm_final). person_ref values are 人員名單 record ids.',
        'examples': h.examples}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    h.engine.dispose()
    print(f'{len(h.examples)} examples -> {OUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
