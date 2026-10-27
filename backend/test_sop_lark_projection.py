from copy import deepcopy
from types import SimpleNamespace
import json

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from .models import Base, WorkspaceRow
from .sop_import.models import LocalTask, CaseState, TaskNodeLink, LarkOutbox, TaskEvent
from .sop_import.domain import Applicability, Lifecycle
from .sop_import.lark_projection import (Projection, ProjectionClient, FIELDS, TABLE, BASE, APP_ID,
                                         client_token, sync_key, fingerprint, gates)
from .sop_import.outbox import latest, enqueue_all
from .node_assignment.lark_table import Kind
from .test_sop_import import h, apply, preview, post, URL


class Fake:
    def __init__(self):
        self.records, self.tokens, self.calls = {}, {}, []
        self.lose_create = self.lose_update = self.rate_limit = self.schema_drift = False
        self.n = 0

    def __call__(self, request):
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, path, body, dict(request.url.params)))
        def reply(data, code=0, status=200):
            return httpx.Response(status, json={'code': code, 'data': data})
        if path.endswith('/tenant_access_token/internal'):
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'fake', 'expire': 7200})
        if path.endswith('/fields'):
            if TABLE in path:
                types = {Kind.TEXT: 1, Kind.NUMBER: 2, Kind.SELECT: 3, Kind.MULTI: 4, Kind.DATE: 5, Kind.CHECKBOX: 7, Kind.USERS: 11}
                fields = [{'field_id': fid, 'field_name': name, 'type': types[kind], 'property': {'multiple': True}}
                          for name, (fid, kind) in FIELDS.items()]
                if self.schema_drift:
                    fields[0]['field_name'] = 'renamed'
            else:
                fields = [{'field_id': str(i), 'field_name': name, 'type': kind}
                          for i, (name, kind) in enumerate([('姓名', 1), ('所屬組別', 3), ('職級', 3), ('在職', 7), ('Lark帳號', 11)])]
            return reply({'items': fields, 'has_more': False})
        if TABLE not in path:
            assert request.method == 'GET'
            return reply({'items': [{'record_id': 'person', 'fields': {'姓名': 'Resolved', '在職': True, 'Lark帳號': [{'id': 'ou_known'}]}}], 'has_more': False})
        if path.endswith('/search'):
            condition = body['filter']['conditions'][0]
            found = [r for r in self.records.values() if r['fields'].get(condition['field_name']) == condition['value'][0]]
            return reply({'items': deepcopy(found), 'has_more': False})
        if request.method == 'POST':
            token = request.url.params['client_token']
            if self.rate_limit:
                self.rate_limit = False
                return reply({}, 1254290, 429)
            if token not in self.tokens:
                self.n += 1
                rid = f'rec{self.n}'
                self.tokens[token] = rid
                self.records[rid] = {'record_id': rid, 'fields': deepcopy(body['fields'])}
            rid = self.tokens[token]
            if self.lose_create:
                self.lose_create = False
                raise httpx.ReadTimeout('lost response', request=request)
            return reply({'record': self.records[rid]})
        rid = path.rsplit('/', 1)[-1]
        if rid not in self.records:
            return reply({}, 1254043, 404)
        if request.method == 'DELETE':
            del self.records[rid]
            return reply({})
        if request.method == 'PUT':
            self.records[rid]['fields'] = deepcopy(body['fields'])
            if self.lose_update:
                self.lose_update = False
                raise httpx.ReadTimeout('lost update', request=request)
        return reply({'record': deepcopy(self.records[rid])})


@pytest.fixture
def p(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/p.db')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    cfg = {'SOP_LARK_PROJECTION_ENABLED': 'true', 'LARK_WORKER_ORGANIZATION': 'org',
           'LARK_WORKER_IDENTITY': 'application', 'LARK_APP_ID': APP_ID, 'LARK_APP_SECRET': 'fake'}
    project = {'id': 'SRC-test', 'name': 'Case', 'case_type': 'intake', 'code': 'SRC-test', 'case_visibility': 'source_reference'}
    state = {'environment': 'production', 'settings': {'external_enabled': True}, 'projects': [project]}
    with sessions.begin() as db:
        db.add(WorkspaceRow(id='lark-org', version=1, data={}))
        db.add(CaseState(workspace_id='lark-org', project_id='SRC-test'))
        db.flush()
        db.add(LocalTask(workspace_id='lark-org', id='t1', project_id='SRC-test', template_family_id='family',
                         source_row_key='source32', instance_scope='office_shared', snapshot={'restricted': 'SECRET SOURCE'},
                         title='Task', instructions='SECRET INSTRUCTIONS', participants={'executor': 'ou_known', 'checker': 'unresolved'},
                         applicability=Applicability.APPLICABLE, state=Lifecycle.PENDING, revision=1, local={}))
        db.flush()
        for i, key in enumerate(('control', 'mapping', 'report')):
            db.add(TaskNodeLink(workspace_id='lark-org', project_id='SRC-test', task_id='t1', node_id=key, node_key=key, ordinal=i))
    fake = Fake()
    clock = [1000.]
    projection = Projection(sessions, cfg, lambda wid: deepcopy(state), transport=httpx.MockTransport(fake), clock=lambda: clock[0])
    yield SimpleNamespace(engine=engine, sessions=sessions, cfg=cfg, state=state, project=project, fake=fake,
                          worker=projection, clock=clock)
    engine.dispose()


def row(p):
    with p.sessions() as db:
        return latest(db, 'lark-org', 'SRC-test', 't1')


def test_payload_shared_allowlist_and_people(p):
    p.worker.drain()
    assert row(p).state == 'done'
    values = p.fake.records['rec1']['fields']
    assert set(values) == set(FIELDS)
    assert values['節點'] == ['控制', '圖資', '報告']
    assert values['共用'] is True
    assert values['專案編號'] == 'SRC-test'
    assert values['確認單編號'] == ''
    assert values['負責人'] == [{'id': 'ou_known'}]
    assert values['參與者'] == [{'id': 'ou_known'}]
    assert 'SECRET' not in json.dumps(p.fake.calls)
    assert len(p.fake.records) == 1


def test_token_independent_of_actor_and_content(p):
    token = client_token('lark-org', 'SRC-test', 't1', 1)
    p.fake.rate_limit = True
    p.worker.drain()
    assert row(p).state == 'sent'
    with p.sessions.begin() as db:
        task = db.get(LocalTask, ('lark-org', 't1'))
        task.title, task.participants, task.revision = 'Edited by another actor', {}, 2
    p.worker.drain()
    tokens = [call[3]['client_token'] for call in p.fake.calls if call[0] == 'POST' and call[1].endswith('/records')]
    assert tokens == [token, token]
    assert row(p).state == 'done'
    assert p.fake.records['rec1']['fields']['本地版本'] == 2


def test_lost_create_response_adopt_and_update(p):
    p.fake.lose_create = True
    p.worker.drain()
    assert row(p).state == 'sent'
    p.clock[0] += 10
    p.worker.drain()
    assert row(p).record_id == 'rec1'
    assert row(p).state == 'done'
    assert len([c for c in p.fake.calls if c[0] == 'POST' and c[1].endswith('/records')]) == 1


def test_duplicate_pauses_without_writes(p):
    fields = {'同步鍵': sync_key('SRC-test', 't1', 1), '專案編號': 'SRC-test'}
    p.fake.records = {rid: {'record_id': rid, 'fields': fields} for rid in ('recA', 'recB')}
    p.worker.drain()
    assert row(p).state == 'paused'
    assert row(p).last_error == 'duplicate_sync_key'
    assert not any(c[0] == 'PUT' or c[0] == 'POST' and c[1].endswith('/records') for c in p.fake.calls)


@pytest.mark.parametrize('gate', ['flag', 'external', 'workspace', 'environment', 'allowlist', 'identity', 'app'])
def test_each_gate_zero_http(p, monkeypatch, gate):
    if gate == 'flag': p.cfg['SOP_LARK_PROJECTION_ENABLED'] = 'false'
    if gate == 'external': p.state['settings']['external_enabled'] = False
    if gate == 'workspace': p.cfg['LARK_WORKER_ORGANIZATION'] = 'other'
    if gate == 'environment': p.state['environment'] = 'test'
    if gate == 'allowlist': monkeypatch.setattr('backend.sop_import.lark_projection.formal_write_allowed', lambda *a: False)
    if gate == 'identity': p.cfg['LARK_WORKER_IDENTITY'] = 'user'
    if gate == 'app': p.cfg['LARK_APP_ID'] = 'wrong'
    p.worker.drain()
    assert p.fake.calls == []


@pytest.mark.parametrize('marker', ['case_visibility', 'planning_origin'])
def test_local_planning_zero_http(p, marker):
    p.project[marker] = 'local_planning' if marker == 'case_visibility' else 'local'
    p.worker.drain()
    assert p.fake.calls == []


def test_schema_drift_pause(p):
    p.fake.schema_drift = True
    p.worker.drain()
    assert row(p).state == 'paused'
    assert row(p).last_error.startswith('schema_drift')
    assert not p.fake.records


def test_429_backoff(p):
    p.fake.rate_limit = True
    p.worker.drain()
    count = len(p.fake.calls)
    assert row(p).retry_at > p.clock[0]
    p.worker.drain()
    assert not any(c[0] == 'POST' and c[1].endswith('/records') for c in p.fake.calls[count:])
    p.clock[0] += 10
    p.worker.drain()
    assert row(p).state == 'done'


def test_drift_event_and_reassert(p):
    p.worker.drain()
    p.fake.records['rec1']['fields']['標題'] = 'Lark edit'
    p.clock[0] += 601
    p.worker.drain()
    assert row(p).drift is True
    with p.sessions() as db:
        event = db.scalar(select(TaskEvent).where(TaskEvent.kind == 'lark_drift'))
        assert event.changes['lark_values']['標題'] == 'Lark edit'
    p.worker.drain()
    assert p.fake.records['rec1']['fields']['標題'] == 'Task'
    assert row(p).state == 'done'


def test_deleted_row_bumps_generation(p):
    p.worker.drain()
    del p.fake.records['rec1']
    p.clock[0] += 601
    p.worker.drain()
    p.worker.drain()
    assert row(p).generation == 2
    p.worker.drain()
    assert row(p).state == 'done'
    assert p.fake.records['rec2']['fields']['同步鍵'].endswith('|g2')


def test_unknown_update_readback(p):
    p.worker.drain()
    with p.sessions.begin() as db:
        task = db.get(LocalTask, ('lark-org', 't1'))
        task.title, task.revision = 'changed', 2
    p.fake.lose_update = True
    p.worker.drain()
    assert row(p).state == 'done'
    assert p.fake.records['rec1']['fields']['標題'] == 'changed'


def test_transaction_rollback_and_backfill(p):
    with pytest.raises(RuntimeError):
        with p.sessions.begin() as db:
            task = db.get(LocalTask, ('lark-org', 't1'))
            task.title, task.revision = 'rolled back', 9
            db.flush()
            raise RuntimeError()
    assert row(p).target_revision == 1
    with p.sessions.begin() as db:
        db.query(LarkOutbox).delete()
    assert enqueue_all(p.sessions) == 1
    p.cfg['SOP_LARK_PROJECTION_ENABLED'] = 'false'
    p.worker.drain()
    assert p.fake.calls == []
    p.cfg['SOP_LARK_PROJECTION_ENABLED'] = 'true'
    p.worker.drain()
    assert row(p).state == 'done'


def test_import_mutations_enqueue_while_disabled(h):
    receipt = apply(h)
    with h.sessions() as db:
        rows = list(db.scalars(select(LarkOutbox)))
        assert len(rows) == len(receipt['created_task_ids'])
    tid = receipt['created_task_ids'][0]
    post(h, URL + '/sop-tasks/' + tid + '/transition', {'expected_revision': 1, 'action': 'archive', 'reason': 'archived'})
    with h.sessions() as db:
        assert latest(db, 'w', 'p1', tid).target_revision == 2
    assert h.client.get(URL + '/sop-tasks').json()['tasks'][0]['lark_sync']['state'] == '未啟用'


def test_failed_import_rolls_back_outbox(h, monkeypatch):
    plan = preview(h)
    def fail(*args):
        raise RuntimeError('rollback')
    monkeypatch.setattr(h.service, 'event', fail)
    with pytest.raises(RuntimeError, match='rollback'):
        apply(h, plan)
    with h.sessions() as db:
        assert list(db.scalars(select(LocalTask))) == []
        assert list(db.scalars(select(LarkOutbox))) == []


def test_replay_after_write_flag_revoked_never_needs_lark(h):
    plan = preview(h)
    receipt = apply(h, plan)
    h.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    replay = apply(h, plan)
    assert replay == {**receipt, 'replayed': True}
    assert h.writes == []


def test_manual_edit_archive_restore_refresh_outbox(h):
    created = post(h, URL + '/sop-tasks', {'title': 'Manual', 'node_keys': ['sales']})
    tid = created['task_id']
    response = h.client.patch(URL + '/sop-tasks/' + tid, json={'expected_revision': 1, 'title': 'Edit'})
    assert response.status_code == 200
    post(h, URL + '/sop-tasks/' + tid + '/transition', {'expected_revision': 2, 'action': 'archive', 'reason': 'archive'})
    post(h, URL + '/sop-tasks/' + tid + '/transition', {'expected_revision': 3, 'action': 'restore', 'reason': 'restore'})
    with h.sessions() as db:
        rows = list(db.scalars(select(LarkOutbox)))
        assert len(rows) == 1 and rows[0].target_revision == 4 and rows[0].state == 'none'


def test_changed_sync_key_is_reported_and_repaired(p):
    p.worker.drain()
    p.fake.records['rec1']['fields']['同步鍵'] = 'manually changed'
    p.clock[0] += 601
    p.worker.drain()
    assert row(p).drift is True
    assert p.fake.records['rec1']['fields']['同步鍵'] == sync_key('SRC-test', 't1', 1)
    with p.sessions() as db:
        assert db.scalar(select(TaskEvent).where(TaskEvent.kind == 'lark_drift')) is not None


def test_shared_drain_lock_excludes_second_process_connection(p):
    from .sop_import.lark_projection import drain_lock
    with drain_lock(p.engine) as first:
        assert first
        with drain_lock(p.engine) as second:
            assert not second


def test_readonly_check_reports_drift_without_side_effects(p):
    from .node_assignment.roster import fetch_roster
    p.worker.drain()
    p.fake.records['rec1']['fields']['標題'] = 'Remote change'
    before = len(p.fake.calls)
    with p.worker.client_factory(lambda: pytest.fail('write from readonly check')) as client:
        report = p.worker.reconcile(client, 'lark-org', 'SRC-test', p.project, p.state, fetch_roster(client), readonly=True)
    assert report['issues'][0]['kind'] == 'lark_drift'
    assert p.fake.records['rec1']['fields']['標題'] == 'Remote change'
    assert not any(c[0] == 'PUT' for c in p.fake.calls[before:])
    with p.sessions() as db:
        assert list(db.scalars(select(TaskEvent))) == []
    assert row(p).state == 'done'


def test_backfill_preserves_canary_cleanup_pause(p):
    with p.sessions.begin() as db:
        current = latest(db, 'lark-org', 'SRC-test', 't1')
        current.state, current.last_error = 'paused', 'canary_cleanup'
    enqueue_all(p.sessions)
    p.worker.drain()
    assert row(p).state == 'paused'
    assert not p.fake.records
