"""Management actions remain available while learning is disabled."""
from copy import deepcopy
from datetime import date, time
from .workflow import require, find, uid, now, event
from .operations import active_user, capable, digest
from .policy import upgrade


def apply_management(ws,user,body):
    from .input_validation import validate_action
    validate_action(body)
    action=body['action']; data=body.get('payload') or {}
    if action not in ('schedule_set','quote_review'): return False
    upgrade(ws); active_user(ws,user['id'])
    if action=='schedule_set':
        require(capable(user,'calendar_edit'),'需要班表維護權限',403)
        ident=str(data.get('user_id','')); active_user(ws,ident)
        try:
            day=date.fromisoformat(str(data.get('day',''))).isoformat()
            value=time.fromisoformat(str(data.get('end_time','')))
            require(value.tzinfo is None and value.second==0 and value.microsecond==0,'下班時間請用 HH:MM',422)
        except ValueError: require(False,'請提供有效日期與 HH:MM 下班時間',422)
        prior=next((s for s in ws['work_schedules'] if s['user_id']==ident and s['day']==day),None)
        history=deepcopy(prior.get('history',[])) if prior else []
        if prior: history.append({k:v for k,v in prior.items() if k!='history'})
        row=dict(id=prior['id'] if prior else uid(),user_id=ident,day=day,end_time=value.strftime('%H:%M'),version=prior['version']+1 if prior else 1,active=True,basis='company_schedule',source_url=str(data.get('source_url','')),updated_by=user['id'],updated_at=now(),history=history)
        if prior: prior.update(row)
        else: ws['work_schedules'].append(row)
    elif action=='quote_review':
        p=find(ws['projects'],body.get('project_id'),'案件'); quote=find(p['quotes'],data.get('quote_id'),'報價')
        seat=data.get('seat'); require(seat in ('pm','sales'),'需 PM 或業務確認',422)
        principal=p.get('pm_id') if seat=='pm' else p.get('sales_id')
        require(principal and user['id']==principal,'不是此案指定確認者',403)
        classification=data.get('classification'); require(classification in ('effective','duplicate','additional'),'報價認定類型錯誤',422)
        fingerprint=digest(quote)
        principals={'pm':p.get('pm_id'),'sales':p.get('sales_id')}
        require(all(principals.values()) and principals['pm']!=principals['sales'],'報價需指定不同的 PM 與業務',409)
        for ident in principals.values(): active_user(ws,ident)
        for previous in p['quote_reviews']:
            if (previous.get('quote_id')==quote['id'] and previous.get('source_hash')==fingerprint
                    and previous.get('classification')==classification and previous.get('status')=='pending'
                    and previous.get('principal_ids')!=principals):
                previous.update(status='invalidated',invalidated_at=now(),invalidated_reason='PM 或業務職責已改派，原投票失效')
        review=next((r for r in p['quote_reviews'] if r['quote_id']==quote['id'] and r['source_hash']==fingerprint and r['classification']==classification and r.get('principal_ids')==principals and r['status']=='pending'),None)
        if not review:
            review=dict(id=uid(),quote_id=quote['id'],source_hash=fingerprint,classification=classification,principal_ids=principals,status='pending',votes=[],created_at=now()); p['quote_reviews'].append(review)
        require(not any(v['actor_id']==user['id'] and v['seat']!=seat for v in review['votes']),'兩方必須不同人',409)
        review['votes']=[v for v in review['votes'] if v['seat']!=seat]+[{'seat':seat,'actor_id':user['id'],'at':now()}]
        if ({v.get('seat'):v.get('actor_id') for v in review['votes']}==principals
                and len({v.get('actor_id') for v in review['votes']})==2):
            for previous in p['quote_reviews']:
                if previous['quote_id']==quote['id'] and previous['id']!=review['id'] and previous['status']=='approved': previous['status']='superseded'
            review['status']='approved'
    event(ws,user,action,body.get('project_id'),message='保存報價或班表決策')
    return True
