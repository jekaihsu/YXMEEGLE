import pytest

from .lark_adapter import RemoteFailure
from .remote_policy import FORMAL_BASES, formal_write_allowed, require_formal_write
from .sources import KNOWN_TABLES

V4 = 'H7W6b0PFWaVF1BsgqXJj3pQ9pXb'


def test_only_v4_node_assignment_and_task_tables_are_writable():
    require_formal_write(V4, 'tblcPZPmezkyeVb7')
    require_formal_write(V4, 'tblsoyGcC6K5AipF')


@pytest.mark.parametrize('table', sorted(KNOWN_TABLES[V4]) + ['tblfaCO2xPUNptQH', 'tbl3jzXUO8oyfvcu'])
def test_every_other_v4_table_stays_blocked(table):
    with pytest.raises(RemoteFailure, match='不在正式回寫白名單') as error:
        require_formal_write(V4, table)
    assert error.value.status == 'blocked'


@pytest.mark.parametrize('base', sorted(FORMAL_BASES - {V4}))
def test_the_allowlisted_table_ids_are_bound_to_the_v4_base(base):
    assert formal_write_allowed(base, 'tblcPZPmezkyeVb7') is False
    assert formal_write_allowed(base, 'tblsoyGcC6K5AipF') is False
