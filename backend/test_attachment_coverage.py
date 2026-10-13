"""Case attachment coverage is not a count of the global source index."""

from .attachment_coverage import source_attachment_coverage
from .test_public_case_http_boundaries import isolated_http
from fastapi.testclient import TestClient
from .app import WorkspaceRow, BusinessRow, create_app
from . import storage


def test_counts_only_visible_case_metadata_and_distinguishes_file_versions():
    project = {
        'id': 'visible',
        'source_attachments': [
            {'id': 'a', 'status': 'indexed'},
            {'id': 'b', 'status': 'source_missing'},
            {'id': 'c', 'status': 'metadata_unavailable'},
            {'id': 'd', 'status': 'new_status'},
            {'id': 'e'},
        ],
        'files': [{'id': 'version-1'}, {'id': 'version-2'}],
    }
    # The caller may hold unrelated source metadata, but this pure helper
    # receives only the visible project's fields.
    workspace = {'projects': [project], 'source_attachment_index': [
        {'id': 'unrelated', 'project_id': 'private', 'status': 'indexed'}] * 42}
    result = source_attachment_coverage(workspace['projects'][0])
    assert result == {
        'scope': 'case_only',
        'metadata_records': 5,
        'metadata_status_counts': {
            'indexed': 1, 'source_missing': 1,
            'metadata_unavailable': 1, 'unknown': 2,
        },
        'workspace_versions': 2,
        'unmatched_metadata_access': 'outside_case_scope',
        'source_field_coverage': 'not_reported',
        'file_content_access': 'not_verified',
    }


def test_zero_case_metadata_makes_no_absence_or_access_claim():
    result = source_attachment_coverage({'id': 'visible', 'files': [{'id': 'v1'}]})
    assert result['metadata_records'] == 0
    assert result['metadata_status_counts'] == dict.fromkeys(
        ('indexed', 'source_missing', 'metadata_unavailable', 'unknown'), 0)
    assert result['workspace_versions'] == 1
    assert result['source_field_coverage'] == 'not_reported'
    assert result['file_content_access'] == 'not_verified'


def test_http_full_and_single_case_coverage_respects_visibility(isolated_http, tmp_path):
    app, _, _, _ = isolated_http
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, 'lark-boundary')
        state = storage.load(db, BusinessRow, row)
        hidden, visible = state['projects'][:2]
        hidden['source_attachments'] = [
            {'id': 'HIDDEN_ATTACHMENT', 'status': 'indexed'} for _ in range(3)]
        visible['source_attachments'] = [
            {'id': 'visible-indexed', 'status': 'indexed'},
            {'id': 'visible-missing', 'status': 'source_missing'},
            {'id': 'visible-unavailable', 'status': 'metadata_unavailable'},
        ]
        visible['files'] = [
            {'id': 'visible-version-1'}, {'id': 'visible-version-2'}]
        state['source_attachment_index'] = [
            {'id': f'GLOBAL_ORPHAN_{n}', 'status': 'indexed'} for n in range(42)]
        row.data = storage.save(db, BusinessRow, row.id, state)

    shell_app = create_app({
        'DATABASE_URL': f'sqlite:///{tmp_path}/boundaries.db',
        'UPLOAD_DIR': str(tmp_path / 'files'),
        'DEMO_MODE': 'false', 'APP_ENV': 'development',
        'SESSION_SECRET': 'boundary-only' * 4,
        'LARK_WORKER_ORGANIZATION': 'boundary',
        'LARK_ALLOWED_TENANTS': 'boundary',
        'WORKSPACE_SHELL_ENABLED': 'true',
    })
    client = TestClient(shell_app)
    client.cookies.set('meegle_session', shell_app.state.signer.dumps({
        'mode': 'lark', 'sid': 'boundary-session',
        'wid': 'lark-boundary', 'uid': 'u-manager'}))
    full_response = client.get('/api/workspace')
    detail_response = client.get(f"/api/projects/{visible['id']}")
    assert full_response.status_code == detail_response.status_code == 200
    full = full_response.json()
    detail = detail_response.json()
    assert [p['id'] for p in full['projects']] == [visible['id']]
    assert detail['project']['id'] == visible['id']
    coverage = full['projects'][0]['source_attachment_coverage']
    assert detail['project']['source_attachment_coverage'] == coverage
    assert coverage == {
        'scope': 'case_only',
        'metadata_records': 3,
        'metadata_status_counts': {
            'indexed': 1, 'source_missing': 1,
            'metadata_unavailable': 1, 'unknown': 0},
        'workspace_versions': 2,
        'unmatched_metadata_access': 'outside_case_scope',
        'source_field_coverage': 'not_reported',
        'file_content_access': 'not_verified',
    }
    for response in (full_response, detail_response):
        assert 'HIDDEN_ATTACHMENT' not in response.text
        assert 'GLOBAL_ORPHAN_' not in response.text
    assert client.get(f"/api/projects/{hidden['id']}").status_code == 404
