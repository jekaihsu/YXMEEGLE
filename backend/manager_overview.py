"""Pure, unwired Manager Overview (VCC-128) for an already authorized workspace.

Population protocol: ``population(state, filters) -> list[dict] | None`` supplies one
row per confirmation version, with ``row_key`` (source context + record_id +
version, encoded as an injective opaque string) and ``project_id`` (existing assignments mapping's stable case ID, or
None for unresolved). It must use only this narrowed state, preserve source
versions, and apply exactly the supplied filters. No confirmation_list import,
name/code/suffix join, source read, or permission widening occurs here. None
means unavailable/undetermined population, never an empty or zero population.

``population_state`` is an optional trusted C-STATE envelope for that exact
filtered read, authorized by the coordinator's P2-128B contract clarification.
Without it, loaded nonempty facts are partial and empty reads are unknown.
Only explicit complete_empty/filtered_empty evidence permits zero. C-STATE has
no ready/complete-nonempty value; arbitrary "ready" strings are rejected.
Failure/loading/unknown do not acquire counts from retained rows. ``as_of`` is
the caller's snapshot instant, never a fetch time relabelled source-updated.

Case candidates come from the caller's authorized projects, across all history,
not from confirmation versions. Only pm_id and execution_status filters have
proven project fields and apply to cases. Version/cutoff/scope and other opaque
population filters have no project mapping here; they apply to cards/drilldown
only. Missing population leaves local cases intact with unknown row_keys.

Local unfinished execution: operations.py:190-195 and shell.py:178. This is
workbench execution, not engineering lifecycle or source closure. No manager
case-action/pending-decision predicate is defined: home_details.py:188-191 and
home_queues.py:54-82 are viewer-specific. company_dashboard.py:10-23 verifies
native pending receipts but does not define a manager decision population.
Its task/deadline counts (company_dashboard.py:39-48,113-124) are different
grains and lack VCC-123 provenance; they are deliberately not reused as cards.
Source stage mappings are unlocated under D3 (receipt_missing), even if
source_lifecycle.declared (source_lifecycle.py:17-28) accepts a mapped string.
Effective due dates remain unknown (my_work.py:42-45). No amount is emitted.

Caller boundary: app.py:300-320 identity/require_access; app.py:324-350
filter_visible_cases -> filter_private_workspace -> case_redaction.apply.
Source Health input is only build_source_health's already authorized result
(source_health.py:70-93,164-170), never a raw source snapshot.
"""
from copy import deepcopy

from .case_cutover import admission_fields
from .data_state import EMPTY, UNCOUNTED, data_state
from .my_work import _route


OPEN_EXECUTION = frozenset(('pending', 'in_progress', 'engineering_complete', 'paused'))


def _unknown(reason, *, state='unknown'):
    return {'value': None, 'state': data_state(state), 'reason': reason}


def _read_state(envelope, rows):
    if envelope is None:
        return data_state('partial' if rows else 'unknown')
    if not isinstance(envelope, dict) or not isinstance(envelope.get('states'), list):
        raise ValueError('population_state must be a C-STATE envelope')
    # Validate with the real shared contract; do not copy arbitrary metadata.
    result = data_state(*envelope['states'], count=envelope.get('count'))
    if result['states'][0] in EMPTY and rows:
        raise ValueError('empty read state contradicts population')
    return result


def _measure(value, read):
    states = read['states']
    if states == ['forbidden']:
        return None, data_state('forbidden'), 'Population is not authorized.'
    if value is None:
        return None, data_state('unknown') if states[0] in EMPTY else data_state(*states), (
            'The population is unavailable; no denominator is established.')
    if states[0] in UNCOUNTED:
        return None, data_state(*states), 'The population read does not establish a count.'
    if value == 0 and states[0] not in EMPTY:
        return None, data_state('unknown'), 'No complete authorized zero-population evidence.'
    return value, data_state(*states, count=value), (
        'Complete authorized empty population.' if states[0] in EMPTY else
        'Loaded authorized population only; completeness is not asserted.')


def _card(ident, label, unit, value, read, filters, as_of):
    value, state, reason = _measure(value, read)
    return {'id': ident, 'label': label, 'unit': unit, 'state': state,
            'value': value, 'reason': reason, 'as_of': as_of,
            'drilldown': {'route': 'confirmations', 'filters': deepcopy(filters),
                          'group_by': 'project_id' if unit == 'stable_case' else 'row_key'}}


def _unavailable_card(ident, label, reason, filters, as_of):
    result = _card(ident, label, 'stable_case', 0, data_state('unknown'), filters, as_of)
    result['reason'] = reason
    return result


def _case(project, versions, people):
    status = project.get('execution_status')
    unfinished = ({'value': True, 'state': None,
                   'reason': 'Open local workbench execution state (operations.py:190-195).'}
                  if status in OPEN_EXECUTION else
                  _unknown('Local execution state is missing or undefined; source closure is not inferred.'))
    person = people.get(project.get('pm_id'))
    responsible = ({'value': person.get('name'), 'state': None,
                    'reason': 'Current stored PM assignment; pending handovers do not replace it.'}
                   if person and person.get('name') else
                   _unknown('Current PM has no authorized person label.'))
    # IDs stay in details except the stable case ID needed for row/navigation.
    return {'project_id': project['id'], 'label': project.get('name') or project.get('code') or None,
            'unfinished': unfinished,
            'actionable': _unknown('No manager-level actionable-case predicate; task readiness is viewer-specific.'),
            'responsible': responsible,
            'current_stage': _unknown('VCC-117 stage mapping receipts are missing.', state='unlocated'),
            'effective_due_date': _unknown('VCC-123: no verified formal effective approved due field.'),
            'blocker': _unknown('No manager-level case blocker definition; task blockers are scoped separately.'),
            'pending_decision': _unknown('No manager-level pending-decision definition.'),
            'entry_point': {'route': _route(project['id']), 'kind': 'case', 'read_only': True},
            'details': {'row_keys': deepcopy(versions), 'pm_id': person.get('id') if person else None,
                        'execution_status': status,
                        'admission': admission_fields(project, project.get('execution_allowed') is True),
                        'mapping_state': 'receipt_missing',
                        'amounts': {'value': None, 'state': 'withheld', 'reason': 'G-AMT remains open.'},
                        'formula': 'Source versions stay distinct; stable cases use only non-null assignment project_id.'}}


def _health(result):
    page = result.get('page_state') if isinstance(result, dict) else None
    # Malformed/absent state is unknown, never an assertion of overall health.
    if not isinstance(page, dict) or not isinstance(page.get('states'), list) or not page['states']:
        page = data_state('unknown')
    else:
        page = data_state(*page['states'])
    return {'route': 'sources', 'state': page,
            'reason': 'Source Health page state only; no diagnostic source inventory is exposed.',
            'failure': {'state': page if 'read_failed' in page['states'] else data_state('unknown'),
                        'reason': 'Applies only to the Source Health read; unrelated case facts are retained.'},
            'partial': {'state': page if 'partial' in page['states'] else data_state('unknown'),
                        'reason': 'Only the injected Source Health page can establish partial loading.'},
            'unmatched': _unknown('The Source Health page-state projection supplies no unmatched population.',
                                  state='unlocated')}


def build_manager_overview(state, *, population, filters=None, period=None,
                           source_health=None, as_of=None, population_state=None):
    """Return snapshot, separate unavailable weekly dataset, and Source Health.

    No period is forwarded to the population. Filters are opaque, preserved
    exactly (including version/cutoff/scope), and belong to the shared snapshot
    population. Unknown actionability candidates remain visible for verification.
    Status buckets may overlap; this result has no additive bucket total.
    """
    filters = deepcopy(filters) if filters is not None else {}
    # Explicit forbidden read cannot expose a population, label or count.
    if population_state is not None and _read_state(population_state, [])['states'] == ['forbidden']:
        return {'as_of': as_of, 'snapshot': {'state': data_state('forbidden')},
                'weekly_activity': _unknown('No authorized weekly event population.', state='forbidden'),
                'source_health': _health(source_health)}
    rows = population(state, deepcopy(filters))
    available = rows is not None
    if available and not isinstance(rows, list):
        raise ValueError('population must return a list or None')
    if not available:
        rows = []
    projects = {p['id']: p for p in state.get('projects', [])
                if isinstance(p, dict) and p.get('id')}
    versions = {}
    unresolved = []
    row_keys = set()
    for row in rows:
        if not isinstance(row, dict) or 'row_key' not in row or 'project_id' not in row:
            raise ValueError('population row lacks required identity')
        key = row['row_key']
        if not isinstance(key, str) or not key or key in row_keys:
            raise ValueError('population row_key must be a unique nonempty opaque string')
        row_keys.add(key)
        pid = row['project_id']
        if pid is None:
            unresolved.append({'details': {'row_key': deepcopy(row['row_key']),
                                           'mapping_state': 'receipt_missing'}})
        elif pid not in projects:
            # Reject a broken injected boundary instead of emitting a forbidden
            # identifier or silently changing the drilldown denominator.
            raise ValueError('population refers outside the authorized workspace')
        else:
            versions.setdefault(pid, []).append(row['row_key'])
    read = _read_state(population_state, rows)
    if not available and read['states'][0] in EMPTY:
        read = data_state('unknown')  # None contradicts a claim of proven emptiness.
    people = {p['id']: p for p in state.get('users', [])}
    cases = []
    for pid, project in projects.items():
        if project.get('execution_status') == 'completed':
            continue
        # These two filters alone are defined on the authorized project shape.
        if filters.get('pm_id') and project.get('pm_id') != filters['pm_id']:
            continue
        if filters.get('execution_status') and project.get('execution_status') != filters['execution_status']:
            continue
        case = _case(project, versions.get(pid, []) if available else None, people)
        if not available:
            case['details']['row_keys_state'] = data_state('unknown')
            case['details']['row_keys_reason'] = 'The confirmation population is unavailable; row keys are unknown.'
        cases.append(case)
    cards = [_card('confirmation_versions', 'Confirmation versions', 'confirmation_version',
                   len(rows) if available else None, read, filters, as_of),
             _card('stable_cases', 'Stable cases', 'stable_case', len(versions) if available else None, read, filters, as_of),
             _unavailable_card('pending_decisions', 'Pending decisions',
                               'No manager-level pending-decision definition.', filters, as_of),
             _unavailable_card('overdue_cases', 'Overdue cases',
                               'VCC-123: effective approved due date provenance is unresolved.', filters, as_of)]
    unresolved_count, unresolved_state, reason = _measure(len(unresolved) if available else None, read)
    return {'as_of': as_of,
            'snapshot': {'state': read, 'filters': deepcopy(filters), 'cases': cases, 'cards': cards,
                         'unresolved': {'value': unresolved_count, 'state': unresolved_state,
                                        'reason': reason, 'rows': unresolved},
                         'bucket_policy': 'Status buckets may overlap and must never be summed.'},
            'weekly_activity': {**_unknown('No proven period-event source or weekly activity definition.',
                                          state='unlocated'), 'period': deepcopy(period), 'rows': None},
            'source_health': _health(source_health)}
