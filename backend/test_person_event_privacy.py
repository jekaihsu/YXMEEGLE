"""Person-change events expose only a whitelisted audit summary (issue #34). Synthetic data only."""
import json
from copy import deepcopy
from .seed import seed
from .policy import upgrade
from .operations import apply_operation
from .workspace_projection import public_copy, filter_private_workspace

OAUTH_SENTINEL = 'SYNTHETIC_OPEN_ID_SENTINEL'
REASON_SENTINEL = 'SYNTHETIC_INTERNAL_REASON_SENTINEL'
LEAKS = (OAUTH_SENTINEL, REASON_SENTINEL, 'oauth_identity', 'company_admin_authorization')


def workspace():
    ws = upgrade(seed()); ws['environment'] = 'demo'
    manager = next(u for u in ws['users'] if u['role'] == 'manager')
    target = next(u for u in ws['users'] if u['role'] != 'manager')
    target['oauth_identity'] = {'source': 'oauth_user_info', 'open_id': OAUTH_SENTINEL}
    target['company_admin_authorization'] = {'reason': REASON_SENTINEL}
    return ws, manager, target


def member_view(ws):
    member = next(u for u in ws['users'] if u['role'] == 'member' and u['id'] != ws['events'][0]['actor_id'])
    return filter_private_workspace(public_copy(ws), member)


def assert_clean(state):
    blob = json.dumps(state, ensure_ascii=False)
    for leak in LEAKS:
        assert leak not in blob


def test_rename_event_has_no_private_profile_but_keeps_audit_summary():
    ws, manager, target = workspace(); old = target['name']
    apply_operation(ws, manager, {'action': 'admin_person', 'payload': {'id': target['id'], 'name': '新姓名'}}, True)
    assert OAUTH_SENTINEL not in ws['events'][0]['message']
    state = member_view(ws)
    assert_clean(state)
    msg = json.loads(state['events'][0]['message'])
    assert msg == {'person': target['id'], 'changes': {'name': {'before': old, 'after': '新姓名'}}}


def test_deactivate_and_role_change_keep_summary_without_capability_names():
    ws, manager, target = workspace()
    new_role = 'member' if target['role'] == 'pm' else 'pm'
    apply_operation(ws, manager, {'action': 'admin_person', 'payload': {'id': target['id'], 'role': new_role, 'capabilities': ['edit_sop'], 'active': False}}, True)
    state = member_view(ws)
    assert_clean(state)
    msg = json.loads(state['events'][0]['message'])
    assert msg['person'] == target['id'] and msg['capabilities_changed'] is True
    assert msg['changes']['active'] == {'before': True, 'after': False}
    assert msg['changes']['role']['after'] == new_role
    assert 'edit_sop' not in state['events'][0]['message']
    assert state['events'][0]['action'] == 'admin_person' and state['events'][0]['actor_id'] == manager['id']


def test_legacy_full_profile_events_are_rewritten_in_projection():
    ws, manager, target = workspace()
    before = deepcopy(target); after = {**before, 'name': '舊事件新名', 'role': 'pm', 'active': False, 'capabilities': ['edit_sop']}
    ws['events'].insert(0, {'id': 'legacy', 'actor_id': manager['id'], 'action': 'admin_person', 'created_at': 'x',
                            'message': json.dumps({'person': target['id'], 'before': before, 'after': after}, ensure_ascii=False)})
    state = member_view(ws)
    assert_clean(state)
    msg = json.loads(state['events'][0]['message'])
    assert msg['changes']['name']['after'] == '舊事件新名' and msg['changes']['active']['after'] is False
    assert msg['capabilities_changed'] is True and 'edit_sop' not in state['events'][0]['message']
    assert OAUTH_SENTINEL in json.dumps(ws['events'][0])  # authoritative storage is untouched


def test_malformed_or_extended_person_events_fail_closed():
    ws, manager, target = workspace()
    ws['events'][:0] = [
        {'id': 'bad', 'action': 'admin_person', 'actor_id': manager['id'], 'message': 'not json ' + OAUTH_SENTINEL},
        {'id': 'ext', 'action': 'admin_person', 'actor_id': manager['id'], 'message': json.dumps(
            {'person': 'p', 'changes': {'name': {'before': 'a', 'after': 'b'}, 'oauth_identity': {'before': None, 'after': OAUTH_SENTINEL}}, 'x': REASON_SENTINEL})}]
    state = member_view(ws)
    assert_clean(state)
    assert json.loads(state['events'][0]['message'])['changes'] == {}
    assert list(json.loads(state['events'][1]['message'])['changes']) == ['name']
