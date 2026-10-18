"""Home cards projected from cached reports on one snapshot."""
from collections.abc import Callable
from copy import deepcopy
from typing import NamedTuple
from fastapi import HTTPException
from .models import HomeResponse, Meta


class Part(NamedTuple):
    name: str
    sources: tuple[tuple[str,dict], ...]
    project: Callable[[list[dict]],dict]
    failure: str


def pick(result, *keys): return {key:result[key] for key in keys}


def unique_gaps(reports):
    gaps={}
    for report in reports:
        for gap in report['meta']['gaps']: gaps.setdefault(gap['id'],gap)
    return list(gaps.values())


def asset_cards(results):
    cards={}
    for kind,report in zip(('instrument','vehicle'),results):
        other={'instrument':'vehicle','vehicle':'instrument'}[kind]
        gaps=[gap for gap in unique_gaps([report]) if not gap['id'].startswith((other+'-','asset-'+other+'-')) and gap['id']!='source-'+other]
        cards[kind]=dict(pick(report,'kpi','by_category'),gaps=gaps)
    return cards


def sales_card(results):
    report=results[0]
    rows=[row for row in report['items'] if row['receivable'] is not None and row['receivable']>0]
    return dict(pick(report,'kpi','by_status'),top_receivable=sorted(rows,key=lambda row:row['receivable'],reverse=True)[:5])


PARTS=(
    Part('quality',(('review',{'dept':'field','weeks':12}),),lambda r:pick(r[0],'kpi','kpi_prev','trend','by_group','control'),'外業品質報表暫時無法讀取。'),
    Part('quality_office',(('review',{'dept':'office','weeks':12}),),lambda r:pick(r[0],'kpi'),'內業品質報表暫時無法讀取。'),
    Part('sales',(('sales',{'sort':'receivable','order':'desc','limit':200}),),sales_card,'業務報表暫時無法讀取。'),
    Part('progress',(('progress',{'dept':'field','scope':'week'}),),lambda r:pick(r[0],'week','basis','kpi','by_group'),'外業進度報表暫時無法讀取。'),
    Part('assets',(('assets',{'kind':'instrument'}),('assets',{'kind':'vehicle'})),asset_cards,'資產報表暫時無法讀取。'),
)


def compose(result: Callable[[str,dict],dict], meta: Meta, week: str) -> HomeResponse:
    meta=deepcopy(meta);gaps={};cards={}
    for part in PARTS:
        reports=[]
        try:
            for endpoint,params in part.sources:
                report=result(endpoint,dict(params,week=week) if endpoint in ('review','progress') else dict(params))
                reports.append(report)
                for gap in report['meta']['gaps']: gaps.setdefault(gap['id'],gap)
            cards[part.name]=part.project(reports)
            if part.name!='assets': cards[part.name]['gaps']=unique_gaps(reports)
        except HTTPException:
            raise
        except Exception:
            cards[part.name]=None
            ident='home-'+part.name+'-failed'
            gaps[ident]=dict(id=ident,severity='warn',message=part.failure)
    meta['gaps']=list(gaps.values())
    return dict(meta=meta,week=week,**cards)
