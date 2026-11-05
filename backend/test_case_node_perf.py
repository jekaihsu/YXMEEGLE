"""The batched node response derives the chain once, preserving detail authority."""
from unittest.mock import patch

from .node_assignment import views, service
from .test_node_assignment_routes import h, view  # noqa: F401


def test_overview_derives_one_case_and_embeds_all_nodes(h):
    with patch.object(views, 'case_view', wraps=views.case_view) as derive, patch.object(service, 'case_view', derive):
        body = view(h)
    assert derive.call_count == 1, 'one case projection, not one projection per node'
    assert len(body['node_details']) == 9
    for node in body['nodes']:
        detail = view(h, key=node['key'])
        assert body['node_details'][node['key']] == {k: detail[k] for k in ('tasks', 'assignable_people')}
        assert body['can'][node['key']] == detail['can']
    assert not h.fake.writes()


def test_task_link_association_linear_budget():
    from .sop_import.read_links import links_by_task
    class Link:
        reads = 0
        def __init__(self, task_id):
            self._task_id = task_id
        @property
        def task_id(self):
            Link.reads += 1
            return self._task_id
    rows = [Link(str(i // 3)) for i in range(30_000)]
    grouped = links_by_task(rows)
    assert Link.reads == len(rows)
    assert grouped['9999'] == rows[-3:]
    assert grouped['unknown'] == []


def test_first_screen_waits_for_one_current_node_capture(h):
    from .read_snapshots import capture
    token = capture.set({'wid': 'lark-company', 'project_id': 'p1'})
    try:
        first = view(h)
        h.clock[0] += 61
        current = view(h)
        assert current['stale'] is False, 'a successful first-screen capture must not strand stale controls'
        assert current['fetched_at'] != first['fetched_at']
    finally:
        capture.reset(token)


def test_first_screen_workspace_blob_read_budget(tmp_path):
    from sqlalchemy import event
    from .test_perf_budget import scaled_client
    with scaled_client(tmp_path, 2, WORKSPACE_SHELL_ENABLED='true', INDEX_TABLES_ENABLED='true') as (app, client):
        wide = []
        def observe(conn, cursor, statement, parameters, context, many):
            if 'workspaces.data' in statement:
                wide.append(statement)
        event.listen(app.state.engine, 'before_cursor_execute', observe)
        try:
            response = client.get('/api/projects/p001/first-screen')
            assert response.status_code == 200
            assert response.json()['project']['project']['id'] == 'p001'
            assert len(wide) <= 7, 'generation checks must not reload the workspace metadata blob'
        finally:
            event.remove(app.state.engine, 'before_cursor_execute', observe)
