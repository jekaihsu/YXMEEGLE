"""Issue #49: audit pagination reads bounded batches, not the full history."""
import time
from sqlalchemy import event
from backend import storage
from backend.app import AuditRow
from backend.test_public_case_http_boundaries import isolated_http  # noqa: F401 (fixture)

WID='lark-boundary'


def _seed(app,n,project='p2',noise_every=0):
    with app.state.sessions.begin() as db:
        for i in range(n):
            other=noise_every and i%noise_every!=0
            db.add(AuditRow(id=f'syn-{i:05d}',workspace_id=WID,actor_id='u-manager',action='task_update',
                created_at=f'2026-01-01T00:{i//3600:02d}:{(i//60)%60:02d}:{i%60:02d}+00:00',
                data={'result':'success','project_id':'p-other' if other else project,'changes':[]}))


def _count_selects(app):
    stmts=[]
    def hook(conn,cur,statement,params,ctx,many):
        if 'FROM action_audit' in statement: stmts.append((statement,params))
    event.listen(app.state.engine,'before_cursor_execute',hook)
    return stmts,lambda:event.remove(app.state.engine,'before_cursor_execute',hook)


def test_small_page_reads_bounded_rows_and_every_select_has_limit(isolated_http):
    app,client,_,_=isolated_http
    _seed(app,1500)
    stmts,stop=_count_selects(app)
    body=client.get('/api/audit?limit=1').json(); stop()
    assert len(body['items'])==1 and body['has_more'] is True
    assert stmts and all('LIMIT' in s for s,_ in stmts) and len(stmts)<=2
    stmts,stop=_count_selects(app)
    hist=client.get('/api/admin/audit/history?limit=1').json(); stop()
    assert len(hist['items'])==1 and all('LIMIT' in s for s,_ in stmts) and len(stmts)<=2


def test_pages_are_complete_ordered_and_visibility_safe_across_batches(isolated_http):
    app,client,_,_=isolated_http
    # sparse matches force multiple keyset batches; old-case rows (p1) must never surface
    _seed(app,950,project='p2',noise_every=7)
    expected=sorted([f'syn-{i:05d}' for i in range(950) if i%7==0],reverse=True)
    got=[];offset=0
    while True:
        page=client.get(f'/api/audit?project_id=p2&offset={offset}&limit=30').json()
        got+= [r['id'] for r in page['items'] if r['id'].startswith('syn-')]
        if not page['has_more']: break
        offset+=30
    assert got==expected
    assert 'OLD_CASE_SENTINEL' not in client.get('/api/audit?limit=100').text
    hist=[];offset=0
    while True:
        page=client.get(f'/api/admin/audit/history?project_id=p2&offset={offset}&limit=100').json()
        hist+=[r['id'] for r in page['items'] if r['id'].startswith('syn-')]
        if not page['has_more']: break
        offset+=100
    assert hist==expected


def test_non_manager_restricted_actions_filtered_in_sql_not_after_limit(isolated_http):
    app,client,_,signin=isolated_http
    with app.state.sessions.begin() as db:  # newest rows are admin actions by someone else
        for i in range(250):
            db.add(AuditRow(id=f'zz-{i:04d}',workspace_id=WID,actor_id='u-manager',action='admin_x',
                created_at=f'2027-01-01T00:00:{i%60:02d}+00:00',data={'result':'success','changes':[]}))
    signin('u-pm')
    body=client.get('/api/audit?limit=5').json()
    assert body['items'] and all(not r['action'].startswith('admin_') for r in body['items'])


def test_prefix_prefilter_escapes_like_wildcards(isolated_http):
    app,client,_,signin=isolated_http
    # 'admin_' / 'people_' contain LIKE wildcards; adminX*/peopleX* are not restricted by Python startswith
    with app.state.sessions.begin() as db:
        for i,action in enumerate(('adminXfoo','peopleXbar','admin_real','people_real')):
            db.add(AuditRow(id=f'wc-{i}',workspace_id=WID,actor_id='u-manager',action=action,
                created_at=f'2027-02-01T00:00:{i:02d}+00:00',data={'result':'success','changes':[]}))
    signin('u-pm')
    ids={r['id'] for r in client.get('/api/audit?limit=100').json()['items']}
    assert {'wc-0','wc-1'}<=ids and not {'wc-2','wc-3'}&ids
