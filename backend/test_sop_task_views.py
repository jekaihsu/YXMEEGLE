from .test_sop_import import URL, apply, change, h, overview, post  # noqa: F401  (fixture)

IMPORTED = ['start', 'block', 'archive', 'set_applicability', 'edit']


def by_row(h, n):
    return next(t for t in overview(h)['tasks'] if t['origin']['source_row_key'] == f'meegle-v137:A:{n}')


def manual(h, participants=None):
    created = post(h, URL + '/sop-tasks', {'title': 'Review plans', 'node_keys': ['pm'], **({'participants': participants} if participants else {})})
    return created['task']


def act(h, task, action, status=200, **body):
    return post(h, f"{URL}/sop-tasks/{task['id']}/transition", {'expected_revision': task['revision'], 'action': action, **body}, status)


def test_task_flags_and_node_keys_come_without_the_source_grant(h):
    apply(h)
    h.who[0] = 'member'
    shared, single, conditional = by_row(h, 32), by_row(h, 19), by_row(h, 22)
    assert (shared['source_snapshot'], shared['instance_scope'], shared['is_shared'], shared['node_keys']) == (
        None, 'office_shared', True, ['control', 'mapping', 'report'])
    assert (single['instance_scope'], single['is_shared'], single['is_conditional'], single['node_keys']) == (
        'case', False, False, ['confirmation'])
    assert (conditional['applicability'], conditional['is_conditional']) == ('unresolved', True)
    h.who[0] = 'pm'
    decided = act(h, conditional, 'set_applicability', applicability='applicable', reason='有異議')
    assert (decided['task']['applicability'], decided['task']['is_conditional']) == ('applicable', True)


def test_allowed_actions_follow_state_applicability_evidence_and_actor(h):
    apply(h)
    assert by_row(h, 19)['allowed_actions'] == IMPORTED
    assert by_row(h, 22)['allowed_actions'] == ['block', 'archive', 'set_applicability', 'edit']
    task = manual(h, {'executor': 'member', 'checker': 'pm', 'confirmer': 'pm'})
    assert task['allowed_actions'] == ['start', 'block', 'complete', 'archive', 'set_applicability', 'edit']
    h.who[0] = 'member'
    assert next(t for t in overview(h)['tasks'] if t['id'] == task['id'])['allowed_actions'] == ['start', 'block', 'complete']
    assert by_row(h, 19)['allowed_actions'] == []
    h.who[0] = 'other'
    assert next(t for t in overview(h)['tasks'] if t['id'] == task['id'])['allowed_actions'] == []
    h.who[0] = 'pm'
    done = act(h, task, 'complete')['task']
    assert done['allowed_actions'] == ['reopen', 'archive']
    archived = act(h, done, 'archive', reason='重複')['task']
    assert archived['allowed_actions'] == ['restore']
    h.cfg['SOP_TASK_WRITES_ENABLED'] = 'false'
    assert {tuple(t['allowed_actions']) for t in overview(h)['tasks']} == {()}


def test_edit_and_transition_return_the_updated_task(h):
    apply(h)
    task = by_row(h, 19)
    before = overview(h)['checklist_revision']
    edited = change(h, task, {'title': 'Local title'})
    assert (edited['task']['title'], edited['task']['revision'], edited['revision'], edited['checklist_revision']) == (
        'Local title', 2, 2, before + 1)
    started = act(h, edited['task'], 'start')
    assert (started['task']['state'], started['task']['revision'], started['task']['allowed_actions'], started['checklist_revision']) == (
        'in_progress', 3, ['block', 'archive', 'set_applicability', 'edit'], before + 2)
    assert started['task'] == by_row(h, 19)
