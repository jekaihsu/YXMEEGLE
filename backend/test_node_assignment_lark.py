import httpx
import pytest

from .live_read.token_cache import TenantTokenCache
from .node_assignment.config import NodeAssignmentConfig
from .node_assignment.domain import NodeKey
from .node_assignment.errors import Failure
from .node_assignment.lark_table import BitableClient, Table
from .node_assignment.roster import parse_roster

CFG = {'LARK_WORKER_IDENTITY': 'application', 'LARK_APP_ID': 'a', 'LARK_APP_SECRET': 'b', 'LARK_WORKER_ORGANIZATION': 'c'}


class NoBucket:
    def acquire(self, deadline):
        pass


def test_only_allowlisted_tables_are_written_by_the_client():
    calls = []
    config = NodeAssignmentConfig(enabled=True, node_table='tblmSQrcCs9vPQZx')
    client = BitableClient(CFG, config, httpx.MockTransport(calls.append), token_cache=TenantTokenCache(), bucket=NoBucket())
    for write in (lambda: client.create(Table.NODES, {'指派鍵': 'x'}, 'token'),
                  lambda: client.update(Table.NODES, 'rec1', {'狀態': '已完成'}),
                  lambda: client.create(Table.PEOPLE, {'姓名': 'x'}, 'token')):
        with pytest.raises(Failure) as error:
            write()
        assert (error.value.code, error.value.message) == ('writes_disabled', '此 Base 資料表不在正式回寫白名單，禁止寫入')
    assert calls == [] and config.writable is False


def test_default_and_environment_configuration():
    assert NodeAssignmentConfig().writable is True
    config = NodeAssignmentConfig.from_env({'NODE_ASSIGNMENT_ENABLED': 'TRUE', 'NODE_ASSIGNMENT_TASK_TABLE_ID': '../x',
                                            'NODE_ASSIGNMENT_READ_TTL_SECONDS': 'nan', 'NODE_ASSIGNMENT_ROSTER_TTL_SECONDS': '5'})
    assert (config.enabled, config.task_table, config.read_ttl_seconds, config.roster_ttl_seconds) == (
        True, 'tblsoyGcC6K5AipF', 60, 30)


def row(open_id, name, groups, rank, employed=True):
    return {'record_id': 'rec' + open_id, 'fields': {'姓名': name, '所屬組別': groups, '職級': rank, '在職': employed,
                                                     'Lark帳號': [{'id': open_id, 'name': name}]}}


def test_roster_excludes_ambiguous_accounts_and_keeps_departed_people_unassignable():
    roster = parse_roster([row('ou_a', '甲', ['外業'], '經理'), row('ou_a', '甲二', ['行政'], '老闆'),
                           row('ou_b', '乙', ['外業', '水深A'], '組員'), row('ou_c', '丙', ['外業'], '組員', False),
                           {'record_id': 'recx', 'fields': {'姓名': '無帳號'}}])
    assert roster.ambiguous == frozenset({'ou_a'}) and roster.person('ou_a') is None
    assert [roster.public(p, NodeKey.FIELD) for p in roster.assignable(NodeKey.FIELD)] == [
        {'open_id': 'ou_b', 'name': '乙', 'departments': ['外業', '水深A']}]
    assert roster.person('ou_c').employed is False


def test_roster_reads_a_single_select_department_field():
    roster = parse_roster([row('ou_a', '甲', '外業', '經理'), row('ou_b', '乙', ['PM'], '組員')])
    assert roster.people['ou_a'].departments == frozenset({'外業'})
    assert roster.people['ou_b'].departments == frozenset({'PM'})


def test_people_schema_accepts_single_and_multi_select_departments():
    from backend.node_assignment.lark_table import LARK_TYPES, Kind
    assert LARK_TYPES[Kind.MULTI] == {3, 4}


def test_roster_rejects_columns_it_did_not_ask_for():
    with pytest.raises(Failure, match='未要求的欄位'):
        parse_roster([{'record_id': 'r', 'fields': {'姓名': '甲', '薪資': 1}}])
