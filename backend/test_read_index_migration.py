"""Run Postgres coverage only against an explicitly supplied disposable server."""
import json
import os
import uuid

import pytest
from sqlalchemy import cast, create_engine, event, inspect, select, Text
from sqlalchemy.orm import Session

from backend.models import Base, BusinessRow, WorkspaceRow
from backend.partial_reads import load_partial
from backend.read_index_migration import ensure_read_indexes, INDEX_NAME, INDEX_COLUMNS


@pytest.fixture(params=('sqlite', 'postgresql'))
def engine(request, tmp_path):
    if request.param == 'sqlite':
        engine = create_engine('sqlite:///' + str(tmp_path / 'existing.db'))
        yield engine
        engine.dispose()
        return
    url = os.environ.get('U2H_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('U2H_TEST_POSTGRES_URL not supplied; PostgreSQL integration unverified')
    schema = 'u2h_' + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA {schema}')
    engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        admin.dispose()


def snapshot(connection):
    return connection.execute(select(BusinessRow.workspace_id, BusinessRow.kind,
        BusinessRow.entity_id, BusinessRow.parent_id, BusinessRow.ordinal,
        cast(BusinessRow.data, Text)).order_by(BusinessRow.workspace_id,
        BusinessRow.kind, BusinessRow.entity_id)).all()


def test_existing_populated_database_twice_and_exact_reader_sql(engine):
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'DROP INDEX {INDEX_NAME}')
        connection.execute(WorkspaceRow.__table__.insert(), [dict(id='w', version=7,
            data={'storage_schema': 2, 'sentinel': 'unchanged'})])
        connection.execute(BusinessRow.__table__.insert(), [dict(workspace_id='w',
            kind='users' if i < 65 else 'projects', entity_id=f'r{i}', parent_id='',
            ordinal=i, data={'id': f'r{i}', 'name': 'preserve 原始值'}) for i in range(2000)])
        before = snapshot(connection)
    captured = []
    def capture(connection, cursor, statement, parameters, context, many):
        if statement.startswith('SELECT business_records.kind'):
            captured.append((statement, parameters))
    event.listen(engine, 'before_cursor_execute', capture)
    def read():
        with Session(engine) as db:
            return load_partial(db, BusinessRow, db.get(WorkspaceRow, 'w'), collections=('users',))
    old_result = read()
    ensure_read_indexes(engine)
    ensure_read_indexes(engine)
    assert read() == old_result
    assert len(old_result['users']) == 65
    assert len(captured) == 2 and captured[0] == captured[1]
    with engine.connect() as connection:
        assert snapshot(connection) == before
        assert connection.execute(select(WorkspaceRow.version, WorkspaceRow.data)).one() == (
            7, {'storage_schema': 2, 'sentinel': 'unchanged'})
        index = next(i for i in inspect(connection).get_indexes('business_records') if i['name'] == INDEX_NAME)
        assert tuple(index['column_names']) == INDEX_COLUMNS
        if engine.dialect.name == 'sqlite':
            sql, params = captured[-1]
            plan = connection.exec_driver_sql('EXPLAIN QUERY PLAN ' + sql, params).all()
            assert INDEX_NAME in str(plan)
            assert 'TEMP B-TREE' not in str(plan)
        else:
            assert connection.exec_driver_sql(
                'SELECT indisvalid AND indisready FROM pg_index WHERE indexrelid=to_regclass(%s)',
                (INDEX_NAME,)).scalar() is True
    event.remove(engine, 'before_cursor_execute', capture)


def test_new_database_declaration_and_existing_index_are_safe(engine):
    Base.metadata.create_all(engine)
    ensure_read_indexes(engine)
    ensure_read_indexes(engine)


def test_wrong_named_index_is_rejected(engine):
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'DROP INDEX {INDEX_NAME}')
        connection.exec_driver_sql(f'CREATE INDEX {INDEX_NAME} ON business_records(ordinal)')
    with pytest.raises(RuntimeError, match='unexpected index definition'):
        ensure_read_indexes(engine)


def test_full_and_case_read_parity_with_ordinal_ties(engine):
    from backend import storage
    from backend.perf_fixture import build_scaled_workspace
    from backend.policy import upgrade
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'DROP INDEX {INDEX_NAME}')
    with Session(engine) as db:
        db.add(WorkspaceRow(id='w', version=3, data={}))
        db.flush()
        root = storage.save(db, BusinessRow, 'w', upgrade(build_scaled_workspace(6)))
        db.get(WorkspaceRow, 'w').data = root
        db.commit()
    def read():
        with Session(engine, info={'shared_reads_wids': {'w'}}) as db:
            row = db.get(WorkspaceRow, 'w')
            full = storage.load(db, BusinessRow, row)
            partial = load_partial(db, BusinessRow, row, collections=storage.CASE_DETAIL_COLLECTIONS,
                project_ids=(full['projects'][0]['id'],), project_children=storage.PROJECT_CHILDREN,
                filter_project_rows=True)
            return full, partial
    before = read()
    ensure_read_indexes(engine)
    assert read() == before


def test_partial_named_index_is_rejected(engine):
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'DROP INDEX {INDEX_NAME}')
        connection.exec_driver_sql(f'CREATE INDEX {INDEX_NAME} ON business_records'
            '(workspace_id, kind, parent_id, ordinal) WHERE ordinal > 100')
    with pytest.raises(RuntimeError, match='unexpected index definition'):
        ensure_read_indexes(engine)


def test_sqlite_bound_json_path_counterexample(tmp_path):
    """A literal-path expression-index gain cannot be claimed for the actual reader."""
    engine = create_engine('sqlite:///' + str(tmp_path / 'json.db'))
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP INDEX {INDEX_NAME}')
            connection.execute(WorkspaceRow.__table__.insert(), dict(id='w', version=0, data={}))
            connection.execute(BusinessRow.__table__.insert(), [dict(workspace_id='w',
                kind='source_work_items', entity_id=str(i), parent_id='', ordinal=i,
                data={'id': str(i), 'project_id': f'p{i % 100}'}) for i in range(2000)])
            connection.exec_driver_sql("CREATE INDEX json_probe ON business_records"
                "(workspace_id,kind,CAST(JSON_EXTRACT(data,'$.\"project_id\"') AS VARCHAR),ordinal)")
            query = select(BusinessRow.data).where(BusinessRow.workspace_id == 'w',
                BusinessRow.kind == 'source_work_items',
                BusinessRow.data['project_id'].as_string().in_(('p1',))).order_by(BusinessRow.ordinal).limit(201)
            captured = []
            def capture(conn, cur, sql, params, ctx, many):
                captured.append((sql, params))
            event.listen(connection, 'before_cursor_execute', capture)
            rows = connection.execute(query).all()
            event.remove(connection, 'before_cursor_execute', capture)
            sql, params = captured[0]
            assert params[2] == '$."project_id"'
            bound_plan = connection.exec_driver_sql('EXPLAIN QUERY PLAN ' + sql, params).all()
            assert 'TEMP B-TREE' in str(bound_plan)
            literal_sql = sql.replace('JSON_EXTRACT(business_records.data, ?)',
                'JSON_EXTRACT(business_records.data, \'$."project_id"\')')
            literal_params = params[:2] + params[3:]
            literal_plan = connection.exec_driver_sql('EXPLAIN QUERY PLAN ' + literal_sql, literal_params).all()
            assert 'TEMP B-TREE' not in str(literal_plan)
            assert [json.loads(r[0]) for r in connection.exec_driver_sql(literal_sql, literal_params)] == [r[0] for r in rows]
            assert len(rows) == 20
    finally:
        engine.dispose()
