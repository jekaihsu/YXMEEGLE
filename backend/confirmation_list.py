"""Confirmation List read model (VCC-129): pure, unwired, read-only.

Input is a workspace state the caller has already narrowed (identity ->
production_access.require_access -> source_case_policy.filter_visible_cases /
visible_source_snapshot -> allowlists -> case_redaction).  Nothing here widens
it: whatever is absent from ``state`` is absent from every row, count and id.

Identity: one row per confirmation source record version, keyed by
``SourceRef.version_key`` (base_token, table_id, record_id, version).  A case
link exists only when the entity carries the ``project_id`` produced by the
import assignments mapping *and* that project is present in the narrowed
state; names, case numbers and suffixes never join.  No receipt authority
exists (plan D3), so every link reports ``receipt_missing``.

Unresolved, reported as unknown rather than guessed:

* effective due date (VCC-123 deadline provenance unresolved); the deadline
  range filter is ``unavailable`` and never hides a row.
* source-modified time: Lark's ``last_modified_time`` is read into raw records
  (sources.py:128) but ``update_entities`` does not copy it onto confirmation
  entities (source_entities.py:78-103) and ``public_source_cache`` strips it
  (workspace_projection.py:101); an entity's ``history[].replaced_at`` is the
  retrieval clock.  No trustworthy field survives, so the default order is the
  caller's source order plus ``row_key`` and no sort by time is offered.
* contract amounts stay withheld (gate G-AMT): ``fields`` is read only for the
  project name, case number and PM text.
"""
import base64
import binascii
import hashlib
import json
from collections import Counter
from urllib.parse import quote

from .case_cutover import admission_fields, execution_allowed
from .data_state import data_state
from .source_identity import SourceRef
from .sources import text

DEFAULT_COLUMNS = ('case_number', 'project_name', 'confirmation_version', 'pm', 'admission_state',
                   'effective_due', 'workflow_summary', 'source_modified', 'source_status')
NON_DEFAULT_COLUMNS = ('record_id', 'source_context')
SORTABLE = ('case_number', 'project_name', 'confirmation_version', 'pm', 'admission_state')
NUMERIC_COLUMNS = frozenset({'confirmation_version'})
FILTER_KEYS = frozenset({'source_version', 'pm', 'admission_state', 'deadline_from', 'deadline_to'})
DEADLINE_REASON = 'effective due date is unknown: VCC-123 deadline provenance is unresolved'
MODIFIED_REASON = 'no trustworthy source-modified field survives into confirmation entities'
AMOUNT_WITHHELD = {'state': 'withheld', 'reason': 'contract amounts are hidden pending gate G-AMT'}
MAX_LIMIT = 100
HEALTHY = frozenset({'ready', 'ok', 'fresh', 'complete'})


class ListError(ValueError):
    """Bad query; surfaces as a 422-style result."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code, self.detail = code, detail


def _error(err, status=422):
    return {'status': status, 'error': err.code, 'detail': err.detail}


def _dedupe_key(ref):
    """Two deliveries of the same record version collapse; different versions never do."""
    return ref.version_key


def _row_key(ref):
    """Injective public key over the full version-qualified identity.

    ``source_key`` has exactly three non-empty components without ``/``; the
    version part is type-tagged (u none, i int, s str) and percent-encoded, so
    it never contains ``@`` and the last ``@`` always splits it off.
    """
    v = ref.version
    tag = 'u' if v is None else f'i{v}' if isinstance(v, int) else 's' + quote(v, safe='')
    return f'{ref.source_key}@{tag}'


def _case_link(entity, projects):
    """Verified assignment only: entity.project_id must name a project visible in this state."""
    pid = entity.get('project_id')
    if not isinstance(pid, str) or not pid.strip():
        return None, 'assignment_absent'
    if pid not in projects:
        return None, 'project_not_visible'
    return pid, None


def _binding(q, filters, sort):
    """Opaque identity of the filter/sort set a cursor belongs to (page size excluded)."""
    blob = json.dumps([q, filters, sort], sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _encode_cursor(binding, row_key):
    raw = json.dumps({'b': binding, 'k': row_key}, separators=(',', ':'), ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip('=')


def _decode_cursor(cursor, binding):
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)).decode())
        key, bound = raw['k'], raw['b']
    except (ValueError, KeyError, TypeError, binascii.Error):
        raise ListError('cursor_invalid', 'cursor is malformed')
    if not isinstance(key, str) or not _cursor_matches(binding, bound):
        raise ListError('cursor_filter_mismatch', 'cursor was issued for a different filter or sort set')
    return key


def _cursor_matches(expected, actual):
    return actual == expected


def _normalize_filters(filters):
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise ListError('filters_invalid', 'filters must be an object')
    unknown = sorted(set(filters) - FILTER_KEYS)
    if unknown:
        raise ListError('filter_unsupported', f'unsupported filter: {unknown[0]}')
    result = {}
    for key, value in filters.items():
        if value in (None, '', []):
            continue
        if key in ('deadline_from', 'deadline_to'):
            if not isinstance(value, str) or len(value) != 10 or value[4] != '-' or value[7] != '-':
                raise ListError('filter_invalid', f'{key} must be YYYY-MM-DD')
            result[key] = value
            continue
        values = [value] if isinstance(value, str) else value
        if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
            raise ListError('filter_invalid', f'{key} must be a string or list of strings')
        result[key] = sorted(set(values))
    return result


def _normalize_sort(sort):
    if sort in (None, '', {}):
        return None
    if not isinstance(sort, dict) or sort.get('direction') not in (None, 'asc', 'desc', 'clear'):
        raise ListError('sort_invalid', 'sort must be {column, direction}')
    column, direction = sort.get('column'), sort.get('direction') or 'asc'
    if direction == 'clear' or column in (None, ''):
        return None
    if column not in SORTABLE:
        raise ListError('sort_unsupported', f'column is not sortable: {column}')
    return {'column': column, 'direction': direction}


def _numeric(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _source_state(state):
    """Source-level read state, mirroring source_health.py:35-41 status names."""
    source = state.get('source_status')
    status = source.get('status') if isinstance(source, dict) else None
    if status in ('forbidden', 'unauthorized'):
        return 'forbidden'
    if status in ('error', 'read_failed', 'blocked'):
        return 'read_failed'
    if status in ('loading', 'refreshing'):
        return 'loading'
    if status == 'unlocated' or not isinstance(state.get('source_confirmations'), list):
        return 'unlocated'
    if status == 'partial':
        return 'partial'
    if status == 'stale':
        return 'stale'
    return 'ok' if status in HEALTHY else 'unknown'


def _workflow_summary(project):
    nodes = project.get('nodes') if isinstance(project, dict) else None
    if not isinstance(nodes, list):
        return {'state': 'unknown', 'reason': 'project nodes absent'}
    by_status = Counter(str(n.get('status') or 'unknown') for n in nodes if isinstance(n, dict))
    return {'state': 'known', 'total': sum(by_status.values()),
            'completed': by_status.get('completed', 0), 'by_status': dict(sorted(by_status.items()))}


def _build_rows(state, source_state):
    """Authorized rows in the caller's source order, plus bookkeeping counts."""
    projects = {p['id']: p for p in state.get('projects') or [] if isinstance(p, dict) and p.get('id')}
    users = {u.get('id'): u for u in state.get('users') or [] if isinstance(u, dict)}
    seen, rows, unkeyed, collapsed = set(), [], 0, 0
    for order, entity in enumerate(state.get('source_confirmations') or []):
        if not isinstance(entity, dict) or entity.get('source_kind') not in (None, 'confirmation', 'quote_confirmation'):
            continue
        origin = entity.get('source_identity') or entity
        version = entity.get('source_version')
        try:
            ref = SourceRef.from_entity(origin, version=version)
        except ValueError:
            unkeyed += 1
            continue
        dedupe = _dedupe_key(ref)
        if dedupe in seen:
            collapsed += 1
            continue
        seen.add(dedupe)
        fields = entity.get('fields') if isinstance(entity.get('fields'), dict) else {}
        pid, reason = _case_link(entity, projects)
        project = projects.get(pid)
        if project is not None:
            admission = admission_fields(project, execution_allowed(state, project))
            admission_state = admission['execution_system']
            admission_out = {'state': admission_state, 'label': admission['execution_system_label'],
                             'readonly_reason': admission['execution_readonly_reason']}
            pm_id = project.get('pm_id') or None
            pm = {'id': pm_id, 'name': (users.get(pm_id) or {}).get('name') if pm_id else None,
                  'state': 'known' if pm_id else 'unknown'}
        else:
            admission_state = 'unknown'
            admission_out = {'state': 'unknown', 'label': None, 'readonly_reason': 'case link unresolved'}
            pm = {'id': None, 'name': text(fields.get('案件負責人')) or None, 'state': 'unknown'}
        number = text(entity.get('code') or fields.get('工程確認單編號')) or None
        name = text(fields.get('工程名稱')) or None
        missing = entity.get('source_missing') is True
        # Only a healthy read observed these rows; partial/stale/failed reads retain earlier ones.
        status = 'missing' if missing else 'located' if source_state == 'ok' else 'unknown' if source_state == 'unknown' else 'stale'
        key = _row_key(ref)
        rows.append({
            'row_key': key, 'case_number': number, 'project_name': name,
            'confirmation_version': {'value': None if version is None else str(version),
                                     'state': 'unknown' if version is None else 'known'},
            'pm': pm, 'admission': admission_out,
            'effective_due': {'state': 'unknown', 'value': None, 'reason': DEADLINE_REASON},
            'workflow_summary': _workflow_summary(project) if project is not None
                else {'state': 'unknown', 'reason': 'case link unresolved'},
            'source_modified': {'state': 'unknown', 'value': None, 'reason': MODIFIED_REASON},
            'source_status': status,
            'retention': 'current' if status == 'located' else 'snapshot',
            'case_link': {'state': 'linked' if project is not None else 'unresolved',
                          'project_id': pid, 'reason': reason, 'verification': 'receipt_missing'},
            'detail': {'source_context': {'base_token': ref.base, 'table_id': ref.table},
                       'record_id': ref.record_id, 'non_default': True},
            '_order': order, '_version': version,
        })
    return rows, {'unkeyed_rows': unkeyed, 'duplicate_versions_collapsed': collapsed}


def _sort_value(row, column):
    if column == 'case_number':
        return row['case_number']
    if column == 'project_name':
        return row['project_name']
    if column == 'confirmation_version':
        return row['_version']
    if column == 'pm':
        return row['pm']['name'] or row['pm']['id']
    return row['admission']['state'] if row['admission']['state'] != 'unknown' else None


def _ordered(rows, sort):
    base = sorted(rows, key=lambda r: (r['_order'], r['row_key']))
    if sort is None:
        return base
    column, desc = sort['column'], sort['direction'] == 'desc'
    known = [r for r in sorted(rows, key=lambda r: r['row_key']) if _sort_value(r, column) not in (None, '')]
    unknown = [r for r in sorted(rows, key=lambda r: r['row_key']) if _sort_value(r, column) in (None, '')]

    def key(row):
        value = _sort_value(row, column)
        number = _numeric(value) if column in NUMERIC_COLUMNS else None
        return (0, number, '') if number is not None else (1, 0, str(value).casefold())
    # Python's reverse sort keeps equal keys in input order, so row_key stays the tiebreak.
    known.sort(key=key, reverse=desc)
    return known + unknown


def _apply(rows, q, filters):
    """Return (matching rows, excluded-because-unknown counts) from the authorized rows."""
    needle = q.casefold().strip()
    wanted_version = set(filters.get('source_version', ()))
    wanted_pm = set(filters.get('pm', ()))
    wanted_admission = set(filters.get('admission_state', ()))
    excluded, kept = Counter(), []
    unknown_rows = set()
    for row in rows:
        if needle:
            hay = ' '.join(str(v) for v in (row['case_number'], row['project_name'], row['pm']['name']) if v)
            if needle not in hay.casefold():
                continue
        ok = True
        for name, wanted, value in (('source_version', wanted_version, row['confirmation_version']['value']),
                                    ('pm', wanted_pm, row['pm']['id']),
                                    ('admission_state', wanted_admission,
                                     None if row['admission']['state'] == 'unknown' else row['admission']['state'])):
            if not wanted or value in wanted:
                continue
            ok = False
            if value is None:
                excluded[name] += 1
                unknown_rows.add(row['row_key'])
        if ok:
            kept.append(row)
    return kept, {**excluded, 'distinct_rows': len(unknown_rows)} if unknown_rows else {'distinct_rows': 0}


def _snapshot(state, source_state):
    """Provenance of a retained read: ``last_success_at`` must be supplied by the caller's source status."""
    if source_state == 'ok':
        return None
    source = state.get('source_status')
    stamp = source.get('last_success_at') if isinstance(source, dict) else None
    proven = isinstance(stamp, str) and bool(stamp.strip())
    return {'state': 'proven' if proven else 'unproven', 'last_success_at': stamp if proven else None}


def _counts_known(source_state, snapshot, authorized):
    """May row counts be shown as numbers?  Never for an undetermined read, nor an empty non-current one."""
    if source_state == 'ok':
        return True
    if source_state == 'unknown':
        return False
    if source_state == 'read_failed':
        return snapshot['state'] == 'proven'
    return authorized > 0          # partial / stale: delivered rows are a snapshot; an empty one proves nothing


def _basis(source_state, known):
    if source_state == 'ok':
        return 'current'
    if not known:
        return 'undetermined'
    return 'partial_snapshot' if source_state == 'partial' else 'retained_snapshot'


def confirmation_population(state, filters=None, *, q='', sort=None):
    """Ordered ``{'row_key', 'project_id'}`` dicts for a filter set; the drilldown denominator.

    ``project_id`` is the visibility-checked assignment (``None`` when
    unresolved).  Pure and side-effect free.  Returns ``None`` (never a list)
    when the source cannot be read for this caller (forbidden / unlocated /
    loading / undetermined / failed without a proven snapshot / empty partial
    or stale read).
    """
    source_state = _source_state(state)
    if source_state in ('forbidden', 'unlocated', 'loading'):
        return None
    rows, _ = _build_rows(state, source_state)
    if not _counts_known(source_state, _snapshot(state, source_state), len(rows)):
        return None
    matching, _ = _apply(rows, q or '', _normalize_filters(filters))
    return [{'row_key': r['row_key'], 'project_id': r['case_link']['project_id']}
            for r in _ordered(matching, _normalize_sort(sort))]


def _independent_stale(state, source_state):
    """C-STATE keeps partial and stale independent: ``source_status.stale`` marks stale on top of a partial read."""
    source = state.get('source_status')
    return source_state == 'stale' or (source_state == 'partial' and isinstance(source, dict) and source.get('stale') is True)


def _page_state(source_state, authorized, matching, stale=False):
    if source_state in ('read_failed', 'loading', 'unlocated', 'unknown'):
        return data_state(source_state)
    flags = [s for s, on in (('partial', source_state == 'partial'), ('stale', stale)) if on]
    if flags:                      # C-STATE: only partial/stale combine; a filtered zero keeps them
        return data_state(*flags)
    if authorized == 0:
        return data_state('complete_empty')
    if matching == 0:
        return data_state('filtered_empty')
    return None


def _public(row):
    return {k: v for k, v in row.items() if not k.startswith('_')}


def build_confirmation_list(state, *, q='', filters=None, sort=None, cursor=None, limit=50, as_of=None):
    """One page of the Confirmation List over the caller-narrowed ``state``."""
    source_state = _source_state(state)
    if source_state == 'forbidden':
        return {'status': 403, 'page_state': data_state('forbidden')}
    try:
        if not isinstance(q, str) or len(q) > 240:
            raise ListError('q_invalid', 'q must be a string of at most 240 characters')
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
            raise ListError('limit_invalid', f'limit must be an integer from 1 to {MAX_LIMIT}')
        norm_filters, norm_sort = _normalize_filters(filters), _normalize_sort(sort)
        binding = _binding(q.strip(), norm_filters, norm_sort)
        after = _decode_cursor(cursor, binding) if cursor else None
    except ListError as err:
        return _error(err)
    if source_state in ('unlocated', 'loading'):
        return {'status': 200, 'page_state': data_state(source_state), 'rows': [], 'next_cursor': None,
                'totals': {'matching': None, 'loaded': 0, 'authorized_source': None}}
    rows, bookkeeping = _build_rows(state, source_state)
    matching, excluded = _apply(rows, q, norm_filters)
    ordered = _ordered(matching, norm_sort)
    start = 0
    if after is not None:
        index = {r['row_key']: i for i, r in enumerate(ordered)}
        if after not in index:
            return _error(ListError('cursor_stale', 'cursor row is not in the current result set'))
        start = index[after] + 1
    page = ordered[start:start + limit]
    more = start + limit < len(ordered)
    grouping = Counter(r['case_link']['project_id'] for r in matching if r['case_link']['state'] == 'linked')
    snapshot = _snapshot(state, source_state)
    known = _counts_known(source_state, snapshot, len(rows))
    deadline = {'status': 'unavailable', 'reason': DEADLINE_REASON, 'hides_rows': False,
                'requested': {k: v for k, v in norm_filters.items() if k.startswith('deadline_')}}
    return {
        'status': 200, 'as_of': as_of,
        'page_state': _page_state(source_state, len(rows), len(matching), _independent_stale(state, source_state)),
        'rows': [_public(r) for r in page],
        'next_cursor': _encode_cursor(binding, page[-1]['row_key']) if more and page else None,
        # A noncurrent read never proves a filtered zero: the matching denominator stays undetermined.
        'totals': {'matching': len(matching) if known and (matching or source_state == 'ok') else None, 'loaded': len(page),
                   'authorized_source': len(rows) if known else None},
        'totals_basis': _basis(source_state, known), 'snapshot': snapshot,
        'filter_status': {'deadline': deadline},
        'excluded_unknown': excluded,
        'sort': {'applied': norm_sort, 'order_basis': 'source_order_then_row_key' if norm_sort is None
                 else 'column_then_row_key', 'source_modified': 'unavailable', 'reason': MODIFIED_REASON},
        'grouping': {'basis': 'verified project_id assignment only',
                     'linked_cases': len(grouping),
                     'by_case': [{'project_id': pid, 'rows': n} for pid, n in sorted(grouping.items())],
                     'unresolved_rows': sum(r['case_link']['state'] == 'unresolved' for r in matching)},
        'columns': {'default': list(DEFAULT_COLUMNS), 'non_default': list(NON_DEFAULT_COLUMNS)},
        'amounts': dict(AMOUNT_WITHHELD),
        'diagnostics': bookkeeping,
    }
