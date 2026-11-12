"""C-STATE: read states stay separate and never collapse into a zero count."""
import itertools

import pytest

from .data_state import STATES, data_state


def test_every_state_is_preserved_separately():
    assert STATES == ('loading', 'complete_empty', 'filtered_empty', 'unlocated', 'forbidden',
                      'read_failed', 'partial', 'stale', 'unknown')
    payloads = [data_state(state) for state in STATES]
    assert [p['states'] for p in payloads] == [[state] for state in STATES]


def test_partial_and_stale_coexist_in_canonical_order():
    for states in (('partial', 'stale'), ('stale', 'partial')):
        assert data_state(*states, count=12) == {'states': ['partial', 'stale'], 'count': 12}
    assert data_state('partial', count=3) == {'states': ['partial'], 'count': 3}
    assert data_state('stale', count=0) == {'states': ['stale'], 'count': 0}
    assert data_state('partial', 'stale') == {'states': ['partial', 'stale'], 'count': None}


def test_no_other_states_combine():
    for pair in itertools.combinations(STATES, 2):
        if set(pair) == {'partial', 'stale'}:
            continue
        with pytest.raises(ValueError, match='only partial and stale'):
            data_state(*pair)


def test_unknown_never_becomes_zero():
    assert data_state('unknown') == {'states': ['unknown'], 'count': None}
    for count in (0, 5):
        with pytest.raises(ValueError, match='unknown carries no count'):
            data_state('unknown', count=count)


def test_uncounted_states_make_no_count_claim():
    for state in ('loading', 'unlocated', 'read_failed'):
        assert data_state(state)['count'] is None
        with pytest.raises(ValueError, match='carries no count'):
            data_state(state, count=0)


def test_empty_states_are_distinct_zero_counts():
    complete, filtered = data_state('complete_empty'), data_state('filtered_empty', count=0)
    assert complete == {'states': ['complete_empty'], 'count': 0}
    assert filtered == {'states': ['filtered_empty'], 'count': 0}
    assert complete != filtered
    for state in ('complete_empty', 'filtered_empty'):
        with pytest.raises(ValueError, match='count of zero'):
            data_state(state, count=1)


def test_forbidden_carries_no_name_or_count():
    assert data_state('forbidden') == {'states': ['forbidden']}
    for kwargs in ({'name': '機密案件'}, {'count': 0}, {'count': 7}, {'name': 'x', 'count': 1}):
        with pytest.raises(ValueError, match='forbidden carries no name or count'):
            data_state('forbidden', **kwargs)


def test_name_is_kept_for_non_forbidden_states():
    assert data_state('unlocated', name='案件 A') == {'states': ['unlocated'], 'count': None, 'name': '案件 A'}


@pytest.mark.parametrize('kwargs', [{'count': -1}, {'count': True}, {'count': 1.0}, {'count': '3'},
                                    {'name': ''}, {'name': 3}])
def test_rejects_malformed_values(kwargs):
    with pytest.raises(ValueError):
        data_state('partial', **kwargs)


@pytest.mark.parametrize('states', [(), ('ready',), ('partial', 'partial'), ('empty',)])
def test_rejects_unsupported_states(states):
    with pytest.raises(ValueError):
        data_state(*states)
