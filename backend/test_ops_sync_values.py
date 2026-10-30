from datetime import datetime, timezone, timedelta
import pytest

from .ops_sync import values as V
from .ops_sync.testing import env


def test_clear_omitted_unknown_are_distinct():
    assert len({id(V.CLEAR), id(V.OMITTED), id(V.UNKNOWN)}) == 3
    assert V.encode(V.CLEAR) == {'t': 'clear'}
    for blocked in (V.OMITTED, V.UNKNOWN):
        with pytest.raises(V.ValidationError):
            V.encode(blocked)
        with pytest.raises(V.ValidationError) as caught:
            env('c1', intended=blocked).validated()
        assert caught.value.code == 'no_mutation_requested'
    with pytest.raises(V.ValidationError) as caught:
        V.SetValue(None)
    assert caught.value.code == 'set_null'
    with pytest.raises(V.ValidationError) as caught:
        env('c2', expected=V.UNKNOWN).validated()
    assert caught.value.code == 'unknown_baseline'
    assert env('c3', intended=V.CLEAR).validated()['intended'] == {'t': 'clear'}
    assert V.decode(None) is V.UNKNOWN


@pytest.mark.parametrize('bad', ['2026-02-30', '2026/10/11', '11-10-2026', '2026-1-1', '', 20261011, True,
                                 '2026-10-11T00:00:00', datetime(2026, 10, 11)])
def test_invalid_date_and_naive_datetime_rejected(bad):
    with pytest.raises(V.ValidationError):
        V.normalize_date(bad)
    with pytest.raises(V.ValidationError):
        env('c1', intended=V.SetValue(bad)).validated()


def test_naive_and_bad_instants_rejected():
    with pytest.raises(V.ValidationError) as caught:
        V.taipei_date_from_instant(datetime(2026, 10, 10, 16, 0))
    assert caught.value.code == 'naive_datetime'
    with pytest.raises(V.ValidationError):
        V.taipei_date_from_millis(True)
    with pytest.raises(V.ValidationError):
        V.taipei_date_from_millis(1.5e12)
    with pytest.raises(V.ValidationError):
        V.to_utc_iso('2026-10-11T00:00:00')


def test_taipei_date_roundtrip_crosses_utc_midnight():
    instant = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)
    assert V.taipei_date_from_instant(instant) == '2026-10-11'
    assert V.taipei_date_from_instant(instant.astimezone(timezone(timedelta(hours=-5)))) == '2026-10-11'
    millis = V.date_to_taipei_millis('2026-10-11')
    assert millis == int(instant.timestamp() * 1000)
    assert V.taipei_date_from_millis(millis) == '2026-10-11'
    assert V.taipei_date_from_instant(datetime(2026, 10, 10, 15, 59, 59, tzinfo=timezone.utc)) == '2026-10-10'
