"""One shared fetch of large, data-only workspace kinds for concurrent case-scoped reads.

Case reads of one workspace version repeat the same large fetch. Readers share one fetch of the raw JSON text
per workspace, version and project scope; each reader still decodes its own copy.
"""
import threading
import time
from collections import OrderedDict

# Only large, data-only kinds are shared. Anything that carries authority (users and their capabilities, approvals,
# delegations) is always read fresh.
KINDS=frozenset({'source_quotes','source_confirmations','contract_items'})
TTL=30.0
MAX_BYTES=32_000_000
MAX_ENTRIES=16
_guard=threading.Lock()
_entries=OrderedDict()
_flights={}
_generation=0


def invalidate(wid):
    """Forget cached rows of one workspace (every workspace when wid is None); an in-flight fetch will not be stored."""
    global _generation
    with _guard:
        _generation+=1
        for key in [k for k in _entries if wid is None or k[0]==wid]: del _entries[key]


def rows(key,fetch):
    if key[1] is None: return fetch()
    with _guard:
        now=time.monotonic()
        for expired in [k for k,v in _entries.items() if now-v[0]>=TTL]:
            del _entries[expired]
        hit=_entries.get(key)
        if hit and time.monotonic()-hit[0]<TTL:
            _entries.move_to_end(key)
            return hit[2]
        flight=_flights.setdefault(key,threading.Lock())
    from .request_timing import measure
    with measure('lockwait'):
        flight.acquire()
    try:
        with _guard:
            hit=_entries.get(key)
            if hit and time.monotonic()-hit[0]<TTL: return hit[2]
            generation=_generation
        try:
            fetched=fetch()
            size=sum(len(text.encode('utf-8')) for _,text in fetched)
            with _guard:
                if generation==_generation and size<=MAX_BYTES:
                    _entries[key]=(time.monotonic(),size,fetched)
                    _entries.move_to_end(key)
                    while len(_entries)>MAX_ENTRIES or sum(entry[1] for entry in _entries.values())>MAX_BYTES:
                        _entries.popitem(last=False)
            return fetched
        finally:
            with _guard:
                if _flights.get(key) is flight: del _flights[key]

    finally:
        flight.release()


def drop_after_commit(db,wid):
    """Only the commit makes written rows true, so shared rows are dropped then; a reader may refill old rows while the transaction is open."""
    from sqlalchemy import event
    pending=db.info.setdefault('shared_reads_wids',set())
    if not pending:
        def committed(session):
            for item in session.info.pop('shared_reads_wids',()): invalidate(item)
        try: event.listen(db,'after_commit',committed,once=True)
        except Exception:
            invalidate(wid)
            return
    pending.add(wid)
