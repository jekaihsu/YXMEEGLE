"""Adapters from existing dataset services to the coordinator's callable contract."""
from copy import copy
import hashlib
import json

from ...lark_adapter import LarkAdapter
from ..client import ALLOWED_POSTS, LiveLarkClient


def content_fingerprint(rows):
    encoded = sorted(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                separators=(',', ':'), allow_nan=False) for row in rows)
    return 'sha256:' + hashlib.sha256(json.dumps(encoded).encode()).hexdigest()


class DatasetRefresher:
    allowed_posts = ALLOWED_POSTS

    def __init__(self, service, client_factory=LiveLarkClient):
        self.service, self.client_factory = service, client_factory

    def reader(self):
        service = copy(self.service)
        clients = []
        def adapter(cfg):
            client = self.client_factory(cfg, allowed_posts=self.allowed_posts)
            clients.append(client)
            return LarkAdapter('', client=client)
        service.adapter_factory = adapter
        return service, clients

    @staticmethod
    def metrics(clients):
        metrics = [client.metrics for client in clients]
        return {key: sum(m[key] for m in metrics) for key in ('calls', 'retries', 'duration_ms')}


def build_refreshers(sources, roster, attendance, *, client_factory=LiveLarkClient):
    from .sources import SourcesRefresher
    from .roster import RosterRefresher
    from .attendance import AttendanceRefresher
    return {'sources': SourcesRefresher(sources, client_factory),
            'roster': RosterRefresher(roster, client_factory),
            'attendance': AttendanceRefresher(attendance, client_factory)}
