"""Retry unavailable databases without restarting the web/worker supervisor."""
import logging
import time
from sqlalchemy.exc import OperationalError


def initialize(operation, *, sleep=time.sleep):
    delay = 1
    while True:
        try:
            return operation()
        except OperationalError:
            logging.getLogger(__name__).warning('database_startup_unavailable retry_seconds=%s', delay)
            sleep(delay)
            delay = min(delay * 2, 30)
