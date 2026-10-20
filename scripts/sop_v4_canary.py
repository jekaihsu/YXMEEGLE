"""Operator-only canary. No remote writes occur without --yes and production gates."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from backend import storage
from backend.models import Base, WorkspaceRow, BusinessRow
from backend.sop_import.models import CaseState, LocalTask, TaskNodeLink, LarkOutbox
from backend.sop_import.domain import Applicability, Lifecycle
from backend.sop_import.lark_projection import Projection, ProjectionClient, Table, check_schema, gates, drain_lock

PROJECT = 'SRC-TEST-SOPV4-20261021'
TASKS = ('sop-v4-canary-case', 'sop-v4-canary-shared32', 'sop-v4-canary-archived')


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--yes', action='store_true')
    parser.add_argument('--cleanup', action='store_true')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--database-url', default=os.environ.get('DATABASE_URL'), required=not os.environ.get('DATABASE_URL'))
    args = parser.parse_args()
    if not args.yes:
        parser.error('Explicit --yes is required. This command writes to the dedicated SOP任務 table.')
    cfg = dict(os.environ)
    wid = 'lark-' + cfg.get('LARK_WORKER_ORGANIZATION', '')
    sessions = sessionmaker(create_engine(args.database_url), expire_on_commit=False)
    def load(workspace):
        with sessions() as db:
            return storage.load(db, BusinessRow, db.get(WorkspaceRow, workspace))
    if not gates(cfg, wid, load(wid)):
        parser.error('Production workspace, application identity, external_enabled and SOP_LARK_PROJECTION_ENABLED are required.')
    worker = Projection(sessions, cfg, load)
    if args.cleanup:
        manifest = json.loads(args.manifest.read_text())
        check(manifest['project_id'] == PROJECT and manifest['workspace_id'] == wid, 'Manifest identifies another case or workspace')
        recorded = set(manifest['record_ids'])
        check(len(recorded) == len(manifest['record_ids']) <= 3 and all(r.startswith('rec') for r in recorded), 'Invalid canary receipt IDs')
        with drain_lock(sessions.kw['bind']) as acquired, ProjectionClient(cfg, before_write=lambda: worker.before_write(wid, PROJECT)) as client:
            check(acquired, 'Projection drain is active. Retry cleanup after it finishes.')
            check_schema(client)
            found = client.search_value('專案編號', PROJECT)
            check({r['record_id'] for r in found} == recorded and len(found) == len(recorded), 'Cleanup scope differs from manifest')
            with sessions.begin() as db:
                for row in worker.current_rows(db, wid, PROJECT):
                    row.state, row.last_error = 'paused', 'canary_cleanup'
            for rid in sorted(recorded):
                client._call('DELETE', client._root(Table.TASKS) + '/records/' + rid, write=True)
        print(f'Deleted only the {len(recorded)} recorded canary rows. Local canary outbox remains paused.')
        return
    if args.manifest.exists():
        parser.error('Manifest exists. Inspect or clean up that run before starting another.')
    with sessions.begin() as db:
        check(db.get(BusinessRow, (wid, 'projects', PROJECT)) is None, 'Canary case already exists')
        db.add(BusinessRow(workspace_id=wid, kind='projects', entity_id=PROJECT, parent_id='', ordinal=999999,
                           data={'id': PROJECT, 'code': PROJECT, 'name': 'SOP V4 canary', 'case_type': 'intake',
                                 'case_visibility': 'source_reference', 'source_kind': 'lark'}))
        db.add(CaseState(workspace_id=wid, project_id=PROJECT))
        db.flush()
        for index, tid in enumerate(TASKS):
            db.add(LocalTask(workspace_id=wid, project_id=PROJECT, id=tid, template_family_id='canary',
                             source_row_key='meegle-v137:A:32' if index == 1 else tid,
                             instance_scope='office_shared' if index == 1 else 'case', snapshot={},
                             title=('Canary case task', 'Canary shared #32', 'Canary archived task')[index],
                             instructions='', participants={}, applicability=Applicability.APPLICABLE,
                             state=Lifecycle.ARCHIVED if index == 2 else Lifecycle.PENDING, revision=1, local={}))
            db.flush()
            for ordinal, key in enumerate(('control', 'mapping', 'report') if index == 1 else ('sales',)):
                db.add(TaskNodeLink(workspace_id=wid, project_id=PROJECT, task_id=tid, node_id=PROJECT + '-' + key,
                                    node_key=key, ordinal=ordinal))
    worker.drain(project_id=PROJECT)
    with ProjectionClient(cfg) as client:
        records = client.search_value('專案編號', PROJECT)
        ids = [r['record_id'] for r in records]
        # Save receipts before verification so a failed check still leaves an exact cleanup scope.
        args.manifest.write_text(json.dumps({'workspace_id': wid, 'project_id': PROJECT, 'record_ids': ids}, indent=2))
        check(len(records) == 3 and len(set(ids)) == 3, 'Expected exactly three canary rows')
        shared = next(r['fields'] for r in records if r['fields']['來源列'] == 'meegle-v137:A:32')
        check(set(shared['節點']) == {'控制', '圖資', '報告'} and shared['共用'] is True, 'Shared task projection differs')
        check(sum(r['fields']['狀態'] == '已封存' for r in records) == 1, 'Archived task projection differs')
    with sessions.begin() as db:
        for row in worker.current_rows(db, wid, PROJECT):
            row.state, row.record_id, row.retry_at = 'sent', None, 0
    worker.drain(project_id=PROJECT)
    with ProjectionClient(cfg) as client:
        after = client.search_value('專案編號', PROJECT)
        check(len(after) == 3 and {r['record_id'] for r in after} == set(ids), 'Resend produced another row')
    print('Verified three rows and forced resend without a fourth row.')
    print(f'Cleanup: {sys.executable} scripts/sop_v4_canary.py --yes --cleanup --manifest {args.manifest}')


if __name__ == '__main__':
    main()
