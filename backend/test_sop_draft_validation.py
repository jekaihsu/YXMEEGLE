"""Admin SOP drafts validate structure before indexing or persisting nested values."""
from copy import deepcopy
import pytest
from .test_backend import app, client, act, role, workspace


@pytest.mark.parametrize('bad', ['missing-key', 'object-key', 'string-tasks', 'scalar-requirement',
                                 'object-label', 'duplicate-node'])
def test_sop_draft_rejects_malformed_nested_structure(client, bad):
    role(client, 'u-manager')
    before = workspace(client)
    source = before['sop_templates'][0]
    nodes = deepcopy(source['nodes'])
    if bad == 'missing-key': nodes[0].pop('key')
    elif bad == 'object-key': nodes[0]['key'] = {}
    elif bad == 'string-tasks':
        nodes[0]['tasks'] = 'abc'
        nodes[0].pop('task_definitions', None)
    elif bad == 'scalar-requirement': nodes[0]['requirements'] = ['bad']
    elif bad == 'object-label': nodes[0]['requirements'][0]['label'] = {'bad': 'object'}
    elif bad == 'duplicate-node': nodes.append(deepcopy(nodes[0]))
    response = act(client, 'sop_draft', {'source_id': source['id'], 'nodes': nodes}, project=None)
    assert response.status_code == 422
    after = workspace(client)
    assert after['sop_templates'] == before['sop_templates']
    assert after['version'] == before['version']


def test_sop_draft_accepts_complete_structured_template(client):
    role(client, 'u-manager')
    before = workspace(client)
    source = before['sop_templates'][0]
    response = act(client, 'sop_draft', {'source_id': source['id'], 'nodes': deepcopy(source['nodes'])},
                   project=None)
    assert response.status_code == 200
    drafts = [t for t in response.json()['sop_templates'] if t.get('created_by') == 'u-manager']
    assert len(drafts) == 1
    assert drafts[0]['nodes'] == source['nodes']
    assert drafts[0]['status'] == 'draft'
