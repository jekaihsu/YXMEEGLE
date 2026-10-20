"""Controlled publication. Run with python3 -m backend.sop_import --help."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..models import Base
from .catalog import load_catalog, stage, publish
from .domain import require


def main():
    parser = argparse.ArgumentParser(description='Validate and publish a local SOP catalog. Requires database operator access.')
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--workbook', type=Path, required=True)
    args = parser.parse_args()
    catalog = load_catalog()
    require(hashlib.sha256(args.workbook.read_bytes()).hexdigest() == catalog['source_files'][0]['sha256'],
            'source_workbook_hash_mismatch')
    engine = create_engine(args.database_url)
    Base.metadata.create_all(engine)
    with sessionmaker(engine).begin() as db:
        version = stage(db, args.workspace, args.revision, catalog, source_verified=True)
        publish(db, version, args.actor, time.time())
        print(json.dumps({'version_id': version.id, 'revision': version.revision, 'content_hash': version.content_hash}))


if __name__ == '__main__':
    main()
