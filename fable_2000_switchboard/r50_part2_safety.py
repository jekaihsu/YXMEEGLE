"""Clone-only connections. No network transport other than local PostgreSQL."""
import os
import psycopg
from psycopg.rows import dict_row

DATABASE = "yongxiang_plumb_r39_clone"
ENV = dict(PGHOST="127.0.0.1", PGPORT="5432", PGUSER="postgres",
           PGPASSWORD="postgres", PGDATABASE=DATABASE, SMTP_DISABLED="1",
           SWITCHBOARD_SANDBOX_MODE="SANDBOX_LOOPBACK")
os.environ.update(ENV)
DSN = "host=127.0.0.1 port=5432 user=postgres password=postgres dbname=" + DATABASE


def connect(*, autocommit=True, name="r50_part2", timeout="3s"):
    conn = psycopg.connect(DSN, autocommit=autocommit, row_factory=dict_row,
                           options=f"-c application_name={name} -c lock_timeout={timeout} -c statement_timeout=30000 -c plpgsql.check_asserts=on")
    db = conn.execute("SELECT current_database() AS db").fetchone()["db"]
    assert db == DATABASE
    assert db != "yongxiang_plumb"
    return conn
