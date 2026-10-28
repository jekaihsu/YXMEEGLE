import pytest

from .sop_import.domain import Failure
from .test_sop_import import h, URL, post  # noqa: F401
from .test_sop_node_authority import roster


@pytest.mark.parametrize('path', ['/sop-tasks', '/sop-assignees', '/sop-assignees?node_key=pm', '/sop/ensure'])
@pytest.mark.parametrize('reader_grant', [True, False])
def test_cold_roster_recovers_manager_before_read_authorization(h, path, reader_grant):
    post(h, URL + '/sop-tasks', {'title': 'X', 'node_keys': ['pm']})
    h.service.roster_required = True
    h.who[0] = 'member'
    if not reader_grant:
        h.users['member']['capabilities'] = []
    calls = []

    def provider(fresh=False):
        if fresh:
            calls.append(True)
            return roster()
        return None

    h.service.roster_provider = provider
    response = (h.client.post if path.endswith('ensure') else h.client.get)(URL + path)
    assert response.status_code == 200, response.text
    assert calls == [True]
    body = response.json()
    if path == '/sop-tasks':
        assert body['tasks'][0]['can']['manage'] is True
        assert 'edit' in body['tasks'][0]['allowed_actions']
    elif path.endswith('ensure'):
        assert body == {'state': 'not_permitted', 'reason': 'sop_import_forbidden'}
    elif path == '/sop-assignees':
        assert body['restricted'] is False


@pytest.mark.parametrize('path', ['/sop-tasks', '/sop/ensure'])
def test_cold_roster_failure_is_passive_for_reads_and_503_for_ensure(h, path):
    h.service.roster_required = True
    h.who[0] = 'member'
    calls = []

    def provider(fresh=False):
        if fresh:
            calls.append(True)
            raise Failure('roster_unavailable', 503)
        return None

    h.service.roster_provider = provider
    response = (h.client.post if path.endswith('ensure') else h.client.get)(URL + path)
    assert response.status_code == (503 if path.endswith('ensure') else 200)
    if path.endswith('ensure'):
        assert response.json()['code'] == 'roster_unavailable'
    else:
        assert response.json()['allowed_actions']['manage'] is False
    assert calls == [True]


def test_global_manager_cold_reads_do_not_refresh_roster(h):
    h.service.roster_required = True

    def provider(fresh=False):
        assert not fresh
        return None

    h.service.roster_provider = provider
    assert h.client.get(URL + '/sop-tasks').status_code == 200
    assert h.client.get(URL + '/sop-assignees').status_code == 200
    assert h.client.post(URL + '/sop/ensure').json() == {'state': 'started'}
