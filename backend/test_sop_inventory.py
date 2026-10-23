import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sop_inventory as inv  # noqa: E402
from sop_snapshot_reader import SnapshotError  # noqa: E402
from backend.sop_contracts import VERSION  # noqa: E402


def make_snapshot(path, rows, schema='yx-workspace-backup/3', digest=None):
    payload = json.dumps(rows).encode()
    manifest = {'schema': schema, 'sha256': {'database.json': digest or hashlib.sha256(payload).hexdigest()}}
    with ZipFile(path, 'w') as archive:
        archive.writestr('database.json', payload)
        archive.writestr('manifest.json', json.dumps(manifest))
    return path


def synthetic_rows():
    task = lambda i, status, version: {'id': i, 'status': status, 'sop_contract_version': version}
    legacy = {'id': 'w1', 'version': 1, 'data': {'projects': [
        {'id': 'p2', 'execution_system': 'workbench', 'sop_applicability': {'subcontract': {
            'applies': True, 'contract_version': VERSION, 'decided_by': 'u', 'reason': 'r'}},
         'nodes': [{'id': 'n2', 'key': 'b', 'status': 'active', 'requirements': [{'key': 'k'}],
                    'sop_applicability_pending': [{'key': 'x'}],
                    'tasks': [task('t3', 'pending', None), task('t2', 'completed', 'old')]}]},
        {'id': 'p1', 'nodes': [{'id': 'n1', 'key': 'a', 'status': 'completed', 'tasks': [task('t1', 'pending', VERSION)]}]},
    ], 'sop_requests': [{'id': 'r1', 'status': 'pending'}, {'id': 'r0', 'status': 'done'}],
        'approvals': [{'id': 'a1', 'status': 'submitted'}]}}
    return {'workspaces': [legacy]}


def test_inventory_is_deterministic_and_lists_expected_items(tmp_path):
    path = make_snapshot(tmp_path / 's.zip', synthetic_rows())
    first, second = inv.build_inventory(path), inv.build_inventory(path)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    ws = first['workspaces']['w1']
    assert [p['id'] for p in ws['projects']] == ['p1', 'p2']
    p1, p2 = ws['projects']
    assert p1['execution_system'] == 'pending' and p1['subcontract_decision'] == 'missing'
    assert p2['subcontract_decision'] == 'applies'
    assert p2['nodes'][0]['open_tasks_needing_contract_review'] == ['t3']  # completed history is not flagged
    assert p2['nodes_with_pending_applicability'] == ['b']
    assert ws['pending_sop_requests'] == ['r1'] and ws['pending_approvals'] == ['a1']
    assert 'production counts' in first['not_verified']


def test_normalized_storage_schema_is_rebuilt(tmp_path):
    rows = {'workspaces': [{'id': 'w', 'version': 1, 'data': {'storage_schema': 2}}], 'business_records': [
        {'workspace_id': 'w', 'kind': 'projects', 'entity_id': 'p', 'parent_id': '', 'ordinal': 0, 'data': {'id': 'p'}},
        {'workspace_id': 'w', 'kind': 'nodes', 'entity_id': 'n', 'parent_id': 'p', 'ordinal': 0, 'data': {'id': 'n', 'key': 'k'}},
        {'workspace_id': 'w', 'kind': 'tasks', 'entity_id': 't', 'parent_id': 'n', 'ordinal': 0, 'data': {'id': 't', 'status': 'pending'}}]}
    node = inv.build_inventory(make_snapshot(tmp_path / 's.zip', rows))['workspaces']['w']['projects'][0]['nodes'][0]
    assert node['tasks'] == 1 and node['open_tasks_needing_contract_review'] == ['t']


def test_snapshot_and_neighbours_are_unchanged(tmp_path, capsys):
    path = make_snapshot(tmp_path / 's.zip', synthetic_rows())
    before = (path.read_bytes(), path.stat().st_mtime_ns, sorted(p.name for p in tmp_path.iterdir()))
    assert inv.main([str(path)]) == 0
    assert json.loads(capsys.readouterr().out)['mode'] == 'read_only_inventory'
    assert (path.read_bytes(), path.stat().st_mtime_ns, sorted(p.name for p in tmp_path.iterdir())) == before


def test_malformed_inputs_fail_safely(tmp_path, capsys):
    bad = tmp_path / 'bad.zip'
    bad.write_bytes(b'not a zip')
    cases = [bad, tmp_path / 'missing.zip',
             make_snapshot(tmp_path / 'c.zip', synthetic_rows(), digest='0' * 64),
             make_snapshot(tmp_path / 'v.zip', synthetic_rows(), schema='other/9'),
             make_snapshot(tmp_path / 'n.zip', {'workspaces': 'x'}),
             make_snapshot(tmp_path / 'r.zip', {'workspaces': [{'id': 1, 'data': {}}]})]
    for case in cases:
        with pytest.raises(SnapshotError):
            inv.build_inventory(case)
        assert inv.main([str(case)]) == 1
    assert inv.main([]) == 2
    assert 'Traceback' not in capsys.readouterr().err


def test_odd_shapes_inside_valid_snapshot_do_not_crash(tmp_path):
    rows = {'workspaces': [{'id': 'w', 'version': 1, 'data': {'projects': [{'id': 'p', 'nodes': 'bad', 'sop_applicability': 5}, 7],
                                                              'sop_requests': None}}]}
    ws = inv.build_inventory(make_snapshot(tmp_path / 's.zip', rows))['workspaces']['w']
    assert ws['projects'][0]['nodes'] == [] and ws['pending_sop_requests'] == []
