"""Create the additive AI usage table. DATABASE_URL is required; safe to repeat."""
import argparse
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect
from sqlalchemy.schema import CreateColumn
from sqlalchemy.engine import make_url
from backend.models import Base
from backend.ai.ledger import AiUsageRow, AiFeedbackRow

TABLES = [AiUsageRow.__table__, AiFeedbackRow.__table__]


def scope_column_ddl(name, dialect):
    column = AiUsageRow.__table__.c[name]
    return 'ALTER TABLE ai_usage ADD COLUMN ' + str(CreateColumn(column).compile(dialect=dialect))


def migrate(engine):
    Base.metadata.create_all(engine, tables=TABLES, checkfirst=True)
    with engine.begin() as connection:
        columns = {c['name'] for c in inspect(connection).get_columns('ai_usage')}
        for name in ('scope', 'project_id'):
            if name not in columns:
                connection.exec_driver_sql(scope_column_ddl(name, connection.dialect))
    for index in AiUsageRow.__table__.indexes:
        index.create(engine, checkfirst=True)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    url = make_url(os.environ['DATABASE_URL'])
    if url.drivername in ('postgres', 'postgresql'):
        url = url.set(drivername='postgresql+psycopg')
    engine = create_engine(url)
    try:
        migrate(engine)
        print('AI usage table verified')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
