import pytest
from sqlalchemy.exc import OperationalError
from .database_startup import initialize


def test_database_retries_back_off_and_recover():
    attempts, delays = [], []
    def operation():
        attempts.append(1)
        if len(attempts) < 9:
            raise OperationalError('connect', {}, RuntimeError('offline'))
        return 'ready'
    assert initialize(operation, sleep=delays.append) == 'ready'
    assert delays == [1, 2, 4, 8, 16, 30, 30, 30]


def test_database_does_not_retry_programming_errors():
    def operation():
        raise ValueError('bad configuration')
    with pytest.raises(ValueError):
        initialize(operation)
