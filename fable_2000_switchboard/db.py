"""僅操作本機 PostgreSQL；參數不經 shell，沒有外部傳送介面。支援 Linux psql 與 Windows psycopg 雙引擎。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading

ROOT = Path(__file__).resolve().parent
DATABASE = 'postgresql://postgres:postgres@127.0.0.1:5432/yongxiang_plumb_r39_clone'
HAS_PSQL = shutil.which('psql') is not None
_SESSION_CONTEXT = threading.local()


def set_session_digest(digest=None):
    if digest is not None and (len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)):
        raise ValueError('Invalid session digest')
    _SESSION_CONTEXT.digest = digest

try:
    import psycopg
except Exception:
    psycopg = None


def _require_clone_target(target):
    if str(target) not in ('yongxiang_plumb_r39_clone', DATABASE):
        raise ValueError('Only the exact local yongxiang_plumb_r39_clone is permitted')
    return DATABASE


def _pg_conn_str(target=None):
    return _require_clone_target(target if target is not None else DATABASE)


_VERIFIED_TARGETS = {}

def assert_not_prod_db(target=None):
    db_target = _require_clone_target(target if target is not None else DATABASE)
    assert 'yongxiang_plumb' not in db_target or 'clone' in db_target, (
        f"FATAL: Test script forbidden from connecting to production DB yongxiang_plumb (got {db_target})"
    )
    if db_target in _VERIFIED_TARGETS:
        return _VERIFIED_TARGETS[db_target]
    if HAS_PSQL:
        proc = subprocess.run(
            ['psql', '-X', '-d', _pg_conn_str(db_target), '-v', 'ON_ERROR_STOP=1', '-Atqc', 'SELECT current_database()'],
            text=True, encoding='utf-8', capture_output=True
        )
        if proc.returncode:
            raise RuntimeError(proc.stderr.strip())
        current_db = proc.stdout.strip()
    elif psycopg is not None:
        with psycopg.connect(_pg_conn_str(db_target), autocommit=True) as conn:
            current_db = str(conn.execute('SELECT current_database()').fetchone()[0]).strip()
    else:
        raise RuntimeError('Neither psql nor psycopg is available')
    assert current_db != 'yongxiang_plumb', (
        f"FATAL: Test script forbidden from connecting to production DB yongxiang_plumb (got {current_db})"
    )
    assert current_db == 'yongxiang_plumb_r39_clone'
    _VERIFIED_TARGETS[db_target] = current_db
    return current_db


def literal(value):
    if value is None:
        return 'NULL'
    return "'" + str(value).replace("'", "''") + "'"


def json_sql(value):
    return literal(json.dumps(value, ensure_ascii=False)) + '::jsonb'


def execute(sql):
    assert_not_prod_db(DATABASE)
    digest = getattr(_SESSION_CONTEXT, 'digest', None)
    if digest:
        sql = 'SET app.r47_session_sha256=' + literal(digest) + ';\n' + sql
    sql = "SET plpgsql.check_asserts=on; DO $$ BEGIN ASSERT current_database() != 'yongxiang_plumb'; ASSERT current_database()='yongxiang_plumb_r39_clone'; END $$;\n" + sql
    if HAS_PSQL:
        process = subprocess.run(
            ['psql', '-X', '-d', _pg_conn_str(DATABASE), '-v', 'ON_ERROR_STOP=1', '-Atq'],
            input=sql, text=True, encoding='utf-8', capture_output=True
        )
        if process.returncode:
            raise RuntimeError(process.stderr.strip())
        return process.stdout
    if psycopg is not None:
        clean_sql = '\n'.join(line for line in sql.splitlines() if not line.lstrip().startswith('\\'))
        with psycopg.connect(_pg_conn_str(DATABASE), autocommit=True) as conn:
            res = conn.pgconn.exec_(clean_sql.encode('utf-8'))
            status = res.status
            # 1 = COMMAND_OK, 2 = TUPLES_OK
            if status not in (1, 2):
                err = res.error_message.decode('utf-8', errors='replace') if res.error_message else f'PQexec status {status}'
                raise RuntimeError(err.strip())
            if status == 2:
                lines = []
                for r in range(res.ntuples):
                    cols = []
                    for c in range(res.nfields):
                        v = res.get_value(r, c)
                        cols.append('' if v is None else v.decode('utf-8', errors='replace'))
                    lines.append('|'.join(cols))
                return '\n'.join(lines) + ('\n' if lines else '')
            return ''
    raise RuntimeError('Neither psql nor psycopg is available')


def query(sql):
    return [json.loads(line) for line in execute(sql).splitlines() if line.strip()]


def apply():
    execute((ROOT / 'sql/switchboard.sql').read_text(encoding='utf-8'))
    overlay = ROOT / 'sql/010_guard_constants.sql'
    if overlay.exists():
        execute(overlay.read_text(encoding='utf-8'))


def snapshot():
    """定義、欄位、ACL、擁有者與資料集合雜湊；不輸出任何薪酬原文。"""
    objects = query("""SELECT jsonb_build_object('schema',n.nspname,'name',c.relname,
      'kind',c.relkind,'owner',pg_get_userbyid(c.relowner),'acl',c.relacl,
      'definition',CASE WHEN c.relkind='v' THEN pg_get_viewdef(c.oid,true) ELSE NULL END,
      'columns',(SELECT jsonb_agg(jsonb_build_object('name',a.attname,'type',
        format_type(a.atttypid,a.atttypmod),'not_null',a.attnotnull) ORDER BY a.attnum)
        FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped))
      FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname IN ('dim','fact') ORDER BY n.nspname,c.relname""")
    for obj in objects:
        name = '"' + obj['schema'] + '"."' + obj['name'].replace('"', '""') + '"'
        obj['data'] = query(f"""SELECT jsonb_build_object('count',count(*),'md5',
          md5(coalesce(string_agg(to_jsonb(t)::text,E'\n' ORDER BY to_jsonb(t)::text),'')))
          FROM {name} t""")[0]
    return objects


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
