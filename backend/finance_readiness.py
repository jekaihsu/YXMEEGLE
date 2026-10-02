"""Read-only financial closure predicates; no ledger, amount or payroll writes."""
from decimal import Decimal, InvalidOperation
from datetime import date,datetime,timezone,timedelta
from .sources import day,text

VERIFIED_CHECKS={'通過','檢核通過','核對通過','已核對','一致','完整','ok','pass','verified'}


def amount(value):
    if value is None or isinstance(value,bool) or not str(value).strip(): return None
    try: result=Decimal(str(value).replace(',','').strip())
    except (InvalidOperation,ValueError): return None
    return result if result.is_finite() and result>=0 else None


def quote_incoming(quote):
    f=quote.get('fields') or {};issues=[]
    if quote.get('source_missing'):issues.append('來源報價目前不存在，歷史收款資料不能作為現行結清依據')
    received=amount(f.get('累計已入帳'));billed=amount(f.get('累計已請款'));billable=amount(f.get('案件可請款總額'));unbilled=amount(f.get('可請款未請'))
    if f.get('案件已入帳') is not True:issues.append('來源未明確勾選案件已入帳')
    booked=day(f.get('入帳日期'))
    try:
        if not booked or date.fromisoformat(booked)>datetime.now(timezone(timedelta(hours=8))).date():issues.append('缺有效入帳日期或日期尚未到')
    except (ValueError,TypeError):issues.append('入帳日期無法核實')
    if text(f.get('入帳資料檢核')).strip().casefold() not in VERIFIED_CHECKS:issues.append('入帳資料檢核未明確通過')
    values={'累計已入帳':received,'累計已請款':billed,'案件可請款總額':billable,'可請款未請':unbilled}
    for key,value in values.items():
        if value is None:issues.append(f'{key}未提供有效金額')
    if all(v is not None for v in values.values()) and not (received==billed==billable and unbilled==0):issues.append('已入帳、已請款與可請款範圍不一致或仍有未請款')
    if not quote.get('id'):issues.append('來源報價識別缺失')
    return {'quote_id':quote.get('id'),'quote_code':quote.get('quote_code'),'source_url':quote.get('source_url'),
            'status':'settled' if not issues else 'unverified','missing':issues,'date':booked or None,
            'amounts':{k:str(v) if v is not None else None for k,v in values.items()},
            'basis':'same-source quote fields, compared independently; never summed across quotes'}


def incoming_readiness(p):
    quotes={};conflicts=[]
    for q in p.get('quotes',[]):
        ident=q.get('id')
        if ident in quotes and q.get('fields')!=quotes[ident].get('fields'):conflicts.append('同一報價來源識別有內容衝突')
        quotes[ident]=q
    rows=[quote_incoming(q) for q in quotes.values()]
    missing=list(dict.fromkeys(conflicts))
    if not rows:missing.append('尚無唯一關聯的來源報價收款資料')
    for row in rows:
        missing += [f"報價 {row.get('quote_code') or row.get('quote_id') or '未識別'}：{reason}" for reason in row['missing']]
    return {'status':'incoming_settled' if not missing else 'unverified','quotes':rows,'missing':missing,
            'scope':'receivables_only','aggregated_amount':None}


def payables_readiness(ws,p):
    from .native_requests import receipt_valid
    node=next((n for n in p['nodes'] if n['key']=='settlement'),None)
    if node:
        for item in reversed(ws.get('financial_requests',[])):
            if item.get('project_id')!=p['id'] or item.get('node_id')!=node['id'] or item.get('status')!='approved':continue
            declaration=item.get('payables_declaration')
            if declaration not in ('no_payables','all_settled'):continue
            if not item.get('evidence_ids') or not receipt_valid(ws,p,node,item,require_fresh=False):continue
            evidence=[]
            for ident in item['evidence_ids']:
                e=next((e for e in p.get('evidence',[]) if e['id']==ident),None)
                f=next((f for f in p.get('files',[]) if f['id']==ident),None)
                if e:
                    if e.get('withdrawn') or e.get('status')!='accepted':break
                    f=next((f for f in p.get('files',[]) if f['id']==e.get('file_id')),None) if e.get('file_id') else None
                    if e.get('file_id') and not f:break
                if f and (f.get('withdrawn') or f.get('storage')=='local' and f.get('remote_status')!='verified'):break
                if not e and not f:break
                evidence.append(ident)
            if len(evidence)!=len(item['evidence_ids']):continue
            return {'status':declaration,'request_id':item['id'],'missing':[],
                    'basis':'explicit PM/admin native-approved declaration with current evidence; not an inferred bank ledger'}
    return {'status':'unknown','request_id':None,'missing':['下包及其他應付款範圍尚未核對：需具佐證的已結清或無應付款共同確認'],
            'basis':'no authoritative declaration; empty local payment list is not zero liability'}


def financial_readiness(ws,p):
    incoming=incoming_readiness(p);payables=payables_readiness(ws,p)
    missing=incoming['missing']+payables['missing']
    return {'incoming':incoming,'payables':payables,'missing':missing,'ready':not missing,'readonly':True}
