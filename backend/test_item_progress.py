"""Per-item status and per-node progress from Lark's own revenue points, with literal expectations."""
from decimal import Decimal

import pytest

from .item_progress import (
    DONE, NO_SIGNAL, PARTIAL, REMAINING_POINTS_FIELD, fmt, item_status, node_progress, parse_points)
from .sources import FIELDS

D = Decimal


def test_the_remaining_field_name_keeps_lark_stray_character():
    assert REMAINING_POINTS_FIELD == '本工項剩餘營ˊ業額' and 'ˊ' in REMAINING_POINTS_FIELD
    assert REMAINING_POINTS_FIELD != '本工項剩餘營業額'
    assert REMAINING_POINTS_FIELD in FIELDS['reporting']


@pytest.mark.parametrize('value, expected', [
    ('4.625', D('4.625')), (4.625, D('4.625')), (3, D(3)), ('0', D(0)), (' 1,250.5 ', D('1250.5')),
    ([{'text': '0.0025', 'type': 'text'}], D('0.0025')), ('1.2e-05', D('0.000012')), ('.5', D('0.5')),
    (None, None), ('', None), ('  ', None), (True, None), ('abc', None), ('1_000', None), ('-1', None), (-0.5, None),
    ('NaN', None), ('Infinity', None), ('-Infinity', None), (float('nan'), None), (float('inf'), None),
    ('1e9999999999', None), ('1' + '0' * 10, None), ('1000000001', None), ('1e-99999999', None), ('1' * 101, None),
    ({'x': 1}, None), ([], None),
])
def test_parse_points(value, expected):
    assert parse_points(value) == expected


def test_the_largest_accepted_value_and_formatting():
    assert parse_points('1000000000') == D(10) ** 9
    assert fmt(parse_points('4.6250')) == '4.625' and fmt(parse_points('1e3')) == '1000' and fmt(parse_points('0.00')) == '0'
    assert fmt(None) is None


@pytest.mark.parametrize('planned, remaining, status', [
    ('10', '0', DONE), ('10', '0.0', DONE), ('0.0025', '0', DONE),
    ('10', '3', PARTIAL), ('10', '9.999', PARTIAL), ('10', '0.0001', PARTIAL),
    ('10', '10', NO_SIGNAL),            # ambiguous: nothing done or nothing linked
    ('10', '10.5', NO_SIGNAL),          # remaining above the plan cannot be progress
    ('10', None, NO_SIGNAL), (None, '5', NO_SIGNAL), (None, None, NO_SIGNAL),
    ('0', '0', NO_SIGNAL), ('0', '-1', NO_SIGNAL),   # no plan to complete
])
def test_item_status_table(planned, remaining, status):
    assert item_status(parse_points(planned), parse_points(remaining)) == status


@pytest.mark.parametrize('planned, remaining', [
    ('10', '-3'), ('10', 'NaN'), ('10', '1e9999999999'), ('10', 'oops'), ('-10', '0'), ('1e9999999999', '0'), ('10', '1000000001'),
])
def test_malformed_values_have_no_signal(planned, remaining):
    assert item_status(parse_points(planned), parse_points(remaining)) == NO_SIGNAL


def pairs(*rows):
    return [(parse_points(p), parse_points(r)) for p, r in rows]


def test_node_percent_is_decimal_safe_and_rounds_half_up_to_one_decimal():
    node = node_progress(pairs(('0.1', '0.0'), ('0.2', '0.2'), ('0.7', '0.4')))
    assert (node.earned, node.planned, node.items_total, node.items_done, node.known, node.all_done) == (
        D('0.4'), D('1.0'), 3, 1, True, False)
    assert node.percent == D('40.0')
    assert node.public() == {'percent': '40', 'earned_points': '0.4', 'planned_points': '1', 'items_done': 1, 'items_total': 3}
    assert node_progress(pairs(('3', '1'), ('3', '3'))).percent == D('33.3')
    assert node_progress(pairs(('3', '2'), ('3', '3'))).percent == D('16.7')   # 1/6 = 16.666..


def test_one_partial_item_among_untouched_ones_is_a_lower_bound_not_zero_or_full():
    node = node_progress(pairs(('100', '50'), ('100', '100')))
    assert (node.known, node.items_done, node.percent) == (True, 0, D('25.0'))


def test_nothing_known_means_no_progress_and_no_percent():
    for rows in ([], [('10', '10')], [('10', None), (None, '3')], [('10', '12')], [('0', '0')]):
        node = node_progress(pairs(*rows))
        assert (node.known, node.percent, node.all_done, node.public()) == (False, None, False, None), rows


def test_all_done_needs_every_item_done_and_a_complete_list():
    done = pairs(('4', '0'), ('6', '0'))
    assert node_progress(done).all_done is True and node_progress(done).percent == D('100.0')
    assert node_progress(done, complete=False).all_done is False
    assert node_progress(pairs(('4', '0'), ('6', '2'))).all_done is False
    assert node_progress(pairs(('4', '0'), ('6', '6'))).all_done is False
    assert node_progress(pairs(('4', '0'), (None, None))).all_done is False
    assert node_progress(pairs(('4', '0'), ('6', '-1'))).all_done is False


def test_a_partial_node_never_displays_100_until_every_item_is_done():
    node = node_progress(pairs(('100000', '0.1')))
    assert node.percent == D('99.9') and node.all_done is False
    assert node_progress(pairs(('100000', '0'))).percent == D('100.0')


def test_the_points_gate_keeps_only_counts():
    node = node_progress(pairs(('4', '0'), ('6', '3')))
    assert node.public(points=False) == {'percent': None, 'earned_points': None, 'planned_points': None, 'items_done': 1, 'items_total': 2}
