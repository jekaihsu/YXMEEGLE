"""Create the additive AI usage table. DATABASE_URL is required; safe to repeat."""
import argparse
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from backend.ai.ledger import column_ddl, ensure_schema

migrate = ensure_schema
scope_column_ddl = column_ddl


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
