from datetime import datetime, timedelta, timezone


class SystemClock:
    def now(self):
        return datetime.now(timezone.utc)


class FakeClock:
    """Injected clock; tests advance it instead of sleeping."""

    def __init__(self, start=None):
        self._now = start or datetime(2026, 10, 11, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def advance(self, seconds):
        self._now += timedelta(seconds=seconds)
