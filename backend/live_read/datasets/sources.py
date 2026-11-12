"""Refresh complete sources, skipping workspace projection when content is equal."""
from . import DatasetRefresher
from ..fingerprint import fingerprint


class SourcesRefresher(DatasetRefresher):
    def __call__(self, wid):
        service, clients = self.reader()
        snapshot = service.sync(wid, None, skip_unchanged=True)
        return dict(fingerprint=fingerprint(snapshot), fetched_at=snapshot['last_sync'],
                    lark=self.metrics(clients))

    refresh = __call__
