import httpx
import pytest

from .sop_import.domain import Failure
from .sop_import.quote_publish import NEVER_WRITE, publish

PROJECT = {'id': 'f' * 32, 'planning_origin': 'local', 'official_quote_no': '115950', 'name': '新竹科學園區地形測量',
           'client': '竹科管理局', 'description': '', 'pm_id': 'ou_pm', 'created_at': '2026-10-20T19:22:33.512+08:00'}
ADMIN = {'id': 'ou_admin', 'role': 'manager', 'active': True, 'capabilities': ['publish_local_quote']}
ON = {'QUOTE_PUBLISH_ENABLED': 'true', 'LARK_QUOTE_BASE_TOKEN': 'quote-base'}


class FakeTable:
    def __init__(self, existing=()):
        self.existing, self.calls = list(existing), []

    def find(self, table, quote_no):
        self.calls.append(('find', table, quote_no))
        return self.existing

    def create(self, table, fields, key):
        self.calls.append(('create', table, fields, key))
        return 'recCreated'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('outbound network is forbidden')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', refuse)


def refused(project=PROJECT, actor=ADMIN, cfg=ON, client=None):
    with pytest.raises(Failure) as caught:
        publish(project, actor=actor, cfg=cfg, client=client)
    return caught.value.code, caught.value.status


@pytest.mark.parametrize('cfg', [{}, {'QUOTE_PUBLISH_ENABLED': 'false'}, {'QUOTE_PUBLISH_ENABLED': 'yes'}])
def test_refuses_unless_explicitly_enabled(cfg):
    table = FakeTable()
    assert refused(cfg=cfg, client=table) == ('quote_publish_disabled', 503)
    assert table.calls == []


def test_refuses_anyone_but_an_admin_holding_the_grant():
    table = FakeTable()
    for actor in ({**ADMIN, 'capabilities': []}, {**ADMIN, 'role': 'pm'}, {**ADMIN, 'active': False}):
        assert refused(actor=actor, client=table) == ('quote_publish_forbidden', 403)
    assert table.calls == []


def test_refuses_without_an_official_number_a_local_case_or_an_injected_client():
    table = FakeTable()
    assert refused(project={**PROJECT, 'official_quote_no': None}, client=table) == ('quote_publish_unready', 409)
    assert refused(project={**PROJECT, 'planning_origin': None}, client=table) == ('quote_publish_unready', 409)
    assert refused(client=None) == ('quote_publish_unready', 409)
    assert table.calls == []


def test_refuses_a_number_the_register_already_holds():
    table = FakeTable(existing=['recOther'])
    assert refused(client=table) == ('quote_number_taken', 409)
    assert table.calls == [('find', ('quote-base', 'tblENZvYAya93Twa'), '115950')]


def test_enabled_admin_run_writes_exactly_the_mapped_fields_through_the_injected_client():
    table = FakeTable()
    result = publish(PROJECT, actor=ADMIN, cfg=ON, client=table)
    fields = {'報價編號': '115950', '工程名稱': '新竹科學園區地形測量', '行號單位': '竹科管理局',
              '案件負責人': [{'id': 'ou_pm'}], '詢價日期': 1792425600000}
    assert result == {'record_id': 'recCreated', 'fields': fields}
    assert table.calls == [('find', ('quote-base', 'tblENZvYAya93Twa'), '115950'),
                           ('create', ('quote-base', 'tblENZvYAya93Twa'), fields, 'local-quote:' + 'f' * 32)]
    assert not NEVER_WRITE & fields.keys()


def test_no_route_reaches_the_adapter(tmp_path):
    from .app import create_app
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/routes.db', 'UPLOAD_DIR': str(tmp_path / 'files'),
                      'SESSION_SECRET': 'routes-only' * 4, 'APP_ENV': 'development', 'DEMO_MODE': 'true',
                      'QUOTE_PUBLISH_ENABLED': 'true', 'LOCAL_CASE_CREATION_ENABLED': 'true'})
    quote_routes = sorted(f"{sorted(r.methods)[0]} {r.path}" for r in app.routes if r.path.startswith('/api/quotes'))
    assert quote_routes == ['GET /api/quotes', 'GET /api/quotes/requests/{request_id}', 'GET /api/quotes/{quote_no}',
                            'POST /api/quotes', 'POST /api/quotes/preview']
    app.state.engine.dispose()
