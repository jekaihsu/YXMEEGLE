"""INV-01..06 共用純函式；只判斷本機狀態，不實作傳送。"""
import json
from pathlib import Path
import re
from switchboard_engine import normalize, parse_satellite_command, _otp_check, SATELLITES

ROSTER_PATH = Path(__file__).resolve().parent / 'formal/authorized_roster.json'
SENSITIVE = re.compile(r'底價|成本|毛利|A\s*[-/]\s*B\s*[-/]\s*C\s*預算|ABC\s*預算|底薪', re.I)
SCOPE_KINDS = frozenset({'SCOPE_CHANGE_OR_ADDON', 'scope_add', 'scope_cut', 'change_order'})

STRIP_PATTERNS = (
    re.compile(r'^\s*(?:寄件人|收件人)\s*[:：].*$', re.M),
    re.compile(r'^\s*(?:麻煩幫我|請寄給|收到請登記).*$', re.M),
    re.compile(r'(?:業主往來\d+|報編\d+|#\d+行政)'),
    re.compile(r'^\s*給[\u4e00-\u9fa5]{1,3}[，,：:].*$', re.M),
    re.compile(r'^\s*X-Sat-Cmd\s*:.*$', re.I | re.M),
)


def strip_command_headers(text: str, from_addr: str = 'yonginside@gmail.com', subject: str = '') -> str:
    res = parse_satellite_command(from_addr, subject, str(text or ''))
    cleaned = res.clean_body
    for pat in STRIP_PATTERNS:
        cleaned = pat.sub('', cleaned)
    return cleaned.strip()


def authorized_roster():
    record = json.loads(ROSTER_PATH.read_text(encoding='utf-8'))
    ids = frozenset(row['id'] for row in record['members'])
    if record['count'] != 81 or len(ids) != 81:
        raise ValueError('INV-01：授權身分名冊必須恰為81個不同識別')
    return ids


def all_10_gates_passed(gate_results):
    return (isinstance(gate_results, list) and len(gate_results) == 10
            and len({g.get('name') for g in gate_results}) == 10
            and all(g.get('passed') is True and bool(g.get('checks'))
                    and all(c.get('passed') is True for c in g['checks'])
                    for g in gate_results))


def send_authorized(approved_by, gate_results):
    return approved_by in authorized_roster() and all_10_gates_passed(gate_results)


def payment_release_allowed(category_id, hold_until_paid, payment_received):
    return category_id != 'CAT-02' or not hold_until_paid or payment_received is True


def check_bounce_release_allowed(invoice_paid, unreversed_allocated_amount, amount_due, check_cleared=True):
    """INV-06：支票退票／沖銷後未收餘額回彈，禁止放行成果。"""
    return (check_cleared is True
            and invoice_paid is True
            and unreversed_allocated_amount is not None
            and amount_due is not None
            and unreversed_allocated_amount >= amount_due)


def otp_pull_only_allowed(sender, dkim_domain, dkim_pass, spf_pass, subject='', body='', requester_id=None):
    """INV-05：OTP 僅允許白名單來源 + DKIM/SPF 通過 + 授權在職人員主動拉取。"""
    if requester_id is not None and requester_id not in authorized_roster():
        return False
    if not (dkim_pass and spf_pass):
        return False
    _cand, whitelisted, _acct, _code = _otp_check(sender or '', subject or '', body or '', bool(dkim_pass), dkim_domain)
    return bool(whitelisted)


def satcmd_verified(request):
    """衛星轉發指令必須具備 sent_copy_verified AND dkim_pass AND spf_pass。"""
    if request.get('channel') == 'satellite_cmd' or request.get('evidence_kind') == 'satellite_cmd':
        return bool(request.get('sent_copy_verified') and request.get('dkim_pass') and request.get('spf_pass')
                    and str(request.get('from_addr') or request.get('mailbox') or '').lower() in SATELLITES)
    return True


def sensitive_draft(text):
    value = re.sub(r'\s+', '', normalize(text))
    return bool(SENSITIVE.search(value))


def commitment_close_allowed(commitment):
    return (commitment.get('kind') not in SCOPE_KINDS
            or bool(commitment.get('settlement_card_id')
                    and str(commitment.get('written_confirmation_draft') or '').strip()))
