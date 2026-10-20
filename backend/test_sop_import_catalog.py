from copy import deepcopy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base
from .sop_import.catalog import load_catalog, validate, stage, publish, RAW_FIELDS, digest
from .sop_import.domain import Failure, NODE_MAP
from .sop_import.models import Version, TemplateRow


def test_catalog_raw_fields_and_confirmation_at01_at03():
    catalog = load_catalog()
    assert len(validate(catalog)) == 64
    assert len(catalog['case_sop_rows']) == 62
    assert all(set(r['raw']) == RAW_FIELDS for r in catalog['case_sop_rows'])
    assert [r['raw']['meegle_id'] for r in catalog['case_sop_rows']
            if r['proposed_import']['target_branch_node_keys'] == ['confirmation']] == [19, 59, 60, 61, 22]
    assert catalog['branch_node_key_map'] == NODE_MAP
    assert [r['raw']['meegle_id'] for r in catalog['case_sop_rows']
            if r['proposed_import']['instance_scope'] == 'office_shared'] == [32, 36]


@pytest.mark.parametrize('change', ['field', 'disposition', 'mapping', 'shared', 'key'])
def test_reject_invalid_catalog(change):
    catalog = deepcopy(load_catalog())
    if change == 'field':
        catalog['case_sop_rows'][0]['raw'].pop('unresolved_raw')
    elif change == 'disposition':
        catalog['case_sop_rows'][0]['proposed_import']['disposition'] = 'task'
    elif change == 'mapping':
        catalog['branch_node_key_map']['N01'] = 'pm'
    elif change == 'shared':
        catalog['case_sop_rows'][31]['proposed_import']['candidate_node_keys'] = ['N05']
    else:
        catalog['case_sop_rows'][0]['source_row_key'] = 'changed'
    with pytest.raises(Failure):
        validate(catalog)


def test_publication_requires_verified_source_and_is_immutable(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/catalog.db')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions.begin() as db:
        v = stage(db, 'w', 'r1', load_catalog())
        ident = v.id
        with pytest.raises(Failure, match='source_workbook_not_verified'):
            publish(db, v, 'publisher', 100)
        v.source_verified = True
        publish(db, v, 'publisher', 100)
    with sessions.begin() as db:
        v = db.get(Version, ('w', ident))
        assert v.content_hash == digest(load_catalog())
        assert stage(db, 'w', 'r1', load_catalog()).id == ident
    with pytest.raises(Failure, match='immutable_template_version'):
        with sessions.begin() as db:
            row = db.get(TemplateRow, ('w', ident, 'meegle-v137:A:19'))
            row.snapshot = {**row.snapshot, 'source_locator': 'edited'}
    with pytest.raises(Failure, match='immutable_template_version'):
        with sessions.begin() as db:
            db.get(Version, ('w', ident)).revision = 'edited'
