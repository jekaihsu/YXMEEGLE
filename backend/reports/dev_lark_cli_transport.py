"""Development-only CLI bridge. Never imported by the application."""
import json
import random
import subprocess
import threading
import time
import httpx


class LarkCliTransport(httpx.BaseTransport):
    def __init__(self):
        self.lock=threading.Lock()
        self.metrics=[]

    def handle_request(self, request):
        if request.url.path=='/open-apis/auth/v3/tenant_access_token/internal':
            return httpx.Response(200,json={'code':0,'tenant_access_token':'cli-managed','expire':7200})
        if request.method!='GET': raise RuntimeError('CLI bridge only permits GET')
        path=request.url.path.removeprefix('/open-apis')
        params=dict(request.url.params)
        started=time.perf_counter()
        with self.lock:
            for attempt in range(8):
                result=subprocess.run(['lark-cli','api','GET',path,'--params',json.dumps(params,ensure_ascii=False),'--as','bot'],capture_output=True,text=True,timeout=120)
                try: body=json.loads(result.stdout)
                except ValueError: body={}
                diagnostic=result.stderr+result.stdout
                if (result.returncode and '429' in diagnostic) or body.get('code') in (99991400,99991401) or body.get('status')==429:
                    time.sleep(min(30,2**attempt)+random.random());continue
                if result.returncode or not body: raise RuntimeError('CLI read failed without usable JSON')
                payload=json.dumps(body,ensure_ascii=False).encode()
                self.metrics.append(dict(path=path,bytes=len(payload),seconds=time.perf_counter()-started,projected='field_names' in params))
                return httpx.Response(200,content=payload)
        raise RuntimeError('CLI rate limit retry budget exhausted')


def configuration():
    return {'LARK_APP_ID':'cli-managed','LARK_APP_SECRET':'cli-managed','LARK_LIVE_READ_BUDGET_SECONDS':'600','LARK_LIVE_READ_LEASE_SECONDS':'700'}
