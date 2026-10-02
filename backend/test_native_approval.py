import json
from copy import deepcopy

import pytest

from backend.lark_adapter import RemoteFailure
from backend.native_approval import (NativeApprovalAdapter, prepare_binding,
                                     verify_definition, verify_instance)


def fixture():
    mapping = {'kind': 'node_skip', 'approval_code': 'definition-live-id',
               'fields': {'binding': {'id': 'field-binding', 'name': '案件版本', 'type': 'input'},
                          'content': {'id': 'field-content', 'name': '內容', 'type': 'textarea'}},
               'nodes': [{'id': 'node-real-id', 'seats': ['pm', 'supervisor']}]}
    definition = {'status': 'ACTIVE', 'form': json.dumps(list(mapping['fields'].values())),
                  'node_list': [{'node_id': 'node-real-id', 'node_type': 'AND',
                                 'need_approver': True, 'approver_chosen_multi': True}]}
    context = {'app_id': 'app', 'tenant': 'company', 'workspace_id': 'lark-company',
               'project_id': 'project', 'request_id': 'skip', 'version': 1, 'scope_hash': 'original'}
    binding = prepare_binding(mapping=mapping, definition=definition, context=context,
                              applicant='ou_applicant', approvers={'pm': 'ou_pm', 'supervisor': 'ou_sup'},
                              content={'reason': '不適用', 'impact': '仍須繳交後續成果'})
    instance = {'approval_code': mapping['approval_code'], 'uuid': binding['payload']['uuid'],
                'open_id': 'ou_applicant', 'instance_code': 'real-instance',
                'form': binding['payload']['form'], 'status': 'APPROVED',
                'task_list': [{'id': 'task-' + a, 'node_id': 'node-real-id', 'open_id': a,
                               'status': 'APPROVED', 'type': 'AND'} for a in ('ou_pm', 'ou_sup')],
                'timeline': [{'type': 'PASS', 'task_id': 'task-' + a, 'open_id': a}
                             for a in ('ou_pm', 'ou_sup')]}
    return mapping, definition, context, binding, instance


def test_real_ui_boundary_ids_are_explicit_not_any_fixed_person_node():
    mapping,definition,*_=fixture()
    for role,name in (('start','Submit'),('end','End')):
        ident='ui-hash-'+role
        mapping.setdefault('boundary_nodes',{})[role]={'id':ident,'name':name}
        definition['node_list'].append({'node_id':ident,'name':name,'need_approver':False,
            'node_type':'AND','empty_assignee_list':[],'require_signature':False})
    assert verify_definition(definition,mapping)
    hidden=deepcopy(definition)
    hidden['node_list'].append({'node_id':'hidden-fixed-approver','name':'Approval',
        'need_approver':False,'node_type':'AND','empty_assignee_list':[],'require_signature':False})
    with pytest.raises(RemoteFailure):verify_definition(hidden,mapping)
    hidden['node_list'][-1]['custom_node_id']='START'
    with pytest.raises(RemoteFailure):verify_definition(hidden,mapping)
    for mutation in ({'name':'Approval'},{'need_approver':True},{'node_type':'OR'},
                     {'empty_assignee_list':['ou_hidden']},{'custom_node_id':'hidden'},
                     {'node_id':'replacement-boundary'}):
        changed=deepcopy(definition);changed['node_list'][-1].update(mutation)
        with pytest.raises(RemoteFailure):verify_definition(changed,mapping)


def test_trusted_proof_requires_both_people_and_does_not_mutate_business():
    _, _, _, binding, instance = fixture()
    before = deepcopy(binding)
    result = verify_instance(binding, instance)
    assert result['approved'] is True and result['simulated'] is False
    assert binding == before and 'status' not in result
    assert 'node_auto_approval_list' not in binding['payload']
    assert 'node_approver_user_id_list' not in binding['payload']
    assert binding['payload']['allow_resubmit'] is False


@pytest.mark.parametrize('mutation', [
    lambda x: x.update(approval_code='another'),
    lambda x: x.update(uuid='another'),
    lambda x: x.update(open_id='ou_someone'),
    lambda x: x.update(instance_code=''),
    lambda x: x.update(form='[]'),
    lambda x: x.update(form=x['form'][:-1] + ',' + x['form'][1:]),
    lambda x: x['task_list'][1].update(open_id='ou_pm'),
    lambda x: x['task_list'][1].update(status='DONE'),
    lambda x: x['task_list'][1].update(type='AUTO_PASS'),
    lambda x: x['task_list'][1].update(node_id='another-node'),
    lambda x: x['task_list'].pop(),
    lambda x: x['timeline'].pop(),
    lambda x: x['timeline'].append({'type': 'REMOVE_REPEAT'}),
    lambda x: x['timeline'].append({'type': 'TRANSFER'}),
    lambda x: x.update(status='UNKNOWN'),
])
def test_invalid_remote_binding_or_fake_votes_fail_closed(mutation):
    _, _, _, binding, instance = fixture()
    mutation(instance)
    with pytest.raises(RemoteFailure):
        verify_instance(binding, instance)


def test_value_change_and_existing_code_conflict():
    _, _, _, binding, instance = fixture()
    form = json.loads(instance['form'])
    form[1]['value'] = 'changed'
    instance['form'] = json.dumps(form)
    with pytest.raises(RemoteFailure):
        verify_instance(binding, instance)
    _, _, _, binding, instance = fixture()
    binding['instance_code'] = 'other'
    with pytest.raises(RemoteFailure):
        verify_instance(binding, instance)


@pytest.mark.parametrize('status', ['PENDING', 'REJECTED', 'CANCELED', 'DELETED'])
def test_nonapproved_never_authorizes(status):
    _, _, _, binding, instance = fixture()
    instance['status'] = status
    assert verify_instance(binding, instance)['approved'] is False


def test_reverted_approval_not_authority():
    _, _, _, binding, instance = fixture()
    instance['reverted'] = True
    assert verify_instance(binding, instance)['approved'] is False


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(status='INACTIVE'),
    lambda d: d['node_list'][0].update(node_type='OR'),
    lambda d: d['node_list'][0].update(need_approver=False),
    lambda d: d['node_list'][0].update(approver_chosen_multi=False),
    lambda d: d['node_list'].append(deepcopy(d['node_list'][0])),
    lambda d: d.update(form='[]'),
])
def test_definition_drift_or_weaker_rule_blocked(mutation):
    mapping, definition, *_ = fixture()
    mutation(definition)
    with pytest.raises(RemoteFailure):
        verify_definition(definition, mapping)


def test_same_person_two_seats_and_wrong_company_blocked():
    mapping, definition, context, *_ = fixture()
    for people, ctx in [({'pm': 'ou_same', 'supervisor': 'ou_same'}, context),
                        ({'pm': 'ou_pm', 'supervisor': 'ou_sup'}, dict(context, workspace_id='demo'))]:
        with pytest.raises(RemoteFailure):
            prepare_binding(mapping=mapping, definition=definition, context=ctx,
                            applicant='ou_applicant', approvers=people, content={'x': 1})


class Fake:
    def __init__(self, definition, instance, failure=None):
        self.definition, self.instance, self.failure = definition, instance, failure
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if '/approvals/' in path:
            return deepcopy(self.definition)
        if method == 'POST':
            if self.failure:
                raise self.failure
            return {'instance_code': self.instance['instance_code']}
        return deepcopy(self.instance)


@pytest.mark.parametrize('failure', [None, RemoteFailure('timeout', 'outcome_unknown'),
                                     RemoteFailure('60012', 'blocked')])
def test_durable_checkpoint_and_uuid_recovery_never_duplicate_post(failure):
    _, definition, context, binding, instance = fixture()
    fake = Fake(definition, instance, failure)
    checks = []
    adapter = NativeApprovalAdapter(fake, lambda: checks.append(True))
    checkpoints = []

    def save(next_binding):
        assert not any(c[0] == 'POST' for c in fake.calls)
        checkpoints.append(deepcopy(next_binding))

    receipt = adapter.submit(binding, context, save)
    assert receipt['approved'] is True
    assert len(checkpoints) == 1 and checkpoints[0]['attempted'] is True
    assert checkpoints[0]['status'] == 'outcome_unknown'
    # Simulated process restart from durable pre-network checkpoint.
    assert adapter.submit(checkpoints[0], context, save)['approved'] is True
    assert sum(c[0] == 'POST' for c in fake.calls) == 1
    assert len(checks) == len(fake.calls)
    assert all(c[1].endswith(binding['payload']['uuid']) for c in fake.calls
               if c[0] == 'GET' and '/instances/' in c[1])


def test_checkpoint_failure_and_scope_revision_prevent_post():
    _, definition, context, binding, instance = fixture()
    fake = Fake(definition, instance)
    adapter = NativeApprovalAdapter(fake, lambda: None)

    def failed_save(_):
        raise RuntimeError('CAS conflict')

    with pytest.raises(RuntimeError):
        adapter.submit(binding, context, failed_save)
    assert binding['attempted'] is False
    with pytest.raises(RemoteFailure):
        adapter.submit(binding, dict(context, scope_hash='changed'), lambda _: None)
    assert all(c[0] == 'GET' for c in fake.calls)


def test_revoked_permission_at_post_and_unreadable_outcome_remain_unknown():
    _, definition, context, binding, instance = fixture()
    fake = Fake(definition, instance)
    checks = []

    def auth():
        checks.append(True)
        if len(checks) > 1:
            raise RemoteFailure('revoked', 'blocked')

    checkpoint = []
    with pytest.raises(RemoteFailure):
        NativeApprovalAdapter(fake, auth).submit(binding, context, checkpoint.append)
    assert binding['attempted'] is True and checkpoint[0]['status'] == 'outcome_unknown'
    assert not any(c[0] == 'POST' for c in fake.calls)


def test_readback_failure_is_not_submitted_success_and_retry_only_reads():
    _, definition, context, binding, instance = fixture()
    instance['open_id'] = 'ou_wrong'
    fake = Fake(definition, instance, RemoteFailure('lost response', 'outcome_unknown'))
    adapter = NativeApprovalAdapter(fake, lambda: None)
    for _ in range(2):
        with pytest.raises(RemoteFailure):
            adapter.submit(binding, context, lambda _: None)
    assert sum(c[0] == 'POST' for c in fake.calls) == 1


def test_binding_payload_mutation_and_definition_change_block_before_post():
    _, definition, context, binding, instance = fixture()
    fake = Fake(definition, instance)
    binding['payload']['open_id'] = 'ou_wrong'
    with pytest.raises(RemoteFailure):
        NativeApprovalAdapter(fake, lambda: None).submit(binding, context, lambda _: None)
    assert all(c[0] == 'GET' for c in fake.calls)
    _, definition, context, binding, instance = fixture()
    definition['approval_name'] = 'changed'
    fake = Fake(definition, instance)
    with pytest.raises(RemoteFailure):
        NativeApprovalAdapter(fake, lambda: None).submit(binding, context, lambda _: None)
    assert all(c[0] == 'GET' for c in fake.calls)
