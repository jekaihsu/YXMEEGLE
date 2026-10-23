"""Malformed cost allocation parts receive a validation error, never a server error."""
import pytest
from .test_backend import app, client, act, role, workspace


@pytest.mark.parametrize('parts', [1, 'bad', {'project_id': 'p1', 'amount': '1'}, ['bad'], [None]])
def test_cost_allocation_rejects_malformed_parts(client, parts):
    role(client, 'u-manager')
    before = workspace(client)
    reply = act(client, 'finance_allocate', {'total': '1', 'parts': parts,
                                           'source_id': 'cost-review', 'reason': 'allocation review'})
    assert reply.status_code == 422
    after = workspace(client)
    assert after['cost_allocations'] == before['cost_allocations']
    assert after['version'] == before['version']


def test_cost_allocation_accepts_balanced_object_parts(client):
    role(client, 'u-manager')
    reply = act(client, 'finance_allocate', {'total': '1.5', 'parts': [{'project_id': 'p1', 'amount': '1.5'}],
                                           'source_id': 'cost-review', 'reason': 'allocation review'})
    assert reply.status_code == 200
    assert reply.json()['cost_allocations'][0]['parts'] == [{'project_id': 'p1', 'amount': '1.5'}]
