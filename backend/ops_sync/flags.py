"""Feature flags for ops_sync. Every flag defaults to False; live writes are hard-disabled."""
from dataclasses import dataclass

from .values import OpsError

FEATURE_OPS_SYNC = False
FEATURE_OPS_SYNC_MOCK_UI = False
FEATURE_OPS_SYNC_LARK_EVENTS = False
FEATURE_OPS_SYNC_LIVE_WRITES = False
FEATURE_LARK_AUTHORITATIVE_OPS = False   # gates read-only case/node projection of existing project state


@dataclass(frozen=True)
class OpsFlags:
    ops_sync: bool = False
    mock_ui: bool = False
    lark_events: bool = False
    live_writes: bool = False
    lark_authoritative_ops: bool = False


def resolve_flags(config=None):
    """Only the core and mock UI may be enabled by local configuration; events and live writes stay off."""
    config = config or {}
    return OpsFlags(ops_sync=config.get('FEATURE_OPS_SYNC') is True,
                    mock_ui=config.get('FEATURE_OPS_SYNC_MOCK_UI') is True,
                    lark_events=False, live_writes=False,
                    lark_authoritative_ops=config.get('FEATURE_LARK_AUTHORITATIVE_OPS') is True)


class LiveWritesDisabled(OpsError):
    code = 'live_writes_disabled'


class LiveLarkWriter:
    """Stub. Live ops writes are refused regardless of configuration; no network client is ever built."""

    def __init__(self, *args, **kwargs):
        raise LiveWritesDisabled('live ops writer is hard-disabled in this slice')
