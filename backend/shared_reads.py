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
MAX_BYTES=160_000_000
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
        hit=_entries.get(key)
        if hit and time.monotonic()-hit[0]<TTL:
            _entries.move_to_end(key)
            return hit[2]
        flight=_flights.setdefault(key,threading.Lock())
    with flight:
        with _guard:
            hit=_entries.get(key)
            if hit and time.monotonic()-hit[0]<TTL: return hit[2]
            generation=_generation
        fetched=fetch()
        size=sum(len(text) for _,text in fetched)
        with _guard:
            if generation==_generation:
                _entries[key]=(time.monotonic(),size,fetched)
                _entries.move_to_end(key)
                while len(_entries)>1 and sum(entry[1] for entry in _entries.values())>MAX_BYTES: _entries.popitem(last=False)
            if _flights.get(key) is flight: del _flights[key]
        return fetched


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
