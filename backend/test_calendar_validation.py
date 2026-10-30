"""Calendar mutations reject malformed lists without changing durable state."""
import pytest
from .test_backend import app, client, act, role, workspace


@pytest.mark.parametrize('value', [None, 1, True, '2026-10-09', {'date': '2026-10-09'}, [None]])
@pytest.mark.parametrize('field', ['holidays', 'workdays'])
def test_calendar_rejects_malformed_date_lists(app, client, field, value):
    role(client, 'u-manager')
    before = workspace(client)
    response = act(client, 'calendar_update', {field: value}, project=None)
    assert response.status_code == 422
    after = workspace(client)
    assert after['calendar'] == before['calendar']
    assert after['version'] == before['version']


def test_calendar_keeps_deduplicated_dates_and_recalculates(client):
    role(client, 'u-manager')
    response = act(client, 'calendar_update', {'holidays': ['2026-10-09', '2026-10-09'],
                                             'workdays': ['2026-10-10']}, project=None)
    assert response.status_code == 200
    assert response.json()['calendar'] == {'holidays': ['2026-10-09'], 'workdays': ['2026-10-10']}
