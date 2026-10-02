"""Comment-scoped Lark notifications: durable, per recipient, fail closed."""
from urllib.parse import urlencode, urlsplit, urlunsplit
from datetime import datetime, timezone
from .workflow import find, require

MENTION_WINDOW_SECONDS = 60
MENTION_ACTOR_LIMIT = 20
MENTION_RECIPIENT_LIMIT = 10
MENTION_WORKSPACE_LIMIT = 100


def reserve_mentions(ws, actor, recipients, *, clock=None):
    """Reserve recipient deliveries in the caller's locked workspace transaction.

    A failed transaction rolls reservations back with the comment. Retries use
    the existing action receipt and therefore cannot reserve or enqueue twice.
    """
    if not recipients:
        return
    instant = clock or datetime.now(timezone.utc)
    cutoff = instant.timestamp() - MENTION_WINDOW_SECONDS
    recent = [r for r in ws.get('_mention_reservations', [])
              if isinstance(r.get('timestamp'), (int, float)) and cutoff < r['timestamp'] <= instant.timestamp()]
    require(sum(r['actor_id'] == actor['id'] for r in recent) + len(recipients) <= MENTION_ACTOR_LIMIT,
            '標註通知過於頻繁，請稍後再試（每人每分鐘 20 位收件人）', 429)
    require(len(recent) + len(recipients) <= MENTION_WORKSPACE_LIMIT, '公司標註通知達每分鐘上限，請稍後再試', 429)
    for recipient in recipients:
        require(sum(r['recipient_id'] == recipient for r in recent) < MENTION_RECIPIENT_LIMIT,
                '同事本分鐘收到的通知已達上限，請稍後再試', 429)
    ws['_mention_reservations'] = recent + [dict(actor_id=actor['id'], recipient_id=r, timestamp=instant.timestamp()) for r in recipients]


def person_verified(person,app_id):
    from .production_access import admitted
    return admitted(person,app_id)


def locate(state,payload):
    p=find(state['projects'],payload.get('project_id'),'案件')
    if payload.get('task_id'):
        n=find(p['nodes'],payload.get('node_id'),'節點'); target=find(n['tasks'],payload['task_id'],'任務')
    else: target=p
    comment=find(target['comments'],payload.get('comment_id'),'留言')
    return p,comment


def enqueue_mentions(ws,actor,p,n,t,comment,demo):
    from .operations import queue
    comment['notifications']=[]
    app_id=ws.get('people_directory_status',{}).get('app_id') or actor.get('identity_app_id')
    for recipient in comment['mentions']:
        person=find(ws['users'],recipient,'標註同事')
        receipt={'recipient_id':recipient,'status':'queued'}
        comment['notifications'].append(receipt)
        if not demo and not (person_verified(actor,app_id) and person_verified(person,app_id)):
            receipt.update(status='blocked',error='通知人員尚未核實同應用在職身分'); continue
        job=queue(ws,'mention',actor,{'comment_id':comment['id'],'project_id':p['id'],'node_id':n['id'] if n else None,'task_id':t['id'] if t else None,'recipient_id':recipient,'identity_app_id':app_id},'mention:'+comment['id']+':'+recipient)
        receipt['job_id']=job['id']


def check_notification(state,actor,payload,cfg,simulated):
    p,comment=locate(state,payload)
    recipient=find(state['users'],payload['recipient_id'],'標註同事')
    require(comment['author_id']==actor['id'] and recipient['id'] in comment.get('mentions',[]),'通知與原留言人員不符',403)
    require(actor.get('active',True) and recipient.get('active',True),'通知人員已停權',403)
    if not simulated:
        app_id=cfg.get('LARK_APP_ID')
        require(payload.get('identity_app_id')==app_id and person_verified(actor,app_id) and person_verified(recipient,app_id),'通知人員尚未核實同應用在職身分',403)
    return p,comment


def notification_text(p,comment,payload,cfg,actor):
    configured=cfg.get('PUBLIC_APP_URL') or cfg.get('LARK_REDIRECT_URI','')
    url=urlsplit(configured)
    require(url.scheme=='https' and url.netloc and not url.username,'正式工作台 HTTPS 網址尚未設定',503)
    path=url.path if cfg.get('PUBLIC_APP_URL') else '/'
    route={'view':'project','project':p['id'],'tab':'flow','comment':comment['id']}
    if payload.get('task_id'): route.update(node=payload['node_id'],task=payload['task_id'])
    link=urlunsplit((url.scheme,url.netloc,path,'',urlencode(route)))
    # Display names, project titles and comment bodies are editable text. Never
    # interpolate them into a trusted company-bot notification: Lark can turn
    # embedded URLs into convincing links even in a plain-text message.
    return f"你在詠翔工作台收到一則同事標註。請開啟工作台查看案件、留言及標註人。\n{link}"


def reflect(state,job,status,error=None,receipt=None):
    try: _,comment=locate(state,job['payload'])
    except Exception: return  # Missing historical comment must never cause a resend.
    target=next((x for x in comment.get('notifications',[]) if x.get('job_id')==job['id']),None)
    if target is None: return
    target['status']=status
    if error: target['error']=error
    else: target.pop('error',None)
    if receipt:
        target['simulated']=bool(receipt.get('simulated'))
        target['message_id']=receipt.get('message_id')
