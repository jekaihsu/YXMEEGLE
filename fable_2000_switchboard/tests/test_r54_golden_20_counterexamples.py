"""
R54 守門反例 golden：20 條（CE-R54-01..20）。

契約：
- 每條斷言的是「結果」：隔離(quarantine) / 出卡(card) / 同號(same serial) / 拒絕(reject)。
- 能用 switchboard_engine 純函數表達的，一律用既有引擎；引擎沒有的守門原語（支票再兌現、
  附件雙副檔名、大寫金額對帳、結案重開、離職外發、收件人/CC 網域）在本檔以確定性
  純函數實作為「R54 守門」並逐一驗證。
- run_r54_20_counterexamples() 回傳 20 個布林結果，整合進 test_switchboard_golden.py 一起跑。
- test_emit_quarantine_cards_count_equals_quarantined 另在測試 clone DB 上驗證
  emit_quarantine_cards() 回傳數 == 隔離信數（全程 ROLLBACK，actual_sends=0，不對外發信）。

pytest -q tests/test_r54_golden_20_counterexamples.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unicodedata
from datetime import date

try:
    import pytest
except ImportError:  # pragma: no cover
    pytest = None

from switchboard_engine import (
    AttachmentMeta, ORG_SJ, ORG_UNKNOWN, ORG_YX, SWITCHBOARD_ADDR,
    check_otp_pull, check_sealed_release, classify_inbound_email, detect_org,
    evaluate_org_marker_separation, parse_satellite_command, resolve_serial_assignment,
    sealed_release_message, thread_fingerprint, verify_satellite_sent_copy_header_d, Violation,
)

SAT_INSIDE = "yonginside@gmail.com"
SAT_QUOTE = "yong.yx1101@gmail.com"
SAT_ADMIN = "yong.yx1103@gmail.com"
SWITCHBOARD = SWITCHBOARD_ADDR  # yongxiang.ltd@gmail.com


# ===========================================================================
# R54 守門原語（引擎未涵蓋者，於此確定性實作；與未來 DB trigger 同義）
# ===========================================================================
def guard_duplicate_check_cashing(ledger):
    """#12 支票再兌現守門：同一張支票（check_no）只能兌現一次。

    ledger: [(check_no, amount, status), ...]，status ∈ {'cleared','bounced'}。
    回傳 (net_paid, duplicate_check_nos)：
      - net_paid 只計入每張『已兌現(cleared)』支票一次（退票不計）；
      - duplicate_check_nos 為被偵測到重複兌現的支票號集合（守門命中）。
    """
    seen_cleared = {}
    duplicates = set()
    net_paid = 0
    for check_no, amount, status in ledger:
        if status != "cleared":
            continue
        if check_no in seen_cleared:
            duplicates.add(check_no)   # 再兌現 → 不重複加總
            continue
        seen_cleared[check_no] = amount
        net_paid += amount
    return net_paid, duplicates


_EXEC_EXT = {".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".js", ".jse", ".vbs",
             ".vbe", ".wsf", ".hta", ".jar", ".ps1", ".msi", ".lnk", ".reg", ".cpl"}
_MACRO_EXT = {".docm", ".xlsm", ".pptm", ".dotm", ".xlam", ".xltm"}


def dangerous_attachment_reason(filename: str):
    """#15 附件巨集/執行檔偽裝雙副檔名守門。回傳違規原因字串，安全則 None。"""
    name = unicodedata.normalize("NFKC", (filename or "").strip()).lower()
    parts = name.split(".")
    exts = ["." + p for p in parts[1:]]
    ext = exts[-1] if exts else ""
    if len(exts) >= 2 and ext in _EXEC_EXT:
        return "DOUBLE_EXTENSION_EXECUTABLE"
    if ext in _EXEC_EXT:
        return "EXECUTABLE"
    if ext in _MACRO_EXT:
        return "MACRO_ENABLED"
    return None


_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6,
             "七": 7, "八": 8, "九": 9, "壹": 1, "貳": 2, "參": 3, "叁": 3, "肆": 4, "伍": 5,
             "陸": 6, "柒": 7, "捌": 8, "玖": 9}
_CN_UNIT = {"拾": 10, "十": 10, "佰": 100, "百": 100, "仟": 1000, "千": 1000}
_CN_SEC = {"萬": 10000, "万": 10000, "億": 100000000, "亿": 100000000}


def chinese_amount_to_int(text: str) -> int:
    """#17 將中文大寫金額轉為整數（支援 拾佰仟萬億、零/整/元/圓/新臺幣）。"""
    total = section = number = 0
    for ch in unicodedata.normalize("NFKC", text or ""):
        if ch in _CN_DIGIT:
            number = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            section += (number or 1) * _CN_UNIT[ch]
            number = 0
        elif ch in _CN_SEC:
            section = (section + number) * _CN_SEC[ch]
            total += section
            section = number = 0
    return total + section + number


def guard_amount_consistency(numeric_amount: int, uppercase_text: str):
    """#17 報價單阿拉伯數字金額 vs 內文大寫金額不符攔截。"""
    parsed = chinese_amount_to_int(uppercase_text)
    if parsed != int(numeric_amount):
        return [Violation("AMOUNT_MISMATCH", f"digits={numeric_amount} uppercase={parsed}")]
    return []


def guard_reopen_closed_case(case_status: str, sender_is_internal: bool, has_pm_approval: bool = False):
    """#18 已結案工編被外部信強制重開攔截。回傳 'REJECT_REOPEN' 或 'ALLOW'。"""
    if case_status != "closed":
        return "ALLOW"
    if sender_is_internal and has_pm_approval:
        return "ALLOW"          # 僅在職 PM 核准可重開
    return "REJECT_REOPEN"      # 外部信（或無核准）一律不得自動重開


def guard_actor_can_send(employment_status: str, session_active: bool):
    """#19 離職同仁信箱或失效 Session 觸發外發拒絕。回傳 'ALLOW' 或 'REJECT_SEND'。"""
    if employment_status == "active" and session_active:
        return "ALLOW"
    return "REJECT_SEND"


def _domain_of(addr: str) -> str:
    addr = (addr or "").strip().lower()
    return addr.split("@")[-1] if "@" in addr else ""


def guard_recipients(to_list, cc_list, authorized_domains):
    """#20 空白收件人或 CC 夾帶未授權外部網域攔截。回傳違規碼清單（空=通過）。"""
    authorized = {d.lower() for d in authorized_domains}
    violations = []
    clean_to = [a for a in (to_list or []) if (a or "").strip()]
    if not clean_to:
        violations.append("EMPTY_RECIPIENT")
    for addr in (cc_list or []):
        dom = _domain_of(addr)
        if dom and dom not in authorized:
            violations.append(f"UNAUTHORIZED_CC_DOMAIN:{dom}")
    return violations


# ===========================================================================
# 20 條守門反例（CE-R54-01 .. CE-R54-20）
# ===========================================================================
def ce01_no_dkim_satellite_quarantined():
    """① 無 DKIM：衛星 From 但 dkim_pass=False → 隔離。"""
    c = classify_inbound_email(SAT_INSIDE, [SWITCHBOARD], "代寄測試",
                               "請寄給 王先生 <wang@ctci.com.tw>\n\n附件為報價單。",
                               dkim_pass=False, dkim_domain="gmail.com")
    assert c.category == "UNCLASSIFIED" and c.injection_suspect and c.quarantine_reason
    return True


def ce02_dkim_gmail_but_from_not_whitelisted():
    """② d=gmail.com 但 From 非登錄白名單信箱 → 不得成為 INTERNAL-CMD，判注入並隔離。"""
    c = classify_inbound_email("randomperson@gmail.com", [SWITCHBOARD], "代寄指令",
                               "請寄給 王先生 <wang@ctci.com.tw>\n\n內容",
                               dkim_pass=True, dkim_domain="gmail.com")
    assert c.category != "INTERNAL-CMD" and c.injection_suspect and c.quarantine_reason
    return True


def ce03_display_name_spoofing():
    """③ 顯示名偽裝：顯示名寫衛星，實際位址為攻擊者 → 不是衛星、判注入。"""
    c = classify_inbound_email("詠翔內業 yonginside@gmail.com <attacker@evil.org>", [SWITCHBOARD],
                               "代寄", "請寄給 王先生\n\n內容")
    assert c.category != "INTERNAL-CMD" and c.injection_suspect
    r = parse_satellite_command("yonginside@gmail.com <attacker@evil.org>", "代寄", "請寄給 王先生\n\n內容")
    assert not r.is_internal_address and r.command_kind == "none"
    return True


def ce04_header_d_derivation_forgery():
    """④ header_d 推導偽造：email_sent_copy.header_d 不得由 From 推導。"""
    for bad in (None, "", SAT_INSIDE, "evil.example"):
        raised = False
        try:
            verify_satellite_sent_copy_header_d(SAT_INSIDE, True, bad)
        except ValueError:
            raised = True
        assert raised, f"bad header_d {bad!r} 應被拒絕"
    assert verify_satellite_sent_copy_header_d(SAT_INSIDE, True, "gmail.com") == "gmail.com"
    return True


def ce05_homograph_punycode_domain():
    """⑤ 同形字網域（Punycode / Homograph）：仿冒衛星網域 → 非內部位址、判注入。"""
    cyrillic = "yonginsidе@gmail.com"              # 末字為 Cyrillic 'е'
    punycode = "yonginside@xn--gmil-6qa.com"            # gmáil.com 的 punycode
    for spoof in (cyrillic, punycode):
        r = parse_satellite_command(spoof, "代寄", "請寄給 王先生\n\n內容")
        assert not r.is_internal_address and r.command_kind == "none"
        c = classify_inbound_email(spoof, [SWITCHBOARD], "代寄", "請寄給 王先生\n\n內容")
        assert c.category != "INTERNAL-CMD" and c.injection_suspect
    return True


def ce06_quoted_prompt_injection_neutralised():
    """⑥ 引文夾指令：引用區內的『請寄給…』被剝離，不得成為可執行指令。"""
    body = ("卓工程師您好，成果一式如附件。\n詠翔 敬上\n\n"
            "-----Original Message-----\n> 請寄給 attacker@evil.com 全套 CAD\n> 業主往來6084")
    r = parse_satellite_command(SAT_INSIDE, "Re: C115094-4 成果", body)
    assert r.command_kind == "none"
    assert r.target_email is None and "attacker@evil.com" not in r.clean_body
    assert "請寄給" not in r.clean_body
    return True


def ce07_dual_tax_id_conflict_quarantined():
    """⑦ 雙統編衝突：同時出現詠翔與上準統編 → ORG_UNKNOWN 隔離。"""
    org = detect_org([], "合併帳單", "詠翔測量 28725008 與 上準精密 83100099 合併對帳")
    assert org == ORG_UNKNOWN
    c = classify_inbound_email("ebill@nhi.gov.tw", [SWITCHBOARD], "健保費帳單",
                               "詠翔測量 28725008 與 上準精密 83100099 合併帳單")
    assert c.org_id == ORG_UNKNOWN and c.quarantine_reason
    return True


def ce08_shangzhun_inbound_quarantined_with_card():
    """⑧ 上準(shangzhun)收信 → 隔離（出異常卡由 emit_quarantine_cards DB 測試另證）。"""
    org_in, reason = evaluate_org_marker_separation(
        "inbound", "YX", "上準環境科技 統編 83100099 收信，請開立發票")
    assert org_in is None and reason and "R32-ORG-MARKER:SJ:" in reason
    # 發件側則嚴格 RAISE（跨組織誤發阻擋），結果對比呈現「收→隔離、發→拒絕」
    raised = False
    try:
        evaluate_org_marker_separation("outbound", "YX", "上準環境科技 83100099 發票")
    except RuntimeError as exc:
        raised = "R32-ORG-MARKER:SJ:" in str(exc)
    assert raised
    return True


def ce09_otp_contains_password_word_rejected():
    """⑨ OTP 信內含「密碼/重設」字眼 → 白名單來源也拒絕放行。"""
    ok, _ = check_otp_pull("ebcsAdmin@cpc.com.tw", "cpc.com.tw", True, True,
                           "EBCS 登入驗證碼", "您的密碼重設驗證碼 654321")
    assert ok is False
    c = classify_inbound_email("no-reply@accounts.google.com", [SWITCHBOARD],
                               "驗證碼：重設您的密碼", "您的 Google 驗證碼 112233",
                               dkim_pass=True, spf_pass=True, dkim_domain="accounts.google.com")
    assert c.category == "CAT-10" and c.is_otp_candidate and not c.is_otp_whitelisted and c.quarantine_reason
    return True


def ce10_same_serial_on_thread_reply():
    """⑩ 舊串回覆沿用同號：同序號 → 同 thread，不配第二個號。"""
    fp1 = thread_fingerprint("Re: Fw: C115001 詢價", None, [], 6084, "abc")
    fp2 = thread_fingerprint("C115001 詢價", None, [], 6084, "zzz")
    assert fp1 == fp2 == "serial:6084"
    rows = {("YX", "serial:6084", "live"): 6084}
    assert resolve_serial_assignment("YX", "serial:6084", "live", rows) == 6084
    assert rows[("YX", "serial:6084", "live")] == 6084          # 沿用、未配新號
    return True


def ce11_dry_run_token_rejected_on_live():
    """⑪ dry_run token 對 live 環境拒絕。"""
    rows = {("YX", "legacy:yezhu:6084", "live"): 6084}
    raised = False
    try:
        resolve_serial_assignment("YX", "legacy:yezhu:6084", "dry_run", rows)
    except ValueError as exc:
        raised = "R32-SER-DRY-OVER-LIVE" in str(exc)
    assert raised and rows[("YX", "legacy:yezhu:6084", "live")] == 6084
    return True


def ce12_duplicate_check_cashing_guard():
    """⑫ 支票再兌現：同一張支票兌現兩次 → 只計一次，偵測重複。"""
    net, dups = guard_duplicate_check_cashing([
        ("CK-001", 105000, "cleared"),
        ("CK-001", 105000, "cleared"),   # 再兌現（重複）
        ("CK-002", 50000, "cleared"),
    ])
    assert net == 155000 and dups == {"CK-001"}
    # 退票不計
    net2, dups2 = guard_duplicate_check_cashing([("CK-003", 70000, "bounced")])
    assert net2 == 0 and dups2 == set()
    return True


def ce13_short_received_30_vs_fee_tolerance():
    """⑬ 短收 30 元（匯費差額 vs 短收邊界）：容差內仍視為未沖帳、封存官章版。"""
    assert "匯費容差內" in sealed_release_message(30)
    assert "匯費容差內" in sealed_release_message(100)   # 邊界：容差上限
    assert "未收" in sealed_release_message(101)          # 邊界外：短收
    held = check_sealed_release([AttachmentMeta("C114109_final.dwg", "h", 1, is_sealed=True)],
                                True, 30.0, False)
    assert held and held[0].code == "HOLD_UNTIL_PAID"     # 少 30 元仍擋
    return True


def ce14_concurrent_send_idempotency_lock():
    """⑭ 兩人並行寄出：同一 thread 的兩個並行寄出只得一個序號（idempotency）。"""
    rows = {}
    a = resolve_serial_assignment("YX", "serial:12085", "live", rows, next_live_seq=12085)
    b = resolve_serial_assignment("YX", "serial:12085", "live", rows, next_live_seq=12086)
    assert a == b == 12085                                 # 第二位寄件者沿用、非 12086
    assert list(rows.keys()) == [("YX", "serial:12085", "live")]   # 僅一個序號登錄
    return True


def ce15_double_extension_macro_executable_quarantined():
    """⑮ 附件巨集/執行檔偽裝雙副檔名隔離。"""
    assert dangerous_attachment_reason("工程報告.pdf.exe") == "DOUBLE_EXTENSION_EXECUTABLE"
    assert dangerous_attachment_reason("現場照片.jpg.js") == "DOUBLE_EXTENSION_EXECUTABLE"
    assert dangerous_attachment_reason("payload.exe") == "EXECUTABLE"
    assert dangerous_attachment_reason("估價單.xlsm") == "MACRO_ENABLED"
    assert dangerous_attachment_reason("成果圖.pdf") is None
    assert dangerous_attachment_reason("C114109_final.dwg") is None
    return True


def ce16_forged_internal_domain_relay_quarantined():
    """⑯ 偽造內部網域轉寄鏈跳板：假冒總機 From（DKIM 不符）→ 隔離。"""
    c = classify_inbound_email(SWITCHBOARD, [SAT_INSIDE], "Fw: 轉寄鏈",
                               "給恆安，業主往來6084，收到請登記。\n\n> 原信",
                               dkim_pass=True, dkim_domain="relay.evil.example")
    assert c.category == "UNCLASSIFIED" and c.injection_suspect
    assert c.quarantine_reason and "spoofed switchboard From" in c.quarantine_reason
    return True


def ce17_quote_amount_vs_uppercase_mismatch():
    """⑰ 報價單金額與內文大寫金額不符攔截。"""
    ok = guard_amount_consistency(849970, "新臺幣捌拾肆萬玖仟玖佰柒拾元整")
    bad = guard_amount_consistency(849970, "新臺幣捌拾伍萬元整")   # 850000 ≠ 849970
    assert ok == [] and bad and bad[0].code == "AMOUNT_MISMATCH"
    return True


def ce18_closed_case_forced_reopen_rejected():
    """⑱ 已結案工編被外部信強制重開攔截。"""
    assert guard_reopen_closed_case("closed", sender_is_internal=False) == "REJECT_REOPEN"
    assert guard_reopen_closed_case("closed", sender_is_internal=True, has_pm_approval=False) == "REJECT_REOPEN"
    assert guard_reopen_closed_case("closed", sender_is_internal=True, has_pm_approval=True) == "ALLOW"
    assert guard_reopen_closed_case("active", sender_is_internal=False) == "ALLOW"
    return True


def _verify_fable_2000_db_and_sso_counterexamples():
    """Fable 20:00 實庫與 SSO 反例補強驗證（嚴格針對 yongxiang_plumb_r39_clone）：
    涵蓋：跨組越權讀取、離職帳號重放、偽造/重放 state、夾帶 ?role=admin / X-Employee-Id、
    未授權核准、shadow 模式下強行觸發寄信。
    """
    import psycopg2
    conn = psycopg2.connect("dbname=yongxiang_plumb_r39_clone")
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute("DO $$ BEGIN ASSERT current_database() != 'yongxiang_plumb'; ASSERT current_database() = 'yongxiang_plumb_r39_clone'; END $$;")

        # 1. 跨組越權讀取：吳柏頤 (pm_sales) 不可讀取張家彬 (engineering_indoor) 專屬 field 卡案件
        cur.execute("SELECT case_id FROM public.session_list_for('a968fbf8-c0ac-5d6a-9939-80584ede3509'::uuid, false)")
        pm_cases = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT DISTINCT case_id FROM public.card WHERE role='field' AND assignee_employee_id='13394342-2826-5d5d-a26f-44e259279870'::uuid")
        eng_cases = {r[0] for r in cur.fetchall()}
        assert eng_cases and not (pm_cases & eng_cases), "跨組越權讀取必須被阻擋"

        # 2. 離職帳號 ('left' 含劉芳君) 與外部待確認帳號 (William Chiu, 育寬 林) 阻擋，且不可擁有 management 權限
        cur.execute("SELECT employment_status FROM public.employee WHERE id='7b77e454-5df0-5e67-be36-17061f24037f'::uuid")
        assert cur.fetchone()[0] == 'left', "劉芳君必須為 left"
        cur.execute("SELECT count(*) FROM public.employee WHERE id IN ('6f152c92-3590-59df-ace8-f878398c6306'::uuid, 'f6a25167-bb5d-4523-9b6f-ca00ca868ef1'::uuid) AND (employment_status='active' OR role_code IN ('gm','vp') OR department='經營層')")
        assert cur.fetchone()[0] == 0, "William Chiu 與 育寬 林 不可為 active 或擁有 management 權限"
        cur.execute("SELECT count(*) FROM public.quarantine_intake_queue_v")
        assert cur.fetchone()[0] == 3, "羅薇歸屬不明佇列必須精確為 3 張工程卡"

        # 3. 未授權核准：final_body 非空但 approved_by IS NULL 違反 switchboard_final_requires_approval
        cur.execute("SAVEPOINT sp_unauth_approve")
        raised_unauth = False
        try:
            cur.execute("SELECT id FROM public.outbound_message LIMIT 1")
            oid = cur.fetchone()[0]
            cur.execute("UPDATE public.outbound_message SET approved_by = NULL, approved_at = NULL, final_body = NULL, delivery_status = 'draft' WHERE id = %s", (oid,))
            cur.execute("SELECT public.outbound_send(%s::uuid, '13394342-2826-5d5d-a26f-44e259279870'::uuid)", (oid,))
        except Exception:
            raised_unauth = True
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT sp_unauth_approve")
        assert raised_unauth, "未授權核准必須被 DB constraint/trigger 攔截"

        # 4. Shadow 模式下強行觸發 outbound_send_live 必拋出異常
        cur.execute("SELECT mode FROM public.org_mode WHERE org_id='YX'")
        assert cur.fetchone()[0] == "shadow"
        cur.execute("SELECT id, COALESCE(approved_by, '1101fb67-0080-50c1-98e6-d02f7a0ae907'::uuid) FROM public.outbound_message LIMIT 1")
        out_id, actor_id = cur.fetchone()
        cur.execute("SAVEPOINT sp_shadow_send")
        raised_shadow = False
        try:
            cur.execute("SELECT public.outbound_send_live(%s::uuid, %s::uuid)", (out_id, actor_id))
        except Exception:
            raised_shadow = True
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT sp_shadow_send")
        assert raised_shadow, "Shadow 模式下強行觸發 outbound_send_live 必須被攔截"
    finally:
        conn.rollback()
        conn.close()
    return True


def ce19_departed_employee_or_dead_session_send_rejected():
    """⑲ 離職同仁信箱或失效 Session 觸發外發拒絕。"""
    assert guard_actor_can_send("left", True) == "REJECT_SEND"
    assert guard_actor_can_send("active", False) == "REJECT_SEND"
    assert guard_actor_can_send("active", True) == "ALLOW"
    assert _verify_fable_2000_db_and_sso_counterexamples() is True
    return True


def ce20_blank_recipient_or_unauthorized_cc_rejected():
    """⑳ 空白收件人或 CC 夾帶未授權外部網域攔截。"""
    authorized = {"ctci.com.tw", "yxsurvey.com.tw"}
    assert "EMPTY_RECIPIENT" in guard_recipients([], ["ok@ctci.com.tw"], authorized)
    v = guard_recipients(["eng@ctci.com.tw"], ["leak@attacker.example"], authorized)
    assert any(x.startswith("UNAUTHORIZED_CC_DOMAIN:attacker.example") for x in v)
    assert guard_recipients(["eng@ctci.com.tw"], ["cc@yxsurvey.com.tw"], authorized) == []
    return True


_COUNTEREXAMPLES = [
    ("CE-R54-01", ce01_no_dkim_satellite_quarantined, "quarantine"),
    ("CE-R54-02", ce02_dkim_gmail_but_from_not_whitelisted, "quarantine"),
    ("CE-R54-03", ce03_display_name_spoofing, "reject"),
    ("CE-R54-04", ce04_header_d_derivation_forgery, "reject"),
    ("CE-R54-05", ce05_homograph_punycode_domain, "reject"),
    ("CE-R54-06", ce06_quoted_prompt_injection_neutralised, "reject"),
    ("CE-R54-07", ce07_dual_tax_id_conflict_quarantined, "quarantine"),
    ("CE-R54-08", ce08_shangzhun_inbound_quarantined_with_card, "quarantine+card"),
    ("CE-R54-09", ce09_otp_contains_password_word_rejected, "reject"),
    ("CE-R54-10", ce10_same_serial_on_thread_reply, "same-serial"),
    ("CE-R54-11", ce11_dry_run_token_rejected_on_live, "reject"),
    ("CE-R54-12", ce12_duplicate_check_cashing_guard, "reject"),
    ("CE-R54-13", ce13_short_received_30_vs_fee_tolerance, "quarantine"),
    ("CE-R54-14", ce14_concurrent_send_idempotency_lock, "same-serial"),
    ("CE-R54-15", ce15_double_extension_macro_executable_quarantined, "quarantine"),
    ("CE-R54-16", ce16_forged_internal_domain_relay_quarantined, "quarantine"),
    ("CE-R54-17", ce17_quote_amount_vs_uppercase_mismatch, "reject"),
    ("CE-R54-18", ce18_closed_case_forced_reopen_rejected, "reject"),
    ("CE-R54-19", ce19_departed_employee_or_dead_session_send_rejected, "reject"),
    ("CE-R54-20", ce20_blank_recipient_or_unauthorized_cc_rejected, "reject"),
]


def run_r54_20_counterexamples() -> dict[str, bool]:
    """跑完 20 條守門反例，回傳 {code: passed}。整合進 golden 套件。"""
    results: dict[str, bool] = {}
    for code, fn, _result_kind in _COUNTEREXAMPLES:
        results[code] = bool(fn())
    assert len(results) == 20 and all(results.values())
    return results


# ---------------------------------------------------------------------------
# pytest：每條獨立一個 test（斷言結果），再加一條總綱
# ---------------------------------------------------------------------------
if pytest is not None:
    @pytest.mark.parametrize("code,fn,result_kind", _COUNTEREXAMPLES)
    def test_r54_counterexample(code, fn, result_kind):
        assert fn() is True, f"{code} ({result_kind}) 守門反例未通過"

    def test_r54_all_20_green():
        res = run_r54_20_counterexamples()
        assert len(res) == 20 and all(res.values())
        assert sorted(res) == [f"CE-R54-{i:02d}" for i in range(1, 21)]


# ===========================================================================
# ⑧ 的 DB 證據：emit_quarantine_cards() 回傳數 == 隔離信數（全程 ROLLBACK）
# ===========================================================================
if pytest is not None:
    def _scalar(conn, sql, args=()):
        return conn.execute(sql, args).fetchone()[0]

    def test_emit_quarantine_cards_count_equals_quarantined(conn):
        """隔離 N 封 → emit_quarantine_cards() 回傳 N；再跑回 0（冪等）。actual_sends 不受影響。"""
        from uuid import uuid4
        # 先清空既有待出卡 backlog，讓計數確定
        _scalar(conn, "SELECT emit_quarantine_cards()")
        assert _scalar(conn, "SELECT emit_quarantine_cards()") == 0

        # 暫停使用者觸發器（含自動出卡），插入 N 封「org_id IS NULL + quarantine_reason」隔離信
        n = 7
        conn.execute("SET LOCAL session_replication_role = 'replica'")
        for i in range(n):
            conn.execute(
                """INSERT INTO email_message(message_id, from_addr, subject, org_id, quarantine_reason)
                   VALUES (%s, 'stranger@unknown.invalid', 'R54 CE quarantine', NULL, %s)""",
                (f"<r54-ce-{uuid4()}@invalid>", f"R54-CE: injection suspect #{i}"),
            )
        conn.execute("SET LOCAL session_replication_role = 'origin'")

        pending = _scalar(conn, """
            SELECT count(*) FROM email_message_effective_v m
             WHERE m.still_quarantined AND m.quarantine_reason IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM card c
                               WHERE c.idempotency_key = 'quarantine:' || coalesce(m.message_id, m.id::text))
        """)
        assert pending == n, f"隔離信數應為 {n}，實得 {pending}"

        emitted = _scalar(conn, "SELECT emit_quarantine_cards()")
        assert emitted == n, f"emit_quarantine_cards() 回傳 {emitted} != 隔離信數 {n}"
        assert _scalar(conn, "SELECT emit_quarantine_cards()") == 0   # 冪等

        # 守門：全程沒有任何對外寄送（clone 無 live transport；卡片均為 dry_run）
        bad_mode = _scalar(conn, """
            SELECT count(*) FROM card
             WHERE idempotency_key LIKE 'quarantine:%%' AND mode <> 'dry_run'
        """)
        assert bad_mode == 0, "隔離卡不得為 live（actual_sends 必須為 0）"
        # conn fixture 於 finally ROLLBACK：clone DB 不留任何列


if __name__ == "__main__":
    res = run_r54_20_counterexamples()
    for code, passed in res.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {code}")
    print(f"=== {sum(res.values())}/20 R54 守門反例通過 ===")
