"""Run with python -m backend.benchmark_reports --data /tmp/lark-docs/data."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import statistics
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient
from .reports.reader import FixtureReader
from .reports.routes import register


def cross_check(client, directory):
    raw=json.loads((Path(directory)/'外業工作單.json').read_text())['records']
    independent=Counter();undated=Counter();weeks=set();missing=0
    for row in raw:
        f=row['fields'];status=(f.get('檢核狀態') or '').strip()
        independent[{'已通過':'passed','已退回':'returned','待檢核':'pending'}.get(status,'unset')]+=1
        v=f.get('出工日期') or f.get('工作日期-薪資')
        if isinstance(v,list): v=v[0].get('text') if v else None
        if v is None:
            missing+=1;undated[{'已通過':'passed','已退回':'returned','待檢核':'pending'}.get(status,'unset')]+=1
            continue
        n=float(v)
        d=(datetime.fromtimestamp(n/1000,timezone(timedelta(hours=8))).date() if n>10000000 else datetime(1899,12,30).date()+timedelta(days=n))
        weeks.add((d-timedelta(days=d.weekday())).isoformat())
    observed=Counter()
    for week in sorted(weeks):
        response=client.get('/api/reports/review',params={'dept':'field','week':week})
        assert response.status_code==200
        kpi=response.json()['kpi']
        observed.update({k:kpi[k] for k in ('passed','returned','pending','unset')})
    assert independent==observed+undated,(independent,observed,undated)
    return dict(independent=dict(independent),endpoint=dict(observed),weeks=len(weeks),undated=missing,undated_statuses=dict(undated))


def run(directory, requests=300, rounds=5):
    app=FastAPI();store=register(app,lambda _:({'wid':'benchmark','mode':'lark'},{'id':'P01'}),{},reader=FixtureReader(directory))
    result={'requests_per_round':requests,'rounds':rounds,'errors':0,'endpoints':{}}
    with TestClient(app) as client:
        started=time.perf_counter();snapshot=store.get();result['cold_fixture_snapshot_ms']=(time.perf_counter()-started)*1000
        result['source_rows']={k:len(v) for k,v in snapshot['data']['tables'].items()}
        result['cross_check']=cross_check(client,directory)
        paths=['review','review/rows','sales','assets','progress']
        def stats(samples):
            return dict(p50_ms=statistics.median(samples),p95_ms=sorted(samples)[int(len(samples)*.95)-1],max_ms=max(samples))
        def weekly(path): return {'week':'2026-10-05'} if path in ('review','review/rows','progress') else {}
        for path in paths:
            warm=client.get('/api/reports/'+path,params=weekly(path))
            assert warm.status_code==200
            samples=[];sizes=[];batches=[]
            for _ in range(rounds):
                batch=[]
                for _ in range(requests):
                    started=time.perf_counter();response=client.get('/api/reports/'+path,params=weekly(path))
                    elapsed=(time.perf_counter()-started)*1000
                    assert response.status_code==200,response.text
                    body=response.json();assert body['meta']['snapshot']
                    if 'items' in body: assert len(body['items'])<=50
                    batch.append(elapsed);sizes.append(len(response.content))
                samples.extend(batch);batches.append(dict(p50_ms=statistics.median(batch),p95_ms=sorted(batch)[int(len(batch)*.95)-1]))
            misses=[]
            for i in range(max(300,requests)):
                weeks=sorted(w for w in snapshot['data']['indices']['field'] if w)
                params={'week':weeks[i%len(weeks)] if weeks else '2026-10-05'} if path in ('review','review/rows','progress') else {}
                if path!='review':
                    from .reports.routes import SORTS
                    params.update(sort=SORTS[path][i%len(SORTS[path])],order='asc' if i%2 else 'desc',offset=i%100,limit=1+i%200)
                if path.startswith('review'):
                    params.update(dept=('field','office','control')[i%3])
                    if i%4==0: params['group']=snapshot['data']['reviews']['field'][i%len(snapshot['data']['reviews']['field'])]['group']
                if path=='sales' and i%4==0: params['status']='未填'
                if path=='review/rows' and i%5==0: params['status']=('passed','returned','pending')[i%3]
                if path=='assets': params.update(kind=('vehicle','instrument')[i%2],**{'from':'2026-01-01','to':(datetime(2026,10,15)-timedelta(days=i%100)).date().isoformat()})
                with store._lock: snapshot['cache'].clear()
                started=time.perf_counter();response=client.get('/api/reports/'+path,params=params)
                misses.append((time.perf_counter()-started)*1000)
                assert response.status_code==200,response.text
                assert response.json()['meta']['snapshot']
            result['endpoints'][path]=dict(hit=stats(samples),miss=stats(misses),miss_requests=len(misses),p50_ms=statistics.median(samples),p95_ms=sorted(samples)[int(len(samples)*.95)-1],payload_bytes=max(sizes),rounds=batches)
    store.close();return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--data',required=True);parser.add_argument('--requests',type=int,default=300);parser.add_argument('--rounds',type=int,default=5)
    args=parser.parse_args();print(json.dumps(run(args.data,args.requests,args.rounds),indent=2))
