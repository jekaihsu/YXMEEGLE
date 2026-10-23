"""Unwired contract-line read model over an already authorized workspace.

There is one native contract-item entity, not a separate contract header
(source_entities.KINDS). Quantities, units, formal revisions and source ordering
are not established by the existing projection. Never recover stripped fields
from raw records, task snapshots or approval requests. ``as_of`` is reserved for
the caller's read context; it does not select a historical effective version.
"""
from dataclasses import asdict

from .data_state import data_state
from .source_identity import SourceRef, is_source_key
from .sources import FIELDS


def _unknown(reason):
    return {'state': 'unknown', 'reason': reason}


def _amount():
    return {'state': 'withheld', 'reason': 'G-AMT: contract amount display is not approved'}


def _text(value):
    return value if isinstance(value, str) and value else None


def _reference(row, version=None):
    origin = row.get('source_identity')
    if origin is None and is_source_key(row.get('id')):
        base, table, record = row['id'].split('/')
        origin = dict(base_token=base, table_id=table, record_id=record)
    try:
        ref = SourceRef.from_entity(origin or {}, version=version)
    except (ValueError, TypeError):
        return None
    if ref.source_key != row.get('id'):
        return None
    return {**asdict(ref), 'version_key': list(ref.version_key)}


def _unique(rows):
    """Dedupe source grain before any edge join; labels never form identity."""
    result = {}
    for row in rows:
        if _reference(row) is not None:
            result.setdefault(row['id'], row)
    return result


def _fields(row):
    # Existing allowlist, restricted further to scalar non-relational evidence.
    # Link fields are represented only by references to present authorized rows.
    excluded = {'分項金額(原始)', '分項金額(報出)', '所屬案件',
                '所屬成案確認單（日報關聯）', '控制工項', '圖資工項', '報告工項'}
    return {key: value for key, value in (row.get('fields') or {}).items()
            if key in FIELDS['contract'] and key not in excluded
            and type(value) in (str, int, float, bool) and value is not None}


def _line(row, version=None):
    return {'section_state': data_state('partial'), 'identity': _reference(row, version),
            'line_number': _text(row.get('item_number')),
            'name': _text(row.get('title')),
            'quantity': _unknown('quantity field unlocated'),
            'unit': _unknown('unit field unlocated'),
            'original_amount': _amount(), 'current_revised_amount': _amount(),
            'revision_reason': _unknown('formal revision reason unlocated')}


def _directory(row):
    return {'identity': _reference(row, row.get('revision')),
            'line_number': _text(row.get('item_number')), 'name': _text(row.get('title'))}


def build_contract_detail(state, contract_key, *, as_of=None):
    """Pure projection; input must already pass admission, allowlists and redaction.

    Absent rows are unlocated, with no echo of the requested key or hidden links.
    Version history describes observed source snapshots, not approved business
    revisions or VCC-122's unexplained differences. No aggregate is calculated.
    """
    contracts = _unique(state.get('contract_items') or [])
    contract = contracts.get(contract_key) if isinstance(contract_key, str) else None
    if contract is None or _reference(contract, contract.get('revision')) is None:
        return {'page_state': data_state('unlocated')}
    confirmations = _unique(state.get('source_confirmations') or [])
    parents = [confirmations[key] for key in sorted(set(contract.get('confirmation_ids') or []))
               if key in confirmations]
    parent_rows = [{'identity': _reference(row, row.get('revision')),
                    'reference': _text(row.get('code'))} for row in parents]
    parent_keys = {row['id'] for row in parents}
    siblings = [_directory(row) for key, row in sorted(contracts.items())
                if key != contract_key and parent_keys.intersection(row.get('confirmation_ids') or [])]
    items = _unique(state.get('source_work_items') or [])
    children = [{'identity': _reference(row), 'name': _unknown('work-item name unlocated'),
                 'category': _text(row.get('category')),
                 'quantity': _unknown('quantity field unlocated'),
                 'unit': _unknown('unit field unlocated'),
                 'state': _unknown('work-item state unlocated'),
                 'responsible_person': _unknown('responsible person unlocated'),
                 'deliverable_count': _unknown('deliverable population unlocated')}
                for key, row in sorted(items.items()) if contract_key in (row.get('contract_ids') or [])]
    status = (state.get('source_work_items_status') or {}).get(contract.get('project_id')) or {}
    complete_children = (status.get('partial') is False and not status.get('truncated')
                         and contract_key not in (status.get('incomplete_contract_ids') or [])
                         and not any(row.get('source_missing') for row in items.values()
                                     if contract_key in (row.get('contract_ids') or [])))
    child_state = (data_state('partial', count=len(children)) if children else
                   data_state('complete_empty') if complete_children else data_state('unknown'))
    observations = []
    for entry in contract.get('history') or []:
        snapshot = entry.get('snapshot') or {}
        # Never import a different record's history into this line.
        version = entry.get('revision')
        if snapshot.get('id') != contract_key or _reference(snapshot, version) is None:
            continue
        observations.append({'kind': 'observed_source_snapshot',
                             'line': _line(snapshot, version), 'source_fields': _fields(snapshot)})
    warnings = ['receipt_missing', 'separate_contract_header_unlocated',
                'quantity_unit_unlocated', 'formal_revision_semantics_unlocated',
                'original_source_order_unlocated']
    if not parents:
        warnings.append('parent_unresolved')
    if contract.get('source_missing'):
        warnings.append('retained_source_missing')
    return {
        'page_state': data_state('partial', 'stale') if contract.get('source_missing') else data_state('partial'),
        'header': {**_directory(contract), 'section_state': data_state('partial'),
                   'source': _reference(contract, contract.get('revision')),
                   'parent_confirmations': parent_rows,
                   'parent_state': data_state('partial') if parents else data_state('unlocated'),
                   'edge_verification': 'receipt_missing'},
        'siblings': {'state': data_state('partial') if siblings else data_state('unknown'), 'rows': siblings},
        'main': _line(contract, contract.get('revision')),
        'work_items': {'state': child_state, 'rows': children,
                       'order': 'stable_source_id; original_source_order_unlocated',
                       'edge_verification': 'receipt_missing'},
        'version_history': {'state': data_state('partial') if observations else data_state('unknown'),
                            'current': _reference(contract, contract.get('revision')),
                            'effective_business_version': _unknown('effective-version rule unlocated'),
                            'historical_observations': observations,
                            'formal_revisions': {'state': data_state('unlocated')}},
        'details': {'section_state': data_state('partial'),
                    'identity': _reference(contract, contract.get('revision')),
                    'source_fields': _fields(contract),
                    'relationship_count': child_state,
                    'mapping_state': data_state('unlocated'), 'warnings': warnings},
    }
