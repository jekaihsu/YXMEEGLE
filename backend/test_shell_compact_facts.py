"""Compact shell cards and task facts retain full-workspace meaning and privacy."""
import json

from .test_home_executable_tasks import AS_OF, OTHER, VIEWER, home_client, shape, task


def test_compact_shell_keeps_canonical_reasons_dates_and_status(tmp_path, monkeypatch):
    def mutate(state):
        shape(state)
        live=state['projects'][1]
        node=live['nodes'][0]
        paused=task('assigned-paused',VIEWER,'2026-10-01','paused')
        paused['original_due_date']=None
        correction=task('assigned-returned',VIEWER,'2026-10-05','rework')
        node['tasks'].extend([paused,correction])
        state.setdefault('events',[]).extend([
            dict(id='pause-fact',project_id=live['id'],node_id=node['id'],task_id=paused['id'],
                 action='task_pause_for_change',message='Verified scope pause',created_at='2026-10-06T09:00:00+08:00'),
            dict(id='return-fact',project_id=live['id'],node_id=node['id'],task_id=correction['id'],
                 action='task_return',message='Correct survey sheet',created_at='2026-10-06T10:00:00+08:00'),
            dict(id='other-person-fact',project_id=live['id'],node_id=node['id'],task_id='lv-other',
                 action='task_return',message='PRIVATE COWORKER REASON',created_at='2026-10-06T11:00:00+08:00'),
            dict(id='other-project-fact',project_id='p004',node_id='p004-sales',task_id='foreign-task',
                 action='task_return',message='PRIVATE OTHER PROJECT REASON',created_at='2026-10-06T12:00:00+08:00'),
        ])
    with home_client(tmp_path,monkeypatch,mutate) as client:
        full=client.get('/api/workspace').json()
        shell=client.get('/api/workspace?scope=shell').json()
        assert shell['scope']=='shell' and full['as_of'][:10]==shell['as_of'][:10]==AS_OF
        full_projects={p['id']:p for p in full['projects']}
        for card in shell['projects']:
            assert card['status']==full_projects[card['id']]['execution_status']
            assert 'execution_status' not in card  # one canonical status on compact cards

        full_tasks={t['id']:t for p in full['projects'] for n in p['nodes'] for t in n['tasks']}
        waiting={row['task_id']:row for row in shell['home_waiting']}
        for ident,reason in [('assigned-paused','Verified scope pause'),('assigned-returned','Correct survey sheet')]:
            full_detail=full_tasks[ident]['home_detail']
            compact=waiting[ident]['detail']
            assert waiting[ident]['reason']==full_detail['reason']==reason
            assert compact['kind']==full_detail['kind']
            assert compact['risk']==full_detail['risk']
            assert compact['blockers']==full_detail['blockers']
            assert 'task_id' not in compact and 'title' not in compact
        risk=waiting['assigned-paused']['detail']['risk']
        assert risk['original_due_date'] is None and risk['current_due_date']=='2026-10-01'
        assert risk['estimated_due_date'] is None and risk['overdue_calendar_days']==6
        assert waiting['assigned-paused']['detail']['pause']['source']=='task_pause_event'
        assert waiting['assigned-returned']['detail']['correction']['source']=='task_return_event'
        assert full_tasks['lv-other'].get('home_detail') is None
        shell_text=json.dumps(shell,ensure_ascii=False)
        assert 'PRIVATE COWORKER REASON' not in shell_text
        assert 'PRIVATE OTHER PROJECT REASON' not in shell_text
