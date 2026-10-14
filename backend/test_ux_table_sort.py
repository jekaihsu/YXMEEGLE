from sqlalchemy import select
from datetime import datetime, timezone

from .company_dashboard import actual_date, overview
from .confirmation_list import build_confirmation_list
from .test_confirmation_list import entity, state


def test_taipei_calendar_dates_and_invalid_values():
    assert [str(actual_date(v)) if actual_date(v) else None for v in
            ['2026-10-14T18:00:00Z', '2026-10-15', 1791993600000, '', None, '2026-02-30']] == [
                '2026-10-15', '2026-10-15', '2026-10-15', None, None, None]


def test_version_numbers_are_numeric_with_unknown_last_in_both_directions():
    st = state(source_confirmations=[entity('a','C',version='10'),entity('b','C',version='2'),
                                   entity('c','C',version='2.5'),entity('d','C')])
    assert [r['confirmation_version']['value'] for r in build_confirmation_list(st,sort={'column':'confirmation_version','direction':'asc'})['rows']] == ['2','2.5','10',None]
    assert [r['confirmation_version']['value'] for r in build_confirmation_list(st,sort={'column':'confirmation_version','direction':'desc'})['rows']] == ['10','2.5','2',None]


def test_source_creation_order_uses_instants_and_keeps_unknown_last():
    st=state(source_confirmations=[entity('a','A'),entity('b','B'),entity('c','C')])
    st['source_confirmations'][0]['fields']['建立時間']='2026-10-15T00:00:00+08:00'
    st['source_confirmations'][1]['fields']['建立時間']='2026-10-14T18:00:00Z'
    assert [r['case_number'] for r in build_confirmation_list(st)['rows']] == ['B','A','C']


def test_cursors_reject_identity_filter_and_snapshot_changes():
    st=state()
    owner={'tenant':'t','identity_app':'a','open_id':'u1','workspace':'w','authz_version':1}
    cursor=build_confirmation_list(st,limit=1,cursor_context=owner)['next_cursor']
    assert build_confirmation_list(st,cursor=cursor,cursor_context={**owner,'open_id':'u2'})['error']=='cursor_filter_mismatch'
    assert build_confirmation_list(st,cursor=cursor,cursor_context=owner,q='C100')['error']=='cursor_filter_mismatch'
    st['source_confirmations'][0]['fields']['工程名稱']='changed'
    assert build_confirmation_list(st,cursor=cursor,cursor_context=owner)['error']=='cursor_filter_mismatch'


def test_production_cursors_require_authorization_context():
    page=build_confirmation_list(state(environment='production'),limit=1)
    assert page['next_cursor'] is None
    assert page['pagination_available'] is False


def test_partial_counts_describe_loaded_population_without_claiming_total():
    page=build_confirmation_list(state(source_status={'status':'partial'}),limit=2)
    assert page['totals']=={'matching':6,'loaded':2,'authorized_source':6}
    assert page['total_count'] is None
    assert page['count_scope']=='authorized_source_versions'
    assert page['filter_scope']=='matching_loaded_versions'
    assert page['complete'] is False


def test_company_sort_happens_before_paging_and_local_due_is_labelled():
    def project(pid,due):
        return {'id':pid,'code':pid,'source_kind':'lark','case_type':'formal','execution_allowed':True,
                'nodes':[{'key':'field','tasks':[{'status':'pending','due_date':due}]}]}
    st={'source_status':{'status':'partial'},'projects':[project('C',None),project('B','2026-10-16'),project('A','2026-10-14')]}
    page=overview(st,limit=1,clock=datetime(2026,10,15,tzinfo=timezone.utc))
    assert [r['code'] for r in page['cases']]==['A']
    assert page['cases'][0]['deadline_basis']=='local_workflow'
    assert page['total_count'] is None
    assert page['pagination']['total']==3
    assert [r['code'] for r in overview(st,offset=1,limit=2,clock=datetime(2026,10,15,tzinfo=timezone.utc))['cases']]==['B','C']


def test_shell_default_due_sort_puts_overdue_cases_first(tmp_path):
    from sqlalchemy import update
    from . import index_tables
    from .models import ProjectIndex
    from .test_perf_budget import scaled_client
    from .test_shell import ON
    with scaled_client(tmp_path, 4, **ON) as (app, client):
        with app.state.sessions.begin() as db:
            rows = db.scalars(select(ProjectIndex).order_by(ProjectIndex.project_id)).all()
            ids = [r.project_id for r in rows]
            for r, due in zip(rows, ['2026-12-01', '2026-11-01', '2026-10-01', '']):
                r.due_date = due
            ti = index_tables.tables(ProjectIndex)[1]
            db.execute(update(ti).where(ti.c.project_id == ids[0]).values(status='in_progress', due_date='2000-01-01'))
            db.execute(update(ti).where(ti.c.project_id.in_(ids[1:])).values(status='completed'))
        page = client.get('/api/projects', params={'view': 'overview', 'tab': 'all', 'sort': 'due', 'dir': 'asc', 'limit': 10}).json()
        assert [p['id'] for p in page['items']] == [ids[0], ids[2], ids[1], ids[3]]
