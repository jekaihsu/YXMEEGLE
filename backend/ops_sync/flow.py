"""Synthetic local vertical flow (assign / propose / decide / dispatch / recover) over the wired OpsStore.

Everything here is synthetic fixture data behind the adapter. Nothing is bound by label to a Lark field, no live
adapter exists, and no mapping is verified: the roster, eligibility and approver identities below are fixtures, NOT
evidence that any Lark column establishes PM eligibility, node ownership or a task deadline. Person identity is the
typed (tenant, app, person_id) triple; display names never take part in matching.
"""
import dataclasses

from . import values as V
from .deadlines import DeadlineService, MockReceipt
from .domain import DomainService
from .eligibility import (ELIGIBLE, INELIGIBLE, MockAppPolicy, MockDirectory, MockEligibilitySource, PersonIdentity,
                          evaluate)
from .flags import OpsFlags
from .projection import sync_headers

TENANT, APP = 'synthetic', 'yxs-local'
MAPPING_NOTICE = ('所有對應皆為「未確認／模擬」：人員資格、案件 PM、節點負責人與期限皆為本機模擬資料，'
                  '尚未與任何 Lark 欄位綁定或驗證；案件 PM 標籤不代表具 PM 資格，合約結束日不等於任務期限。')
# (person_id, display name, eligibility fixture, reason, directory-active)
ROSTER = (('u-pm', '林育寬', ELIGIBLE, '', True), ('u-manager', '張智偉', ELIGIBLE, '', True),
          ('u-control', '李家彬', ELIGIBLE, '', True), ('u-revoked', '（模擬）資格已撤銷', INELIGIBLE, 'revoked', True),
          ('u-norecord', '（模擬）無資格紀錄', None, '', True), ('u-inactive', '（模擬）已停用帳號', ELIGIBLE, '', False))
APPROVERS = tuple(PersonIdentity(TENANT, APP, pid) for pid in ('mock-approver-1', 'mock-approver-2'))
ACTIONS = ('assign_pm', 'clear_pm', 'assign_responsible', 'submit_deadline')
DECISIONS = ('approved', 'rejected', 'stale')
MOCK_OUTCOMES = ('normal', 'timeout_after_commit', 'permission_lost', 'concurrent_edit')

REASONS = {
    'ineligible': '該人員在模擬資格資料中不具 PM 資格（已撤銷或不符），未寫入',
    'eligibility_unknown': '無法確認該人員的 PM 資格（模擬資料無紀錄或已過期），預設拒絕',
    'not_active': '該人員不是已啟用的應用程式身分，未寫入',
    'not_authorized': '沒有此操作的應用程式授權',
    'multiple_assignees': '一次只能指派一位；已保留原值並記錄衝突，請明確選擇單一人選',
    'pm_seat_holder_not_eligible': '該人員同時是 PM，但目前不具 PM 資格',
    'stale_scope': '核准內容與目前申請版本不符（過期核准），生效日期維持不變',
    'insufficient_distinct_approvers': '核准人數不足',
    'baseline_changed': '生效值在您編輯期間已被更動',
}
GATES = ('pm_seat_blocked_ineligible', 'pm_seat_blocked_unknown', 'assignment_ambiguous')


def reason_text(code):
    if code and code.startswith('pm_seat_blocked'):
        return '案件 PM 席位目前被封鎖（資格不符或不明），不可核准或派送期限變更'
    return REASONS.get(code, f'原因代碼：{code}') if code else ''


def person(person_id):
    """Typed person binding. A free string that is not a stable id raises ValidationError (-> 422)."""
    return PersonIdentity(TENANT, APP, person_id).validated()


class Fixtures:
    """Per-request synthetic eligibility / directory / policy. Role gates come from `lead` (checked by the caller);
    the application policy mirrors that decision so the domain layer enforces it again independently."""

    def __init__(self, clock, actor_id, is_lead):
        self.clock = clock
        self.eligibility = MockEligibilitySource(TENANT, APP)
        self.directory = MockDirectory()
        self.policy = MockAppPolicy()
        now = clock.now()
        for pid, name, status, reason, active in ROSTER:
            ident = person(pid)
            if active:
                self.directory.admit(ident, name)
            if status:
                self.eligibility.set(ident, status, now, valid_seconds=3600, revision=1, reason=reason)
        for approver in APPROVERS:
            self.directory.admit(approver, 'mock approver')
            self.policy.grant(approver, 'approve_deadline')
        self.actor = person(actor_id)
        if is_lead:
            for action in ACTIONS:
                self.policy.grant(self.actor, action)

    def services(self, store):
        domain = DomainService(store, self.clock, self.eligibility, self.policy, self.directory, TENANT, APP)
        return domain, DeadlineService(domain)

    def authorizer(self):
        """Engine hook: person-typed fields must carry an active (and, for PM, eligible) typed identity at submit AND dispatch."""
        def check(envelope, phase):
            if envelope.field_id not in ('case.pm', 'node.responsible') or envelope.intended_value is V.CLEAR:
                return None
            try:
                ident = PersonIdentity.from_key(envelope.intended_value.value)
            except (ValueError, V.OpsError):
                return 'invalid_person'
            if not self.directory.is_active(ident):
                return 'not_active'
            if envelope.field_id == 'case.pm':
                status = evaluate(self.eligibility, ident, self.clock.now()).status
                return None if status == ELIGIBLE else 'ineligible' if status == INELIGIBLE else 'eligibility_unknown'
            return None
        return check


def roster_view(fx):
    out = []
    for pid, name, _, _, active in ROSTER:
        ident = person(pid)
        status = evaluate(fx.eligibility, ident, fx.clock.now()).status
        out.append({'person_id': pid, 'name': name, 'active': active, 'eligibility': status,
                    'person_key': ident.key})
    return out


def _seat_view(slot, names):
    key = slot['person']
    return {'person_id': key and key.split('|')[2], 'name': key and names.get(key, ''), 'revision': slot['revision'],
            'state': slot.get('state', 'assigned' if key else 'empty'),
            'open_conflicts': list(slot['open_conflicts'])}


def _proposal_view(prop):
    return {'proposal_id': prop['proposal_id'], 'state': prop['state'], 'reason': prop['reason'],
            'expected': V.decode(prop['expected']).value if prop['expected'].get('t') == 'set' else None,
            'expected_revision': prop['expected_revision'],
            'intended': prop['intended'].get('v') if prop['intended'].get('t') == 'set' else None,
            'actor': prop['actor'], 'receipt_id': prop['receipt_id'], 'mock_receipt': prop['receipt_id'] is not None}


def entities_view(domain, user_visible, fx):
    dom = domain.snapshot()
    names = {f'{TENANT}|{APP}|{pid}': name for pid, name, *_ in ROSTER}
    out = []
    for rec in list(dom['cases'].values()) + list(dom['nodes'].values()):
        if not user_visible(rec['project_id']):
            continue
        dl = rec['deadline']
        eff = dl['effective']['value']
        out.append({
            'entity_id': rec['entity_id'], 'kind': rec['kind'], 'project_id': rec['project_id'],
            'node_id': rec.get('node_id'), 'seat_field': 'case.pm' if rec['kind'] == 'case' else 'node.responsible',
            'seat': _seat_view(rec['pm'] if rec['kind'] == 'case' else rec['responsible'], names),
            'deadline': {'original': dl['original'] and dl['original']['value'],
                         'effective': {'value': eff.get('v') if eff.get('t') == 'set' else None,
                                       'revision': dl['effective']['revision']},
                         'proposals': [_proposal_view(p) for p in sorted(dl['proposals'].values(), key=lambda p: p['version'])]}})
    return out


def dispatch_denial(engine_snapshot):
    """Workspace-global dispatch suspension and the commands it holds back."""
    suspended = [{'reason': reason, **info} for reason, info in engine_snapshot['suspended'].items()]
    held = [c['envelope']['command_id'] for c in engine_snapshot['commands'].values() if c['state'] == 'queued'] if suspended else []
    return {'suspended': suspended, 'held_commands': held}


def sync(domain, state):
    return sync_headers(domain, state, OpsFlags(lark_authoritative_ops=True))


def mock_receipt(deadlines, entity_id, proposal_id, decision):
    """Mock-only receipt for a decision. `stale` binds to the previous proposal version so it must be refused."""
    receipt = deadlines.build_receipt(entity_id, proposal_id, APPROVERS, f'mock-receipt:{proposal_id}')
    if decision == 'stale':
        receipt = dataclasses.replace(receipt, receipt_id=f'mock-stale:{proposal_id}', proposal_version=receipt.proposal_version - 1)
    assert isinstance(receipt, MockReceipt) and receipt.mock is True
    return receipt
