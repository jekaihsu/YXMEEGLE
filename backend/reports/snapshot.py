"""Single-flight snapshots with bounded cold waits and stale reads."""
from concurrent.futures import ThreadPoolExecutor, Future
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import logging
from threading import Lock
import time
from fastapi import HTTPException
from . import compute


def setting(cfg, key, default, minimum, maximum):
    try: value=float(cfg.get(key, default))
    except (ValueError, TypeError): value=default
    return min(maximum,max(minimum,value)) if math.isfinite(value) else default

logger=logging.getLogger('backend.reports')


def ensure_visible_logs():
    # The app configures no logging, so INFO from this module would be dropped; only add a handler when nothing else did.
    if logger.level==logging.NOTSET: logger.setLevel(logging.INFO)
    if not logging.getLogger().handlers and not logger.handlers:
        handler=logging.StreamHandler();handler.setFormatter(logging.Formatter('%(levelname)s:     %(name)s %(message)s'));logger.addHandler(handler)

class SnapshotStore:
    def __init__(self, reader, cfg=None, *, clock=time.monotonic):
        cfg=cfg or {}; self.reader=reader;self.clock=clock
        self.ttl=setting(cfg,'REPORTS_TTL_SECONDS',300,1,86400)
        self.budget=setting(cfg,'REPORTS_COLD_WAIT_SECONDS',20,.01,60)
        self.base=cfg.get('LARK_REPORT_BASE_TOKEN',compute.BASE_TOKEN)
        self._lock=Lock();self._executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='reports')
        self._future=None;self._snapshot=None;self._last_request=None;self._retry_at=0;self._refresh_error=False

    def _build(self):
        started=time.monotonic()
        logger.info('reports snapshot build started')
        try:
            raw=self.reader.read()
            canonical=json.dumps({k:dict(v,records=sorted(v['records'],key=lambda r:r['record_id'])) for k,v in raw.items()},sort_keys=True,ensure_ascii=False,separators=(',',':'))
            fingerprint=hashlib.sha256(canonical.encode()).hexdigest()
            with self._lock: previous=self._snapshot
            data=previous['data'] if previous and previous['fingerprint']==fingerprint else compute.normalize(raw,self.base)
            gaps=previous['gaps'] if previous and previous['fingerprint']==fingerprint else {(endpoint,dept):compute.report_gaps(data,endpoint,dept) for endpoint in ('sources','review','review/rows','sales','assets','progress','progress/case') for dept in ('field','office','control')}
            current=dict(gaps=gaps,data=data,fingerprint=fingerprint,fetched_at=datetime.now(timezone.utc).isoformat(),at=self.clock(),cache=previous['cache'] if previous and previous['fingerprint']==fingerprint else OrderedDict(),pending=previous['pending'] if previous and previous['fingerprint']==fingerprint else {})
            with self._lock: self._snapshot=current;self._retry_at=0;self._refresh_error=False
            logger.info('reports snapshot ready tables=%s records=%s duration_ms=%.0f',len(raw),sum(len(t['records']) for t in raw.values()),(time.monotonic()-started)*1000)
            return current
        except Exception as exc:
            logger.warning('reports snapshot failed error_class=%s duration_ms=%.0f',type(exc).__name__,(time.monotonic()-started)*1000)
            with self._lock: self._retry_at=self.clock()+min(30,self.ttl);self._refresh_error=True
            raise

    def start(self, *, manual=False):
        with self._lock:
            if self._future is not None and not self._future.done(): return self._future
            now=self.clock()
            if manual and self._last_request is not None and now-self._last_request<60:
                raise HTTPException(429,'每分鐘僅能重新讀取一次')
            if not manual and now<self._retry_at: return self._future
            if manual: self._last_request=now
            self._future=self._executor.submit(self._build)
            return self._future

    def peek(self):
        with self._lock: return self._snapshot

    def get(self):
        with self._lock: current=self._snapshot
        if current is None or self.clock()-current['at']>=self.ttl:
            future=self.start()
            if current is None:
                try: current=future.result(timeout=self.budget)
                except TimeoutError:
                    if not future.done():
                        raise HTTPException(503,dict(detail='報表資料正在首次讀取，請稍候',warming=True,retry_after=5),headers={'Retry-After':'5'}) from None
                    raise HTTPException(503,dict(detail='報表來源暫時無法讀取',warming=False)) from None
                except Exception: raise HTTPException(503,dict(detail='報表來源暫時無法讀取',warming=False)) from None
        return current

    def meta(self, snapshot=None, endpoint='sources'):
        if snapshot is None:
            with self._lock: snapshot=self._snapshot
        if snapshot is None:
            return dict(fetched_at='',stale=True,refresh_error=self._refresh_error,snapshot='',gaps=[compute.gap('cold','報表來源正在讀取')])
        return dict(fetched_at=snapshot['fetched_at'],refresh_error=self._refresh_error,stale=self._refresh_error or self.clock()-snapshot['at']>=self.ttl,snapshot=snapshot['fingerprint'][:12],gaps=deepcopy(snapshot['gaps'][(endpoint,'field')]))

    def result(self, endpoint, params, *, snapshot=None):
        from .routes import parameters
        params=parameters(endpoint,params)
        if snapshot is None: snapshot=self.get()
        key=(endpoint,tuple(sorted(params.items())))
        with self._lock:
            result=snapshot['cache'].get(key)
            if result is not None: snapshot['cache'].move_to_end(key)
            pending=snapshot['pending'].get(key)
            owner=result is None and pending is None
            if owner: pending=Future();snapshot['pending'][key]=pending
        if result is None:
            if not owner: result=pending.result()
            else:
                try:
                    if endpoint=='sources': result=compute.sources(snapshot['data'],snapshot['fetched_at'])
                    else: result={'review':compute.review,'review/rows':compute.rows_report,'sales':compute.sales,'assets':compute.assets,'progress':compute.progress,'progress/case':compute.progress_case}[endpoint](snapshot['data'],**params)
                    with self._lock:
                        snapshot['cache'][key]=result
                        if len(snapshot['cache'])>512: snapshot['cache'].popitem(last=False)
                    pending.set_result(result)
                except BaseException as exc:
                    pending.set_exception(exc)
                    raise
                finally:
                    with self._lock: snapshot['pending'].pop(key,None)
        result=deepcopy(result)
        if endpoint=='sources':
            for table in result['tables']:
                if table['status']=='ok': table['fetched_at']=snapshot['fetched_at']
        meta=self.meta(snapshot,endpoint)
        meta['gaps']=deepcopy(snapshot['gaps'][(endpoint,params.get('dept','field'))])+result.pop('gaps',[])
        return dict(result,meta=meta)

    def close(self): self._executor.shutdown(wait=True)
