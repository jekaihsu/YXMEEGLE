import os, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_TEST_DSN = 'dbname=yongxiang_plumb_r39_clone'
ALLOWED_DATABASES = {'yongxiang_plumb_r39_clone'}


def _verify_not_prod(dsn_val: str) -> str:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    requested = conninfo_to_dict(dsn_val).get('dbname')
    if requested not in ALLOWED_DATABASES:
        raise RuntimeError(f'Only the exact R39 test clone is allowed, got {requested!r}')
    with psycopg.connect(dsn_val) as c:
        current_db = c.execute('SELECT current_database()').fetchone()[0]
    if current_db != 'yongxiang_plumb_r39_clone':
        raise RuntimeError('Unexpected database identity: ' + str(current_db))
    if current_db == 'yongxiang_plumb':
        assert current_db != 'yongxiang_plumb', f"FATAL: Test script forbidden from connecting to production DB yongxiang_plumb (got {current_db})"
        raise RuntimeError("FATAL: current_database() == 'yongxiang_plumb' is strictly forbidden in tests!")
    assert current_db != 'yongxiang_plumb', f"FATAL: Test script forbidden from connecting to production DB yongxiang_plumb (got {current_db})"
    # R41-6 fail-fast: refuse any DB that declares itself production (ALTER DATABASE ... SET app.env='prod').
    with psycopg.connect(dsn_val) as c:
        env = c.execute("SELECT current_setting('app.env', true)").fetchone()[0]
    if env == 'prod':
        raise RuntimeError(f"FATAL: {current_db} has app.env=prod; tests must never run against production")
    return current_db


@pytest.fixture(scope='session', autouse=True)
def _guard_test_session_db():
    dsn_val = os.environ.get('PG_DSN') or DEFAULT_TEST_DSN
    _verify_not_prod(dsn_val)


@pytest.fixture
def dsn():
    value = os.environ.get('PG_DSN') or DEFAULT_TEST_DSN
    _verify_not_prod(value)
    return value


@pytest.fixture
def conn(dsn):
    import psycopg
    with psycopg.connect(dsn) as c:
        current_db = c.execute('SELECT current_database()').fetchone()[0]
        assert current_db != 'yongxiang_plumb', f"FATAL: Test script forbidden from connecting to production DB yongxiang_plumb (got {current_db})"
        try:
            yield c
        finally:
            c.rollback()


def arm_org(conn, org='YX'):
    """Arm only inside the caller's rollback transaction; preserve allocator values."""
    conn.execute("""INSERT INTO org_marker(org_code,kind,value,verified_by)
        SELECT %s,kind,value,'pytest-r43' FROM (VALUES
          ('tax_id','pytest-r43-taxid'),('domain','pytest-r43.invalid')) m(kind,value)
        WHERE NOT EXISTS (SELECT 1 FROM org_marker WHERE org_code=%s AND kind=m.kind)""", (org, org))
    conn.execute("""INSERT INTO serial_cutover_log(org_id,sheet_max,new_next,voided_dry_run)
        SELECT org_id,next_serial-1,next_serial,0 FROM serial_allocator WHERE org_id=%s
        AND NOT EXISTS (SELECT 1 FROM serial_cutover_log WHERE org_id=%s)""", (org, org))
    if conn.execute("SELECT to_regclass('public.org_mode')").fetchone()[0] is not None:
        conn.execute("INSERT INTO org_mode(org_id, mode) VALUES (%s, 'live') ON CONFLICT (org_id) DO UPDATE SET mode='live'", (org,))
    assert conn.execute("SELECT (org_live_ready(%s)->>'ready')::boolean", (org,)).fetchone()[0]
