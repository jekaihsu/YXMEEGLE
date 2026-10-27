"""Pure Source Health projection of an already visibility-filtered snapshot.

The caller owns source visibility, diagnostic capability and read authorization.
No reads, grants, receipts, schema inventory or source modification times are
inferred here. Ordinary output exposes only the page state. With diagnostics,
``sources`` is SourceInput-compatible; ``diagnostic.sources`` is separate
and may be dropped, or explicitly joined by its opaque key by an authorized
caller before passing the input to buildSourceHealthView.
"""
from datetime import datetime
import hashlib
import json

from .data_state import data_state


def _time(value):
    """Normalize real instants to the frontend's millisecond ISO contract."""
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value)
    except ValueError:
        return None
    if instant.tzinfo is None or 'T' not in value:
        return None
    return instant.isoformat(timespec='milliseconds')


def _count(value):
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def _permitted(value):
    # No implicit override of an explicit denial or malformed authority flag.
    return ('authorized' not in value or value['authorized'] is True) and value.get('status') not in ('forbidden', 'unauthorized')


def _state(snapshot, freshness, table=None, *, viewer_filtered=None):
    status = (table or snapshot).get('status')
    if status in ('forbidden', 'unauthorized'):
        return data_state('forbidden')
    if snapshot.get('status') == 'error' or status in ('error', 'read_failed'):
        return data_state('read_failed')
    # Only an active refresh (lease) supersedes a retained historical last_error.
    if freshness.get('status') == 'refreshing':
        if status in ('ready', 'partial') and _time((table or {}).get('last_sync', snapshot.get('last_sync'))):
            return data_state(*(['partial'] if status == 'partial' else []), 'stale')
        return data_state('loading')
    if freshness.get('last_error') or freshness.get('status') in ('error', 'blocked', 'needs-permission'):
        return data_state('read_failed')
    if status == 'loading':
        return data_state('loading')
    if status == 'unlocated':
        return data_state('unlocated')
    read = table is not None and table.get('status') in ('ready', 'partial') and (_count(table.get('pages_read')) or 0) > 0
    if not read:
        return data_state('unknown')
    partial = status == 'partial'
    age, ttl = freshness.get('age_seconds'), freshness.get('ttl_seconds')
    stale = freshness.get('status') == 'stale' or (type(age) in (int, float) and type(ttl) in (int, float) and age >= ttl)
    states = (['partial'] if partial else []) + (['stale'] if stale else [])
    if states:
        return data_state(*states)
    if freshness.get('status') != 'fresh':
        return data_state('unknown')
    if _count(table.get('count')) == 0:
        # A visible zero alone proves neither an empty source nor a filter.
        if viewer_filtered is False:
            return data_state('complete_empty')
        if viewer_filtered is True:
            return data_state('filtered_empty')
        return data_state('unknown')
    return None  # Explicit healthy read fact, not a new C-STATE value.


def build_source_health(snapshot, freshness=None, *, diagnostic=False, read_authorized=False, viewer_filtered=None):
    """Build SourceHealthInput without returning any record values.

    ``freshness`` is status(wid)['datasets']['sources'], not the full envelope.
    Per-table last_sync/last_attempt_at, when available, take precedence over
    the atomic snapshot timestamps. fetched_at/changed_at are never source
    modification timestamps. Existing table ``count`` means visible loaded
    rows only; whole-table, view and excluded counts remain unknown.

    G-DIAG is the caller's decision: this function does not check any role.
    ``read_authorized=True`` supplies only the dataset 'sources' retry handle.
    ``viewer_filtered`` is the caller's explicit fact about this snapshot:
    True asserts a filter narrowed it; False asserts it was not narrowed.
    None (the default), or any non-boolean value, leaves that scope unknown.
    A complete fresh zero-row read is filtered_empty only with True, or
    complete_empty only with False; unknown scope emits unknown with no count.
    ``diagnostic=True`` exposes only already permitted source read evidence.
    located/readable describe the last successful read, including retained
    evidence during a current read_failed; they do not prove current access.
    Freshness blocked is an application read_failed with safe error='blocked',
    while viewer authorization and explicit forbidden remain caller decisions.
    Healthy nonempty pages use None (there is no healthy state in C-STATE);
    their diagnostic rows carry the explicit health='healthy' fact.
    """
    freshness = freshness or {}
    if not _permitted(snapshot):
        return {'page_state': data_state('forbidden'), 'sources': []}

    tables = [t for t in snapshot.get('tables', []) if _permitted(t)]
    # Identity is the full source context; never a name, suffix or case number.
    identities = [(t.get('base_token'), t.get('table_id')) for t in tables]
    rows, identifiers = [], []
    page_states = []
    relevant_times = []
    for table, identity in sorted(zip(tables, identities), key=lambda pair: json.dumps(pair[1])):
        if not all(isinstance(part, str) and part.strip() for part in identity) or identities.count(identity) != 1:
            # Keep the page conservative, but summarize only the emitted rows
            # that the frontend can identify, select and count.
            page_states.append('unknown')
            continue
        state = _state(snapshot, freshness, table, viewer_filtered=viewer_filtered)
        if state and state['states'] == ['forbidden']:
            continue
        key = 'source:' + hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        row = {'key': key, 'authorized': True, 'mapped': False, 'accepted': False}
        read = table.get('status') in ('ready', 'partial') and (_count(table.get('pages_read')) or 0) > 0
        if read:
            row.update(located=True, readable=True)
        # A source read is not evidence of presentation in a consuming report.
        success = _time(table.get('last_sync', snapshot.get('last_sync'))) if read else None
        attempt = _time(table.get('last_attempt_at', snapshot.get('last_attempt_at')))
        if attempt:
            row['last_attempt'] = attempt
        if success:
            row['last_success'] = success
        relevant = table.get('relevant') is not False
        row['relevant'] = relevant
        if relevant:
            relevant_times.append(success)
            if state:
                page_states.extend(state['states'])
        if state:
            row['data_state'] = state
        else:
            row['health'] = 'healthy'
        if diagnostic is True:
            if state and 'read_failed' in state['states']:
                row['last_error_summary'] = {'blocked': '設定未完成', 'needs-permission': '權限不足'}.get(freshness.get('status'), '來源讀取失敗')
            if isinstance(table.get('name'), str) and table['name'].strip():
                row['name'] = table['name']
            loaded = _count(table.get('count')) if read and (state is None or state['states'] != ['unknown']) else None
            if loaded is not None:
                row['loaded_count'] = loaded
            if read_authorized is True:
                row.update(read_authorized=True, retry_handle={'dataset': 'sources'})
            rows.append(row)
            identifiers.append({'key': key, 'base_id': identity[0], 'table_id': identity[1]})

    # C-STATE permits only partial+stale to coexist. Error/unknown etc. win;
    # source rows still retain their independently observable states/timestamps.
    root_state = _state(snapshot, freshness)
    root_states = root_state['states']
    if root_states != ['unknown']:
        page_states.extend(root_states)
    priorities = ('forbidden', 'read_failed', 'loading', 'unlocated', 'unknown')
    primary = next((s for s in priorities if s in page_states), None)
    if primary:
        page = data_state(primary)
    elif 'partial' in page_states or 'stale' in page_states:
        page = data_state(*[s for s in ('partial', 'stale') if s in page_states])
    elif page_states and all(s == 'filtered_empty' for s in page_states) and len(page_states) == len(relevant_times):
        page = data_state('filtered_empty')
    elif page_states and all(s == 'complete_empty' for s in page_states):
        page = data_state('complete_empty') if len(page_states) == len(relevant_times) else None
    else:
        page = None if relevant_times and not page_states else data_state('unknown')
    result = {'page_state': page, 'sources': rows}
    if page and 'read_failed' in page['states']:
        result['error'] = 'blocked' if freshness.get('status') == 'blocked' else 'source_read_failed'
    if diagnostic is True:
        oldest = min(relevant_times, key=lambda t: datetime.fromisoformat(t)) if relevant_times and all(relevant_times) else None
        result['diagnostic'] = {'sources': identifiers, 'receipt_state': 'receipt_missing', 'last_success': oldest}
    return result
