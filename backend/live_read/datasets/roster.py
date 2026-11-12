"""Roster reads always renew per-person admission timestamps, even if unchanged."""
from . import DatasetRefresher, content_fingerprint


class RosterRefresher(DatasetRefresher):
    def __call__(self, wid):
        service, clients = self.reader()
        snapshots = []
        fetch = service.fetcher
        def capture(*args):
            snapshot = fetch(*args)
            snapshots.append(snapshot)
            return snapshot
        service.fetcher = capture
        status = service.sync(wid, None)
        return dict(fingerprint=content_fingerprint(snapshots[0]['people']),
                    fetched_at=status['last_success_at'], lark=self.metrics(clients))

    refresh = __call__
