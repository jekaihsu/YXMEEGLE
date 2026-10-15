"""Single-flight snapshots with bounded cold waits and stale reads."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from threading import Lock
import time
from fastapi import HTTPException
from . import compute


def setting(cfg, key, default, minimum, maximum):
    try: value=float(cfg.get(key, default))
    except (ValueError, TypeError): value=default
    return min(maximum,max(minimum,value)) if math.isfinite(value) else default

class SnapshotStore:
    def __init__(self, reader, cfg=None, *, clock=time.monotonic):
        cfg=cfg or {}; self.reader=reader;self.clock=clock
        self.ttl=setting(cfg,'REPORTS_TTL_SECONDS',300,1,86400)
        self.budget=setting(cfg,'REPORTS_COLD_WAIT_SECONDS',10,.01,60)
        self.base=cfg.get('LARK_REPORT_BASE_TOKEN',compute.BASE_TOKEN)
        self._lock=Lock();self._executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='reports')
        self._future=None;self._snapshot=None;self._last_request=None;self._retry_at=0

    def _build(self):
        try:
            raw=self.reader.read()
            canonical=json.dumps({k:dict(v,records=sorted(v['records'],key=lambda r:r['record_id'])) for k,v in raw.items()},sort_keys=True,ensure_ascii=False,separators=(',',':'))
            fingerprint=hashlib.sha256(canonical.encode()).hexdigest()
            with self._lock: previous=self._snapshot
            data=previous['data'] if previous and previous['fingerprint']==fingerprint else compute.normalize(raw,self.base)
            gaps=previous['gaps'] if previous and previous['fingerprint']==fingerprint else {endpoint:compute.report_gaps(data,endpoint) for endpoint in ('sources','review','review/rows','sales','assets','progress')}
            current=dict(gaps=gaps,data=data,fingerprint=fingerprint,fetched_at=datetime.now(timezone.utc).isoformat(),at=self.clock(),cache=previous['cache'] if previous and previous['fingerprint']==fingerprint else {})
            with self._lock: self._snapshot=current;self._retry_at=0
            return current
        except Exception:
            with self._lock: self._retry_at=self.clock()+min(30,self.ttl)
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

    def get(self):
        with self._lock: current=self._snapshot
        if current is None or self.clock()-current['at']>=self.ttl:
            future=self.start()
            if current is None:
                try: current=future.result(timeout=self.budget)
                except Exception: raise HTTPException(503,'報表來源尚未就緒，請稍後再試') from None
        return current

    def meta(self, snapshot=None, endpoint='sources'):
        if snapshot is None:
            with self._lock: snapshot=self._snapshot
        if snapshot is None:
            return dict(fetched_at='',stale=True,snapshot='',gaps=[compute.gap('cold','報表來源正在讀取')])
        return dict(fetched_at=snapshot['fetched_at'],stale=self.clock()-snapshot['at']>=self.ttl,snapshot=snapshot['fingerprint'][:12],gaps=deepcopy(snapshot['gaps'][endpoint]))

    def result(self, endpoint, params):
        snapshot=self.get();key=(endpoint,tuple(sorted(params.items())))
        with self._lock: result=snapshot['cache'].get(key)
        if result is None:
            if endpoint=='sources': result=compute.sources(snapshot['data'],snapshot['fetched_at'])
            else: result={'review':compute.review,'review/rows':compute.rows_report,'sales':compute.sales,'assets':compute.assets,'progress':compute.progress}[endpoint](snapshot['data'],**params)
            with self._lock:
                if len(snapshot['cache'])>=512: snapshot['cache'].clear()
                snapshot['cache'][key]=result
        result=deepcopy(result)
        if endpoint=='sources':
            for table in result['tables']:
                if table['status']=='ok': table['fetched_at']=snapshot['fetched_at']
        meta=self.meta(snapshot,endpoint)
        meta['gaps']=compute.report_gaps(snapshot['data'],endpoint,params.get('dept','field'))
        return dict(result,meta=meta)

    def close(self): self._executor.shutdown(wait=True)
