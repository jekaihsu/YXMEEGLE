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
        control = next(n for n in p['nodes'] if n['key'] == 'control')
        if i % 9 == 4:
            p.setdefault('evidence', []).append(dict(id=f'{p["id"]}-ctl-ok', node_id=control['id'], key='deliverable', note='成果已核定', url='https://example.invalid/ok',
                                                    file_id=None, daily_id=None, daily_source_version=None, status='accepted',
                                                    submitted_by=control['owner_id'], created_at='2026-09-22T09:00:00+08:00'))
        if i % 3 == 0:
            p.setdefault('evidence', []).append(dict(id=f'{p["id"]}-ctl', node_id=control['id'], key='deliverable', note='成果初稿', url='https://example.invalid/ctl',
                                                    file_id=None, daily_id=None, daily_source_version=None, status='submitted',
                                                    submitted_by=control['owner_id'], created_at='2026-09-22T09:00:00+08:00'))
    upgrade(ws)
    ws['version'] = 1
    ws['environment'] = 'demo'
    return ws


def scenarios(ws, count):
    """Per scenario, `count` distinct (user, action fields) targets that succeed once each."""
    result = {name: [] for name in ('task_start', 'task_complete', 'task_return', 'task_add', 'task_update', 'comment_add',
                                    'evidence_submit', 'evidence_approve', 'file_link', 'participants_update', 'node_complete',
                                    'review_submit', 'document_withdraw', 'project_roles', 'delegation_set', 'node_skip_create', 'delivery_submit',
                                    'daily_propose')}
    for p in ws['projects']:
        pid = p['id']; index = int(pid[1:]) - 1
        pm = next(n for n in p['nodes'] if n['key'] == 'pm')
        if index % 3 == 0 and len(result['evidence_approve']) < count:
            result['evidence_approve'].append(('u-manager', dict(project_id=pid, payload={'id': f'{pid}-ctl'})))
        if len(result['file_link']) < count:
            result['file_link'].append((p['pm_id'], dict(project_id=pid, node_id=pm['id'], payload={'direction': 'input', 'name': '委託書', 'url': 'https://example.invalid/doc'})))
        if len(result['participants_update']) < count:
            result['participants_update'].append((p['pm_id'], dict(project_id=pid, payload={'nodes': [{'node_id': pm['id'], 'owner_id': pm['owner_id'], 'collaborator_ids': [p['pm_id']]}]})))
        if index % 2 == 0:
            name = 'node_complete' if len(result['node_complete']) <= len(result['review_submit']) else 'review_submit'
            if len(result[name]) < count: result[name].append((pm['owner_id'], dict(project_id=pid, node_id=pm['id'])))
        if len(result['daily_propose']) < count:
            result['daily_propose'].append((p['pm_id'], dict(project_id=pid, payload={'daily_id': f'du{index}', 'reason': '依案號核對'})))
        if len(result['document_withdraw']) < count:
            result['document_withdraw'].append((p['pm_id'], dict(project_id=pid, payload={'id': f'f{index}', 'reason': '版本錯誤'})))
        if len(result['project_roles']) < count:
            result['project_roles'].append((p['pm_id'], dict(project_id=pid, payload={'assistant_id': 'ou_050', 'admin_id': 'ou_051', 'reason': '補齊助理'})))
        if len(result['delegation_set']) < count:
            sales = next(n for n in p['nodes'] if n['key'] == 'sales')
            result['delegation_set'].append(('u-manager', dict(project_id=pid, payload={
                'principal_id': sales['owner_id'], 'delegate_id': 'ou_060', 'seat': 'owner', 'scope': 'tasks', 'task_ids': [sales['tasks'][0]['id']],
                'source': 'supervisor', 'start_date': '2026-10-01', 'end_date': '2026-12-31', 'qualified': True,
                'qualification_note': '主管確認資格', 'qualification_evidence': '能力認定紀錄'})))
        if len(result['node_skip_create']) < count:
            report = next(n for n in p['nodes'] if n['key'] == 'confirmation')
            if report['status'] == 'pending':
                result['node_skip_create'].append((p['pm_id'], dict(project_id=pid, node_id=report['id'], payload={'reason': '客戶無此需求', 'impact': '不影響交付'})))
        if index % 9 == 4 and len(result['delivery_submit']) < count:
            control = next(n for n in p['nodes'] if n['key'] == 'control')
            result['delivery_submit'].append((control['owner_id'], dict(project_id=pid, node_id=control['id'], payload={
                'work_item_ids': [control['tasks'][0]['id']], 'evidence_ids': [f'{pid}-ctl-ok'], 'quantity': '3', 'unit': '點'})))
        active = next((n for n in p['nodes'] if n['status'] == 'in_progress' and n['key'] not in ('field', 'pm')), None)
        if not active: continue
        starts = [t for t in active['tasks'] if t['status'] == 'pending']
        running = [t for t in active['tasks'] if t['status'] == 'in_progress']
        where = dict(project_id=pid, node_id=active['id'])
        if starts and len(result['task_start']) < count:
            result['task_start'].append((active['owner_id'], dict(where, task_id=starts[0]['id'])))
        if running and len(result['task_complete']) < count:
            result['task_complete'].append((active['owner_id'], dict(where, task_id=running[0]['id'], payload={'output': '完成'})))
        if len(result['task_return']) < count:
            result['task_return'].append((active['owner_id'], dict(where, task_id=active['tasks'][0]['id'], payload={'reason': '資料需補'})))
        if len(result['task_add']) < count:
            result['task_add'].append((active['owner_id'], dict(where, payload={'title': '補充工項'})))
        if len(result['task_update']) < count:
            result['task_update'].append((active['owner_id'], dict(where, task_id=active['tasks'][0]['id'], payload={'title': '改名工項'})))
        if len(result['comment_add']) < count:
            result['comment_add'].append((active['owner_id'], dict(where, task_id=active['tasks'][0]['id'], payload={'body': '請確認'})))
        if len(result['evidence_submit']) < count:
            result['evidence_submit'].append((active['owner_id'], dict(where, payload={'key': active['requirements'][0]['key'], 'note': '已備妥', 'url': 'https://example.invalid/evidence'})))
    return result
