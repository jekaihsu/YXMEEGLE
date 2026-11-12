from copy import deepcopy

import httpx
import pytest
from sqlalchemy import select

from .node_assignment.domain import Actor, NodeAction, NodeKey, NodeStatus, check_node_action
from .sop_import.models import CasePolicy, CaseState, LocalTask, TaskNodeLink, TaskEvent
from .sop_import.domain import Applicability, Lifecycle
from .test_node_assignment_routes import h, act, view, node, NODES, TASKS, CODE, T0


def policy(h, value='legacy'):
    with h.sessions.begin() as db:
        db.merge(CasePolicy(workspace_id='lark-company', project_id='p1', policy=value, revision=1,
                            decided_by='fixture', decided_at=T0, reason='local fixture', facts={}, node_keys=[]))


def complete(h, who='ou_fm', **body):
    return act(h, who, '/nodes/field/legacy_complete', {'request_id': 'legacy-1', 'reason': '舊案成果已核對', **body})


@pytest.mark.parametrize('status', ['未開始', '待處理', '進行中', '待審核'])
def test_legacy_can_complete_every_open_state_without_tasks_or_chain_gate(h, status):
    policy(h)
    if status != '未開始':
        h.case['project'] = {**h.case['project'], 'nodes': [dict(n, status='approved_skipped') if n['key'] in
            ('sales', 'pm', 'confirmation') else n for n in h.case['project']['nodes']]}
    rid = h.fake.add(NODES, {'指派鍵': CODE + '|外業', '確認單編號': CODE, '節點': '外業', '狀態': status})
    if status in ('進行中', '待審核'):
        h.fake.add(TASKS, {'標題': '保留任務', '節點指派': [rid], '狀態': '進行中' if status == '進行中' else '已完成'})
    before = view(h, 'ou_fm', 'field')
    assert before['node']['derived_status'] == status
    tasks, project = deepcopy(h.fake.tables[TASKS]), deepcopy(h.case['project'])
    result = complete(h, expected_revision=before['node']['revision'])
    assert result.status_code == 200, result.text
    assert result.json()['node']['derived_status'] == '已完成'
    assert h.fake.tables[TASKS] == tasks and h.case['project'] == project
    assert not result.json()['can']['legacy_complete']
    fields = h.fake.tables[NODES][rid]
    assert (fields['核准人'], fields['核准時間'], fields['完成時間'], fields['狀態']) == (
        [{'id': 'ou_fm'}], int(T0 * 1000), int(T0 * 1000), '已完成')
    mark = result.json()['node']['legacy_completion']
    assert (mark['actor'], mark['reason'], mark['at']) == (
        {'open_id': 'ou_fm', 'name': '林經理'}, '舊案成果已核對', '2026-09-21T22:13:20+08:00')
    assert view(h, 'ou_fm', 'field')['node']['legacy_completion'] == mark


@pytest.mark.parametrize('value,message', [('managed', '一般完成節點'), ('needs_review', '分類尚未確認'), (None, '分類尚未確認')])
def test_only_explicit_legacy_policy_can_direct_complete(h, value, message):
    if value:
        policy(h, value)
    assert not view(h, 'ou_fm', 'field')['can']['legacy_complete']
    result = complete(h)
    assert result.status_code == 403 and message in result.json()['detail']
    assert h.fake.writes() == []


@pytest.mark.parametrize('reason', [None, '', '  ', 'x' * 501])
def test_reason_is_required_and_bounded_before_any_write(h, reason):
    policy(h)
    result = complete(h, reason=reason)
    assert result.status_code == 422 and h.fake.writes() == []


@pytest.mark.parametrize('who,fields,pm,allowed', [
    ('ou_member', {}, None, False), ('ou_fm', {}, None, True), ('ou_om', {}, None, False),
    ('ou_vp', {}, None, True), ('ou_pm', {'role': 'pm'}, 'ou_pm', True),
    ('ou_pm', {'role': 'pm'}, 'other', False), ('ou_appmanager', {'role': 'manager'}, None, True),
    ('ou_webadmin', {'role': 'member', 'capabilities': ['manage_roles']}, None, True),
])
def test_authority_includes_node_manager_case_pm_and_web_admin(h, who, fields, pm, allowed):
    policy(h)
    h.user_fields.update(fields)
    h.case['project']['pm_id'] = pm
    assert view(h, who, 'field')['can']['legacy_complete'] is allowed
    result = complete(h, who)
    assert result.status_code == (200 if allowed else 403), result.text
    if allowed:
        reopened = act(h, who, '/nodes/field/reject', {'request_id': 'reopen', 'reason': '補充成果',
                                                     'expected_revision': result.json()['node']['revision']})
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()['node']['legacy_completion'] is None
    else:
        assert h.fake.writes() == []


@pytest.mark.parametrize('status', [NodeStatus.DONE, NodeStatus.SKIPPED])
def test_finished_or_skipped_nodes_are_refused_by_domain_and_route(h, status):
    from .node_assignment.domain import IllegalTransition
    with pytest.raises(IllegalTransition):
        check_node_action(Actor(None, 'admin', True), NodeKey.FIELD, NodeAction.LEGACY_COMPLETE,
                          status, frozenset(), case_policy='legacy')
    policy(h)
    if status is NodeStatus.SKIPPED:
        next(n for n in h.case['project']['nodes'] if n['key'] == 'field')['status'] = 'approved_skipped'
    else:
        assert complete(h).status_code == 200
    writes = h.fake.writes()
    assert complete(h, request_id='second').status_code == 409
    assert h.fake.writes() == writes


def test_chain_gap_later_warning_no_cascade_audit_once_replay_and_reopen(h):
    policy(h)
    field = h.fake.add(NODES, {'指派鍵': CODE + '|外業', '確認單編號': CODE, '節點': '外業', '狀態': '未開始'})
    control = h.fake.add(NODES, {'指派鍵': CODE + '|控制', '確認單編號': CODE, '節點': '控制', '狀態': '進行中'})
    h.fake.add(TASKS, {'標題': '先行控制工作', '節點指派': [control], '狀態': '進行中'})
    before = deepcopy(h.fake.tables)
    revision = view(h, 'ou_fm', 'field')['node']['revision']
    result = complete(h, expected_revision=revision)
    assert result.status_code == 200, result.text
    later = node(view(h), 'control')
    assert (later['derived_status'], later['warnings']) == ('未開始', ['lark_status_drift', 'previous_node_not_done'])
    assert node(view(h), 'mapping')['derived_status'] == '未開始'
    assert h.fake.tables[NODES][control] == before[NODES][control]
    assert h.fake.tables[TASKS] == before[TASKS]
    writes = h.fake.writes()
    replay = complete(h, expected_revision=revision)
    assert replay.json() == result.json() and replay.headers['Idempotent-Replayed'] == 'true'
    assert h.fake.writes() == writes
    events = [data for action, actor, data in h.audits() if action == 'node_assignment.legacy_complete' and data['result'] == 'success']
    assert len(events) == 1
    assert (events[0]['project_id'], events[0]['node'], events[0]['reason']) == ('p1', 'field', '舊案成果已核對')
    assert events[0]['legacy_completion']['actor']['open_id'] == 'ou_fm'
    reopened = act(h, 'ou_fm', '/nodes/field/reject', {'request_id': 'reopen', 'reason': '需補核對',
                                                   'expected_revision': result.json()['node']['revision']})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()['node']['legacy_completion'] is None
    assert reopened.json()['node']['derived_status'] == '未開始'
    assert h.fake.tables[NODES][field].get('核准時間') is None
    assert view(h, 'ou_fm', 'field')['can']['legacy_complete']
    assert h.fake.tables[NODES][control] == before[NODES][control] and h.fake.tables[TASKS] == before[TASKS]


def test_stale_revision_and_external_disabled_refuse_writes(h):
    policy(h)
    result = complete(h, expected_revision='0' * 16)
    assert (result.status_code, result.json()['code']) == (409, 'revision_conflict')
    assert h.fake.writes() == []
    h.state['settings']['external_enabled'] = False
    assert not view(h, 'ou_fm', 'field')['can']['legacy_complete']
    assert complete(h).json()['code'] == 'writes_disabled'


def test_legacy_policy_does_not_unblock_other_node_or_sop_operations(h):
    policy(h)
    for action, body in [('complete', {}), ('assign', {'owner_open_ids': ['ou_member']}), ('tasks', {'title': 'x'}),
                         ('reject', {'reason': 'x'})]:
        result = act(h, 'ou_fm', '/nodes/field/' + action, {'request_id': action, **body})
        assert result.json()['code'] == 'writes_disabled'
    assert h.fake.writes() == []


def test_uncertain_write_recovers_after_restart_with_one_audit_event(h):
    policy(h)
    rid = h.fake.add(NODES, {'指派鍵': CODE + '|外業', '確認單編號': CODE, '節點': '外業', '狀態': '未開始'})
    revision = view(h, 'ou_fm', 'field')['node']['revision']

    def timeout(request):
        import json
        h.fake.tables[NODES][rid].update(json.loads(request.content)['fields'])
        raise httpx.ReadTimeout('local fake timeout', request=request)

    h.fake.fault('PUT', f'{NODES}/records/{rid}', timeout)
    assert complete(h, expected_revision=revision).json()['code'] == 'outcome_unknown'
    h.client = h.build()
    recovered = complete(h, expected_revision=revision)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()['node']['legacy_completion']['reason'] == '舊案成果已核對'
    assert len([data for action, actor, data in h.audits() if action == 'node_assignment.legacy_complete' and data['result'] == 'success']) == 1


def test_existing_local_sop_tasks_links_and_events_are_unchanged(h):
    policy(h)
    with h.sessions.begin() as db:
        db.add(CaseState(workspace_id='lark-company', project_id='p1'))
        db.add(LocalTask(workspace_id='lark-company', id='keep-task', project_id='p1', template_family_id='fixture',
                         source_row_key='fixture-row', instance_scope='node', snapshot={'result': '保留原成果'},
                         title='未完成 SOP', instructions='保留', participants={'executor': ['ou_member']},
                         applicability=Applicability.APPLICABLE, state=Lifecycle.PENDING, revision=3, local={}))
        db.add(TaskNodeLink(workspace_id='lark-company', project_id='p1', task_id='keep-task', node_id='p1-field',
                           node_key='field', ordinal=1))
    def contents():
        with h.sessions() as db:
            return {model.__tablename__: [dict(row) for row in db.execute(model.__table__.select()).mappings()]
                    for model in (CaseState, LocalTask, TaskNodeLink, TaskEvent, CasePolicy)}
    before = contents()
    result = complete(h)
    assert result.status_code == 200, result.text
    assert contents() == before
    reopened = act(h, 'ou_fm', '/nodes/field/reject', {'request_id': 'sop-reopen', 'reason': '補核對',
                                                    'expected_revision': result.json()['node']['revision']})
    assert reopened.status_code == 200 and contents() == before


def test_readback_mismatch_does_not_publish_success_marker(h):
    policy(h)
    rid = h.fake.add(NODES, {'指派鍵': CODE + '|外業', '確認單編號': CODE, '節點': '外業', '狀態': '未開始'})
    revision = view(h, 'ou_fm', 'field')['node']['revision']
    h.fake.fault('PUT', f'{NODES}/records/{rid}', lambda request: httpx.Response(200, json={'code': 0, 'data': {}}))
    result = complete(h, expected_revision=revision)
    assert result.json()['code'] == 'readback_mismatch'
    assert not any(data['result'] == 'success' for _, _, data in h.audits())
    assert view(h, 'ou_fm', 'field')['node']['legacy_completion'] is None


def test_duplicate_rows_keep_overview_readable_and_disable_direct_completion(h):
    policy(h)
    assert complete(h).status_code == 200
    h.fake.add(NODES, {'指派鍵': CODE + '|外業', '確認單編號': CODE, '節點': '外業', '狀態': '未開始'})
    h.clock[0] += 61
    h.client = h.build()
    body = view(h, 'ou_fm', 'field')
    assert not body['can']['legacy_complete'] and 'duplicate_assignment_key' in body['node']['warnings']


def test_case_pm_removal_during_read_is_rechecked_before_write(h):
    policy(h)
    h.case['project']['pm_id'] = 'ou_pm'
    def remove_pm(request):
        h.case['project']['pm_id'] = 'someone-else'
    h.fake.fault('POST', f'{NODES}/records/search', remove_pm)
    result = complete(h, 'ou_pm')
    assert result.status_code == 403 and h.fake.writes() == []


def test_later_nodes_can_be_completed_independently_without_releasing_the_gap(h):
    policy(h)
    assert complete(h, 'ou_vp').status_code == 200
    later = act(h, 'ou_vp', '/nodes/control/legacy_complete', {'request_id': 'later', 'reason': '控制成果已核對'})
    assert later.status_code == 200 and later.json()['node']['derived_status'] == '已完成'
    body = view(h)
    assert body['summary']['current_node'] == 'sales'
    assert node(body, 'mapping')['derived_status'] == '未開始'


def test_home_panels_use_the_same_legacy_chain_gap(h):
    from .home_panels import HomePanels
    from .models import AuditRow, Receipt
    from .node_assignment.service import NodeAssignmentService
    from .test_node_assignment_routes import NoBucket
    from .live_read.token_cache import TenantTokenCache
    policy(h)
    assert complete(h).status_code == 200
    control = h.fake.add(NODES, {'指派鍵': CODE + '|控制', '確認單編號': CODE, '節點': '控制',
                                 '工程確認單': ['recCONF1'], '負責人': [{'id': 'ou_member'}], '狀態': '未開始'})
    h.case['project'].update(source_kind='lark', case_visibility='source_reference')
    h.state.update(projects=[h.case['project']], users=[], approvals=[])
    service = NodeAssignmentService({'NODE_ASSIGNMENT_ENABLED': 'true', 'LARK_WORKER_IDENTITY': 'application',
        'LARK_APP_ID': 'app-na', 'LARK_APP_SECRET': 'synthetic', 'LARK_WORKER_ORGANIZATION': 'company'},
        sessions=h.sessions, receipt_model=Receipt, audit_model=AuditRow, skipped_nodes=lambda *_: False,
        transport=httpx.MockTransport(h.fake), clock=lambda: h.clock[0],
        client_options={'token_cache': TenantTokenCache(), 'bucket': NoBucket(), 'sleep': lambda _: None})
    body = HomePanels(service).query(h.state, {'wid': 'lark-company', 'mode': 'lark'}, {'id': 'ou_member', 'active': True}, {})
    later = next(row for row in body['items'] if row['source']['record_id'] == control)
    assert later['derived_status'] == 'not_started' and '等待前置節點' in later['blocked_reasons']


def test_managed_policy_keeps_ordinary_reopen_rules_after_legacy_enrollment(h):
    policy(h)
    result = complete(h)
    assert result.status_code == 200
    with h.sessions.begin() as db:
        row = db.get(CasePolicy, ('lark-company', 'p1'))
        row.policy, row.node_keys = 'managed', ['field']
    detail = view(h, 'ou_fm', 'field')
    assert detail['can']['reject'] and not detail['can']['legacy_complete']
    reopened = act(h, 'ou_fm', '/nodes/field/reject', {'request_id': 'managed-reopen', 'reason': '一般重開',
                                                    'expected_revision': detail['node']['revision']})
    assert reopened.status_code == 200 and reopened.json()['node']['legacy_completion'] is None
