"""Staging-sized workspace in which the common write actions succeed.

perf_fixture shapes the data (420 projects is about 44k business rows). This module
makes those projects executable and plants the few records the node actions need, so a
benchmark or an equivalence test can drive real /api/actions requests against it.
"""
from copy import deepcopy

from .perf_fixture import build_scaled_workspace
from .policy import upgrade

WID = 'demo-bench'
MAPPED = {'state': 'mapped', 'canonical': '執行中', 'reasons': []}


def build_world(n_projects=420):
    ws = build_scaled_workspace(n_projects)
    for p in ws['projects']:
        p['source_lifecycle'] = deepcopy(MAPPED)
    # Every second project gets a pm node that is ready to be submitted: its tasks are
    # done and its requirement has accepted evidence.
    for i, p in enumerate(ws['projects']):
        pm = next(n for n in p['nodes'] if n['key'] == 'pm')
        pm['status'] = 'in_progress'
        if i % 2 == 0:
            for t in pm['tasks']:
                t.update(status='completed', output='完成', completed_at='2026-09-23T17:00:00+08:00')
            p['evidence'] = [dict(id=f'{p["id"]}-ev', node_id=pm['id'], key='assignment', note='已核定', url='', file_id=None,
                                  daily_id=None, daily_source_version=None, status='accepted', submitted_by=pm['owner_id'],
                                  created_at='2026-09-22T09:00:00+08:00')]
        else:
            for t in pm['tasks']:
                t['status'] = 'pending'
    upgrade(ws)
    ws['version'] = 1
    ws['environment'] = 'demo'
    return ws


def scenarios(ws, count):
    """Per scenario, `count` distinct (user, action fields) targets that succeed once each."""
    result = {'task_start': [], 'task_complete': [], 'comment_add': [], 'evidence_submit': [], 'node_complete': []}
    for p in ws['projects']:
        pid = p['id']; index = int(pid[1:]) - 1
        pm = next(n for n in p['nodes'] if n['key'] == 'pm')
        if index % 2 == 0 and len(result['node_complete']) < count:
            result['node_complete'].append((pm['owner_id'], dict(project_id=pid, node_id=pm['id'])))
        active = next((n for n in p['nodes'] if n['status'] == 'in_progress' and n['key'] not in ('field', 'pm')), None)
        if not active: continue
        starts = [t for t in active['tasks'] if t['status'] == 'pending']
        running = [t for t in active['tasks'] if t['status'] == 'in_progress']
        where = dict(project_id=pid, node_id=active['id'])
        if starts and len(result['task_start']) < count:
            result['task_start'].append((active['owner_id'], dict(where, task_id=starts[0]['id'])))
        if running and len(result['task_complete']) < count:
            result['task_complete'].append((active['owner_id'], dict(where, task_id=running[0]['id'], payload={'output': '完成'})))
        if len(result['comment_add']) < count:
            result['comment_add'].append((active['owner_id'], dict(where, task_id=active['tasks'][0]['id'], payload={'body': '請確認'})))
        if len(result['evidence_submit']) < count:
            result['evidence_submit'].append((active['owner_id'], dict(where, payload={'key': active['requirements'][0]['key'], 'note': '已備妥', 'url': 'https://example.invalid/evidence'})))
    return result
