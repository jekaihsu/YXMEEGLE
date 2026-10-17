"""Read-state envelope for list/count reads; this module performs no reads.

Every state stays distinct: a read that has not finished, a read that found
nothing, a filter that hid everything, a source that could not be located, a
viewer without access, a failed read and an undetermined result must never
collapse into one another or into a zero count. Only ``partial`` and ``stale``
describe the same delivered rows and may therefore be reported together.
"""

STATES = ('loading', 'complete_empty', 'filtered_empty', 'unlocated', 'forbidden',
          'read_failed', 'partial', 'stale', 'unknown')
COMBINABLE = frozenset({'partial', 'stale'})
EMPTY = frozenset({'complete_empty', 'filtered_empty'})
# These states make no claim about how many rows exist.
UNCOUNTED = frozenset({'loading', 'unlocated', 'read_failed', 'unknown'})


def _count(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('count must be a non-negative integer or None')
    return value


def data_state(*states, count=None, name=None):
    """Return the public envelope ``{'states': [...], 'count': ..., 'name'?: ...}``.

    ``forbidden`` returns only ``{'states': ['forbidden']}``; a caller that
    passes a name or count for it is rejected rather than silently trimmed so
    the leak is fixed where it originates.
    """
    if not states:
        raise ValueError('at least one state is required')
    unknown = [state for state in states if state not in STATES]
    if unknown:
        raise ValueError(f'unsupported state: {unknown[0]!r}')
    if len(set(states)) != len(states):
        raise ValueError('duplicate state')
    if len(states) > 1 and not set(states) <= COMBINABLE:
        raise ValueError('only partial and stale may coexist')
    if name is not None and (not isinstance(name, str) or not name):
        raise ValueError('name must be a non-empty string or None')
    count = _count(count)
    ordered = [state for state in STATES if state in states]
    if ordered == ['forbidden']:
        if count is not None or name is not None:
            raise ValueError('forbidden carries no name or count')
        return {'states': ordered}
    first = ordered[0]
    if first in EMPTY:
        if count not in (None, 0):
            raise ValueError(f'{first} has a count of zero')
        count = 0
    elif first in UNCOUNTED and count is not None:
        # In particular, unknown is never reported as zero.
        raise ValueError(f'{first} carries no count')
    payload = {'states': ordered, 'count': count}
    if name is not None:
        payload['name'] = name
    return payload
