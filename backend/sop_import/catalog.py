import hashlib
import json
from collections import Counter
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from .domain import Disposition, NODE_MAP, require
from .models import Family, Version, TemplateRow

RAW_FIELDS = {'source_group', 'source_order', 'meegle_id', 'title', 'source_kind', 'owner_role_raw',
              'trigger_raw', 'anchor_raw', 'deadline_raw', 'inputs_raw', 'procedure_raw', 'human_decision_raw',
              'outputs_raw', 'done_when_raw', 'next_raw', 'escalation_raw', 'kpi_raw', 'source_reference_raw',
              'applicability_raw', 'unresolved_raw', 'version_note_raw'}
COUNTS = {'task': 44, 'routing_reference': 13, 'review_required': 1,
          'routine_excluded': 2, 'disabled_excluded': 2}
SPECIAL = {42: 'review_required', 27: 'routine_excluded', 57: 'routine_excluded',
           28: 'disabled_excluded', 58: 'disabled_excluded'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def load_catalog():
    with Path(__file__).with_name('catalog.json').open() as source:
        return json.load(source)


def validate(catalog):
    rows = catalog['case_sop_rows']
    require(len(rows) == 62, 'catalog_row_count_invalid')
    require(catalog['branch_node_key_map'] == NODE_MAP, 'catalog_mapping_invalid')
    require(Counter(r['proposed_import']['disposition'] for r in rows) == COUNTS, 'catalog_dispositions_invalid')
    require(len({r['source_row_key'] for r in rows}) == 62, 'catalog_origin_invalid')
    require({r['raw']['meegle_id'] for r in rows} == set(range(62)), 'catalog_origin_invalid')
    require({r['source_sheet_row'] for r in rows} == set(range(2, 64)), 'catalog_locator_invalid')
    for row in rows:
        raw, proposal = row['raw'], row['proposed_import']
        require(set(raw) == RAW_FIELDS, 'catalog_fields_invalid')
        require(all(v is None or type(v) in (str, int) for v in raw.values()), 'catalog_fields_invalid')
        require(type(raw['title']) is str and 1 <= len(raw['title']) <= 500, 'catalog_title_invalid')
        require(all(not isinstance(v, str) or len(v) <= 20000 for v in raw.values()), 'catalog_fields_invalid')
        number = raw['meegle_id']
        require(row['source_row_key'] == f'meegle-v137:A:{number}', 'catalog_origin_invalid')
        require(proposal['disposition'] == SPECIAL.get(number, proposal['disposition']), 'catalog_dispositions_invalid')
        keys = proposal['candidate_node_keys']
        require(len(keys) == len(set(keys)) and set(keys) <= NODE_MAP.keys(), 'catalog_mapping_invalid')
        require(proposal['target_branch_node_keys'] == [NODE_MAP[k] for k in keys], 'catalog_mapping_invalid')
        require(bool(keys) or number in {27, 57, 28, 58}, 'catalog_mapping_invalid')
        require(proposal['instance_scope'] == ('office_shared' if number in {32, 36} else 'case'), 'catalog_scope_invalid')
        if number in {32, 36}:
            require(keys == ['N05', 'N06', 'N07'], 'catalog_mapping_invalid')
    confirmation = [r['raw']['meegle_id'] for r in rows if r['proposed_import']['candidate_node_keys'] == ['N03']]
    require(confirmation == [19, 59, 60, 61, 22], 'catalog_confirmation_invalid')
    return digest(catalog)


def stage(db, wid, revision, catalog, *, source_verified=False):
    content_hash = validate(catalog)
    family_id = catalog['proposed_template_family_id']
    family = db.get(Family, (wid, family_id))
    if family is None:
        family = Family(workspace_id=wid, id=family_id, name='Plumb case SOP', is_default=True)
        db.add(family)
        db.flush()
    existing = db.scalar(select(Version).where(Version.workspace_id == wid, Version.family_id == family_id,
                                              Version.revision == revision))
    if existing:
        require(existing.content_hash == content_hash, 'immutable_template_version', 409)
        return existing
    version = Version(workspace_id=wid, id=str(uuid4()), family_id=family_id, revision=revision,
                      mapping_revision=catalog['proposed_mapping_revision'], content_hash=content_hash,
                      source_hash=catalog['source_files'][0]['sha256'], source_verified=source_verified, status='draft')
    db.add(version)
    db.flush()
    for ordinal, row in enumerate(catalog['case_sop_rows']):
        db.add(TemplateRow(workspace_id=wid, version_id=version.id, source_row_key=row['source_row_key'],
                           ordinal=ordinal, disposition=Disposition(row['proposed_import']['disposition']), snapshot=row))
    db.flush()
    return version


def publish(db, version, actor_id, at):
    require(version.source_verified, 'source_workbook_not_verified')
    require(version.status in {'draft', 'published'}, 'template_unavailable', 409)
    if version.status == 'published':
        return version
    rows = list(db.scalars(select(TemplateRow).where(TemplateRow.workspace_id == version.workspace_id,
                                                   TemplateRow.version_id == version.id).order_by(TemplateRow.ordinal)))
    catalog = load_catalog()
    catalog['case_sop_rows'] = [r.snapshot for r in rows]
    catalog['proposed_mapping_revision'] = version.mapping_revision
    version.content_hash = validate(catalog)
    version.status, version.published_by, version.published_at = 'published', actor_id, at
    return version
