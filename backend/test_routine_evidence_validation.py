"""A recurring owner cannot persist non-text evidence that breaks the routines page."""
import pytest
from .test_backend import app, client, act, workspace


@pytest.mark.parametrize('evidence', [{'text': 'bad'}, ['bad'], True, 123, None])
def test_routine_evidence_rejects_nontext_without_creating_history(client, evidence):
    create = act(client, 'recurring_create', {'kind': 'field_schedule', 'owner_id': 'u-pm',
                                            'start_date': '2026-10-01'})
    assert create.status_code == 200
    before = create.json()
    ident = before['recurring'][-1]['id']
    reply = act(client, 'recurring_complete', {'id': ident, 'evidence': evidence})
    assert reply.status_code == 422
    after = workspace(client)
    assert after['recurring'] == before['recurring']
    assert after['version'] == before['version']


def test_routine_evidence_accepts_text_for_pending_review(client):
    create = act(client, 'recurring_create', {'kind': 'field_schedule', 'owner_id': 'u-pm',
                                            'start_date': '2026-10-01'})
    assert create.status_code == 200
    ident = create.json()['recurring'][-1]['id']
    reply = act(client, 'recurring_complete', {'id': ident, 'evidence': 'Dispatch reviewed'})
    assert reply.status_code == 200
    history = reply.json()['recurring'][-1]['history']
    assert [(row['evidence'], row['status']) for row in history] == [('Dispatch reviewed', 'pending')]
