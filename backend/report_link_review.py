"""Link administration has explicit case authority and no execution-system dependency."""
from copy import deepcopy
from .workflow import require, find, now, uid, event
from .report_links import can_review_links, daily_code, reviewed_item, case_items, resolve_daily, link_summary, REASONS, LinkBasis, linked_daily

LINK_ACTIONS = frozenset({'daily_propose', 'daily_approve', 'daily_link', 'daily_unlink', 'daily_bulk_link', 'report_bridge_review'})


def entries(state):
    return [(p, d) for p in state['projects'] for d in p.get('daily_reports', [])] + [(None, d) for d in state.get('daily_unmatched', [])]


def allowed_source(state, row):
    if state.get('environment') != 'production': return True
    from .source_case_policy import identity
    return identity(row.get('source_identity') or {}) in state.get('source_visible_record_ids', [])


def invalidate_reviews(state, daily_id, reason):
    for review in state.get('daily_reviews', []):
        if review['daily_id'] == daily_id and review['status'] in ('approved', 'pending'):
            review.update(status='invalidated', invalidated_at=now(), invalidated_reason=reason)


def apply_link(state, user, entry, project, reason, work_item_id=None, proposal=None):
    from .v4_sources import daily_mapping_version, daily_source_version
    require(reason and isinstance(reason, str) and reason.strip(), '需填核對依據', 422)
    require(not entry.get('source_missing'), '來源日報目前不存在，不能新增配對核准', 409)
    require(allowed_source(state, entry), '日報來源尚未授權', 403)
    if project is not None: require(can_review_links(user, project), '需主管、案件 PM 或最高管理員核對', 403)
    item = reviewed_item(state, project['id'], work_item_id) if project else None
    require(not work_item_id or item, '工項必須唯一且屬於已選案件', 422)
    prior = next((p for p, d in entries(state) if d['id'] == entry['id'] and p), None)
    if project is None: require(can_review_links(user, prior), '需原案 PM 或管理者解除連結', 403)
    before = dict(project_id=prior['id'] if prior else None, work_item_id=entry.get('work_item_id'), basis=entry.get('match_basis'))
    invalidate_reviews(state, entry['id'], reason)
    review = proposal or dict(id=uid(), daily_id=entry['id'], requested_by=user['id'], entry=deepcopy(entry),
                              source_version=daily_source_version(entry), mapping_version=daily_mapping_version(entry))
    review.update(project_id=project['id'] if project else None, work_item_id=item, unlink=project is None,
                  reason=reason.strip(), status='approved', approved_by=user['id'], approved_at=now())
    if proposal is None: state.setdefault('daily_reviews', []).append(review)
    for p in state['projects']: p['daily_reports'] = [d for d in p.get('daily_reports', []) if d['id'] != entry['id']]
    state['daily_unmatched'] = [d for d in state.get('daily_unmatched', []) if d['id'] != entry['id']]
    row = deepcopy(entry)
    row.pop('work_item_id', None); row.pop('item_match_basis', None)
    row.update(match_basis=LinkBasis.MANUAL.value, case_code=project['code'] if project else '',
               case_mapping_status='matched' if project else 'unresolved_reference', manual_unlinked=project is None)
    if item: row.update(work_item_id=item, item_match_basis=LinkBasis.MANUAL.value)
    (project['daily_reports'] if project else state['daily_unmatched']).append(row)
    audit = event(state, user, 'daily_link_reviewed' if project else 'daily_link_removed', project['id'] if project else before['project_id'], message=reason)
    audit.update(daily_id=entry['id'], before=before, after=dict(project_id=review['project_id'], work_item_id=item), review_id=review['id'])
    from .operations import reconcile_daily_evidence
    reconcile_daily_evidence(state)


def apply_review(state, user, body):
    from .v4_sources import daily_mapping_version, daily_source_version, review_mapping_version
    action, data = body['action'], body.get('payload') or {}
    project = next((p for p in state['projects'] if p['id'] == body.get('project_id')), None)
    if action == 'report_bridge_review':
        require(project and can_review_links(user, project), '需主管、案件 PM 或最高管理員核對', 403)
        require(isinstance(data.get('reason'), str) and data['reason'].strip(), '需填核對依據', 422)
        bridge = state.setdefault('report_case_bridges', {}).get(project['id'])
        require(bridge is not None, '請先讀取橋接候選', 409)
        codes = data.get('codes', [])
        require(isinstance(codes, list) and all(isinstance(c, str) and c.strip() for c in codes), '請指定完整 v3 案號', 422)
        require(data.get('status') in ('reviewed', 'rejected'), '橋接狀態錯誤', 422)
        if data['status'] == 'reviewed':
            require(codes and len(codes) == len(set(codes)), '核對須選取不重複的 v3 案件', 422)
            available = state.get('report_bridge_available_codes', [])
            require(all(c in available for c in codes), 'v3 案件不存在於已讀取快照', 422)
        else: require(not codes, '拒絕橋接不可保留選取案號', 422)
        bridge.setdefault('history', []).append({k: deepcopy(v) for k, v in bridge.items() if k != 'history'})
        bridge.update(status=data['status'], codes=codes, actor_id=user['id'], reason=data['reason'].strip(), decided_at=now())
        event(state, user, 'report_bridge_reviewed', project['id'], message=data['reason'])
        return True
    if action == 'daily_bulk_link':
        require(data.get('confirmed') is True, '需確認批次配對的列數與案件', 422)
        code = daily_code({'source_case_code': data.get('provisional_code')})
        require(code and project and can_review_links(user, project), '需完整暫填案號及核對權限', 403)
        rows = [d for p, d in entries(state) if p is None and daily_code(d) == code and not d.get('source_missing') and allowed_source(state, d)]
        expected = data.get('daily_ids')
        require(isinstance(expected, list) and rows and len(expected) == len(set(expected)) and set(expected) == {d['id'] for d in rows}, '批次內容已更新，請重新確認', 409)
        require(data.get('work_item_id') in (None, ''), '批次配對不分配工項', 422)
        for row in rows: apply_link(state, user, row, project, data.get('reason'))
        return True
    if action == 'daily_approve':
        review = find(state['daily_reviews'], data.get('id'))
        require(review['status'] == 'pending', '已核對', 409)
        project = find(state['projects'], review['project_id'])
        rows = [d for _, d in entries(state) if d['id'] == review['daily_id']]
        require(len(rows) == 1 and daily_mapping_version(rows[0]) == review_mapping_version(review), '日報來源關聯已變更或不存在，請重新提出配對核對', 409)
        apply_link(state, user, rows[0], project, review['reason'], review.get('work_item_id'), proposal=review)
        return True
    rows = [d for _, d in entries(state) if d['id'] == data.get('daily_id')]
    require(len(rows) == 1, '日報不存在或識別重複', 404)
    row = rows[0]
    if action == 'daily_propose':
        require(project is not None, '請指定案件', 422)
        require(user.get('active', True) and (can_review_links(user, project) or user['id'] in row.get('source_actor_ids', [])), '需由已核實日報填報人或案件 PM 補充關聯', 403)
        require(allowed_source(state, row), '日報來源尚未授權', 403)
        require(isinstance(data.get('reason'), str) and data['reason'].strip(), '需填核對依據', 422)
        require(not row.get('source_missing'), '來源日報目前不存在，不能新增配對核准', 409)
        item = reviewed_item(state, project['id'], data.get('work_item_id'))
        require(not data.get('work_item_id') or item, '工項必須唯一且屬於已選案件', 422)
        state.setdefault('daily_reviews', []).append(dict(id=uid(), daily_id=row['id'], project_id=project['id'], work_item_id=item,
                source_version=daily_source_version(row), mapping_version=daily_mapping_version(row), source_fields=deepcopy(row.get('source_fields', {})),
                entry=deepcopy(row), reason=data['reason'].strip(), requested_by=user['id'], status='pending'))
        event(state, user, action, project['id'], message=data['reason'])
        return True
    require(action in ('daily_link', 'daily_unlink'), '配對操作錯誤', 422)
    require(project is not None or action == 'daily_unlink', '請指定案件', 422)
    if action == 'daily_unlink':
        prior = next((p for p, d in entries(state) if p and d['id'] == row['id']), None)
        require(prior and can_review_links(user, prior), '需原案 PM 或管理者解除連結', 403)
    apply_link(state, user, row, None if action == 'daily_unlink' else project, data.get('reason'), data.get('work_item_id'))
    return True


def review_queue(state, user):
    from .source_case_policy import visible_project
    manager = can_review_links(user)
    projects = [p for p in state['projects'] if manager or can_review_links(user, p)]
    reviewer = bool(projects)
    visible = []
    for parent, row in entries(state):
        if row.get('source_missing') or not allowed_source(state, row): continue
        if not reviewer and user['id'] not in row.get('source_actor_ids', []): continue
        if parent and not (manager or can_review_links(user, parent) or user['id'] in row.get('source_actor_ids', [])): continue
        decision = resolve_daily(row, projects)
        evidence = row.get('candidate_evidence') or list(decision.candidates)
        unknown_containment=parent is not None and not linked_daily(row)
        if unknown_containment:
            evidence=[*evidence,dict(project_id=parent['id'],rank=3,reasons=['legacy_containment_unknown_provenance'])]
        visible.append({**{k: deepcopy(v) for k, v in row.items() if k not in ('source_provenance', 'source_actor_ids')},
                        'project_id': parent['id'] if parent and not unknown_containment else None, 'project_code': parent['code'] if parent else None,
                        'case_mapping_status':'missing_reference' if unknown_containment else row.get('case_mapping_status','missing_reference'),
                        'candidate_evidence': [c for c in evidence if any(p['id'] == c['project_id'] for p in projects)],
                        'can_review': can_review_links(user,parent) if parent else reviewer})
    selectable = [p for p in state['projects'] if visible_project(state,p)] if not reviewer else projects
    return dict(rows=visible, reasons={r: sum(not d['project_id'] and d.get('case_mapping_status', 'missing_reference') == r for d in visible) for r in REASONS},
                projects=[dict(id=p['id'], code=p['code'], name=p.get('name'), can_review=can_review_links(user, p),
                               items=[dict(id=i['id'], name=i.get('name') or i.get('title') or i.get('fields', {}).get('填報工項') or i['id']) for i in case_items(state, p['id'])]) for p in selectable],
                reviews=[r for r in state.get('daily_reviews', []) if any(d['id'] == r['daily_id'] for d in visible)],
                bridges=[{**b, 'project_code': next((p['code'] for p in projects if p['id'] == b['project_id']), ''),
                          'can_review': True} for b in state.get('report_case_bridges', {}).values() if any(p['id'] == b['project_id'] for p in projects)],
                available_codes=state.get('report_bridge_available_codes', []))


def reconcile_item_reviews(state):
    invalidated=[]
    for parent,row in list(entries(state)):
        if not parent or not row.get('work_item_id') or row.get('match_basis')!=LinkBasis.MANUAL.value: continue
        found=[i for i in state.get('source_work_items',[]) if i['id']==row['work_item_id']]
        if not found or len(found)==1 and not found[0].get('source_missing') and found[0].get('project_id')==parent['id']: continue
        reason='人工核對的工項來源已移除或改歸其他案件，須重新核對'
        invalidate_reviews(state,row['id'],reason)
        parent['daily_reports'].remove(row)
        row.pop('work_item_id',None);row.pop('item_match_basis',None)
        row.update(case_mapping_status='unresolved_reference',match_basis=None,mapping_invalidation_reason=reason)
        state.setdefault('daily_unmatched',[]).append(row);invalidated.append(row['id'])
    return invalidated
