"""The P2 list pages and Source Health read only the collections they render; task trees, events and daily reports stay in the database."""
import pytest
from . import storage
from .test_p2_int_routes import http, world  # noqa: F401 (pytest fixtures)

LIST_ROUTES = ('/api/confirmations', '/api/manager-overview', '/api/source-health')
UNRENDERED = {'events', 'work_schedules', 'approvals', 'recurring', 'daily_unmatched', 'jobs', 'delegations'}


@pytest.mark.parametrize('route', LIST_ROUTES)
def test_list_reads_load_headers_and_source_rows_only(world, monkeypatch, route):
    _, client, _, _, _, _ = world
    reads = []
    full, partial = storage.load, storage.load_partial

    def spy_full(db, model, row):
        reads.append({'scope': 'full'})
        return full(db, model, row)

    def spy_partial(db, model, row, *, collections=(), project_ids=None, project_children=()):
        reads.append({'scope': 'partial', 'collections': set(collections), 'project_ids': project_ids, 'children': tuple(project_children)})
        return partial(db, model, row, collections=collections, project_ids=project_ids, project_children=project_children)

    monkeypatch.setattr(storage, 'load', spy_full)
    monkeypatch.setattr(storage, 'load_partial', spy_partial)
    response = client.get(route)
    assert response.status_code == 200, response.text
    assert reads, 'the route must read the workspace'
    assert all(read['scope'] == 'partial' for read in reads), reads
    for read in reads:
        assert read['project_ids'] is None and not read['children'], read
        assert not read['collections'] & UNRENDERED, read
        assert {'projects', 'users', 'source_confirmations'} <= read['collections'], read
