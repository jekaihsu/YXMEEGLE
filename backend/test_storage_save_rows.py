"""storage.save copies each record once; the rows must still be what a plain deep copy and pop would give."""
from copy import deepcopy

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from . import storage
from .models import Base, BusinessRow, WorkspaceRow
from .write_world import WID, build_world


def reference_rows(state):
    """The slow, obviously right flattening: deep copy everything, then pop nested lists."""
    root = deepcopy(state); rows = {}
    def add(kind, record, parent='', ordinal=0):
        item = deepcopy(record); rows[(kind, str(item.get('id') or f'{parent}:{ordinal}'))] = (parent, ordinal, item); return item
    for collection in storage.COLLECTIONS:
        for i, record in enumerate(root.pop(collection, [])):
            row = add(collection, record, ordinal=i)
            if collection == 'projects':
                for j, node in enumerate(row.pop('nodes', [])):
                    nr = add('nodes', node, record['id'], j)
                    for k, task in enumerate(nr.pop('tasks', [])): add('tasks', task, node['id'], k)
                    for k, review in enumerate(nr.pop('review_cycles', [])): add('review_cycles', review, node['id'], k)
                for child in storage.PROJECT_CHILDREN:
                    for j, value in enumerate(row.pop(child, [])): add('project_' + child, value, record['id'], j)
    return root, rows


def test_saved_rows_and_root_equal_the_reference_flattening_and_do_not_alias_the_state():
    engine = create_engine('sqlite://'); Base.metadata.create_all(engine)
    world = build_world(6); world['migration_archive'] = {'original': True}
    expected_root, expected_rows = reference_rows({k: v for k, v in world.items() if k != 'migration_archive'})
    with sessionmaker(engine, expire_on_commit=False)() as db:
        row = WorkspaceRow(id=WID, version=1, data={}); db.add(row); db.flush()
        saved_root = storage.save(db, BusinessRow, WID, world)
        db.flush()
        stored = {(r.kind, r.entity_id): (r.parent_id, r.ordinal, r.data) for r in db.scalars(select(BusinessRow)) if r.kind != 'migration_archive'}
        archive = db.get(BusinessRow, (WID, 'migration_archive', 'original'))
        assert archive.data == {'original': True}
        for key, (parent, ordinal, data) in stored.items():
            data.pop('concurrency_version', None) if key[0] == 'projects' else None
        assert {k: (v[0], v[2]) for k, v in stored.items() if k[0] == 'events'} == {k: (v[0], v[2]) for k, v in expected_rows.items() if k[0] == 'events'}
        assert {k: v for k, v in stored.items() if k[0] != 'events'} == {k: v for k, v in expected_rows.items() if k[0] != 'events'}
        assert saved_root['migration_archive_ref'] == 'original' and 'migration_archive' not in saved_root
        assert {k: v for k, v in saved_root.items() if k not in ('storage_schema', 'migration_archive_ref')} == expected_root
        world['projects'][0]['nodes'][0]['tasks'][0]['title'] = 'mutated after save'
        world['settings']['mutated'] = True
        assert db.get(BusinessRow, (WID, 'tasks', world['projects'][0]['nodes'][0]['tasks'][0]['id'])).data['title'] != 'mutated after save'
        assert 'mutated' not in saved_root['settings']
