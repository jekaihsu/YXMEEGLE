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


def validate(catalog, *, baseline=True):
    rows = catalog['case_sop_rows']
    require(len(rows) == 62 if baseline else 1 <= len(rows) <= 2000, 'catalog_row_count_invalid')
    require(catalog['branch_node_key_map'] == NODE_MAP, 'catalog_mapping_invalid')
    counts = Counter(r['proposed_import']['disposition'] for r in rows)
    require(set(counts) <= {d.value for d in Disposition}, 'catalog_dispositions_invalid')
    require(counts == (COUNTS if baseline else catalog['disposition_counts']), 'catalog_dispositions_invalid')
    require(counts['task'] <= 62, 'catalog_row_count_invalid')
    require(len({r['source_row_key'] for r in rows}) == len(rows), 'catalog_origin_invalid')
    numbers = [r['raw']['meegle_id'] for r in rows]
    require(all(type(n) is int and n >= 0 for n in numbers) and len(set(numbers)) == len(rows), 'catalog_origin_invalid')
    locators = [r['source_sheet_row'] for r in rows]
    require(all(type(n) is int and n >= 2 for n in locators) and len(set(locators)) == len(rows), 'catalog_locator_invalid')
    if baseline:
        require(set(numbers) == set(range(62)), 'catalog_origin_invalid')
        require(set(locators) == set(range(2, 64)), 'catalog_locator_invalid')
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
    if baseline:
        require(confirmation == [19, 59, 60, 61, 22], 'catalog_confirmation_invalid')
    return digest(catalog)


def published_family(db, wid, family_id):
    return db.scalar(select(Version.id).where(Version.workspace_id == wid, Version.family_id == family_id,
                                               Version.published_at.is_not(None)).limit(1)) is not None


def stage(db, wid, revision, catalog, *, source_verified=False):
    family_id = catalog['proposed_template_family_id']
    content_hash = validate(catalog, baseline=not published_family(db, wid, family_id))
    name = catalog.get('proposed_template_family_name') or family_id
    family = db.get(Family, (wid, family_id))
    if family is None:
        family = Family(workspace_id=wid, id=family_id, name=name, is_default=True)
        db.add(family)
        db.flush()
    family.name = name
    existing = db.scalar(select(Version).where(Version.workspace_id == wid, Version.family_id == family_id,
                                              Version.revision == revision))
    if existing:
        require(existing.content_hash == content_hash, 'immutable_template_version', 409)
        return existing
    version = Version(workspace_id=wid, id=str(uuid4()), family_id=family_id, revision=revision,
                      mapping_revision=catalog['proposed_mapping_revision'], content_hash=content_hash,
                      source_hash=catalog['source_files'][0]['sha256'], source_verified=source_verified,
                      catalog_manifest={k: v for k, v in catalog.items() if k != 'case_sop_rows'}, status='draft')
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
    catalog = dict(version.catalog_manifest)
    catalog['case_sop_rows'] = [r.snapshot for r in rows]
    catalog['proposed_mapping_revision'] = version.mapping_revision
    version.content_hash = validate(catalog, baseline=not published_family(db, version.workspace_id, version.family_id))
    version.status, version.published_by, version.published_at = 'published', actor_id, at
    return version
