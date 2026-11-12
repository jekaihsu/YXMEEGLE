import pytest

from .ops_sync.testing import STORE_KINDS


def pytest_report_header(config):
    return 'ops_sync stores under test: JsonFileStore, WorkspaceStore(SQLite). WorkspaceStore on PostgreSQL: UNTESTED (not available).'


@pytest.fixture(params=STORE_KINDS)
def store_kind(request):
    """Every ops_sync engine/domain/storage suite using this fixture runs against each real durable OpsStore."""
    return request.param
