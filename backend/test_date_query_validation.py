"""Dates used by lexical sorting must use the API's YYYY-MM-DD contract."""
import pytest
from fastapi import HTTPException
from .workflow import valid_date
from .test_backend import app, client, act, workspace


@pytest.mark.parametrize('value', ['20261009', '2026-W41-5', '2026-02-30', '', None])
def test_workflow_rejects_noncanonical_or_invalid_dates(value):
    with pytest.raises(HTTPException):
        valid_date(value)
    assert valid_date('2026-10-09') == '2026-10-09'


def test_task_cannot_persist_compact_schedule_dates(client):
    before = workspace(client)
    reply = act(client, 'task_add', {'title': 'Date contract', 'start_date': '20261001',
                                    'due_date': '20261009'}, node='p1-control')
    assert reply.status_code == 400
    after = workspace(client)
    assert after['version'] == before['version']
    assert after['projects'] == before['projects']


@pytest.mark.parametrize('query', [
    {'date_from': 'garbage'}, {'date_to': '2026-02-30'}, {'date_from': '20261009'},
    {'date_to': '2026-W41-5'}, {'date_from': '2026-10-10', 'date_to': '2026-10-09'},
])
def test_daily_query_rejects_invalid_date_range(client, query):
    reply = client.get('/api/daily-reports', params=query)
    assert reply.status_code == 422


def test_daily_query_accepts_canonical_inclusive_range(app, client):
    from .app import WorkspaceRow, BusinessRow
    from . import storage
    wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, wid)
        state = storage.load(db, BusinessRow, row)
        state['projects'][0]['daily_reports'] = [
            {'id': 'inside', 'date': '2026-10-09', 'description': 'Survey'},
            {'id': 'outside', 'date': '2026-10-10', 'description': 'Next day'},
        ]
        row.data = storage.save(db, BusinessRow, wid, state)
    reply = client.get('/api/daily-reports', params={'date_from': '2026-10-09', 'date_to': '2026-10-09'})
    assert reply.status_code == 200
    assert [row['id'] for row in reply.json()['items']] == ['inside']
