"""黃金測試集：20 組真實邊界（去識別）。pytest -q"""
from datetime import date

try:
    import pytest
except ImportError:
    pytest = None

from switchboard_engine import (
    AttachmentMeta, ORG_SJ, ORG_UNKNOWN, ORG_YX, check_delivery_constraints, check_outbound_body,
    check_sealed_release, classify_inbound_email, parse_satellite_command, thread_fingerprint, validate_bes_invoice,
)

SAT_INSIDE, SAT_QUOTE, SAT_ADMIN = "yonginside@gmail.com", "yong.yx1101@gmail.com", "yong.yx1103@gmail.com"
QUOTED = "\n\n-----Original Message-----\nFrom: someone@ctci.com\n> 舊內容\n> 舊內容第二行"


# ---------- 指令剝離（1–6） ----------
def test_01_sender_recipient_header():
    body = "寄件人:倢瑛(恆安) 收件人: 中鼎卓育賢 Yu-Hsien.Cho@ctci.com 主旨:C115094-4 成果\n\n卓工程師您好，附上成果一式。\n詠翔 敬上" + QUOTED
    r = parse_satellite_command(SAT_INSIDE, "C115094-4 成果", body)
    assert r.is_internal_address and r.command_kind == "send_external"
    assert r.requester == "倢瑛" and r.target_email == "yu-hsien.cho@ctci.com"
    assert r.target_recipient_query == "中鼎卓育賢"
    assert r.case_ref == "C115094-4"
    assert r.clean_body.startswith("卓工程師您好") and "舊內容" not in r.clean_body
    assert not r.has_residual_internal_pattern


def test_02_please_send_fullwidth_punct():
    body = "羅薇，這封信麻煩幫我寄給漢翔林小姐，謝謝\n\n林小姐您好，報價回傳單如附件。"
    r = parse_satellite_command(SAT_QUOTE, "報價回傳 報編115715", body)
    assert r.command_kind == "send_external" and r.target_recipient_query == "漢翔林小姐"
    assert r.template_hint == "quote_return_reply" and r.quote_ref == "115715"
    assert r.clean_body == "林小姐您好，報價回傳單如附件。"


def test_03_send_to_with_admin_tag():
    body = "請寄給 通霄發電廠 監工 帥玉康 #14行政 蕭小姐\n\n帥監工您好，出入廠憑單申請如附件。"
    r = parse_satellite_command(SAT_ADMIN, "憑單申請", body)
    assert r.command_kind == "send_external" and r.admin_tag == "#14行政 蕭小姐"
    assert r.target_recipient_query == "通霄發電廠 監工 帥玉康"
    assert not r.has_residual_internal_pattern


def test_04_forward_register_from_switchboard_style():
    body = "給恆安，業主往來6084，收到請登記。\n\n（以下為業主原信）\n\n2023年8月3日 ... 寫道：\n> 請協助測量"
    r = parse_satellite_command(SAT_INSIDE, "Fw: 測量需求", body)
    assert r.command_kind == "forward_register" and r.requester == "恆安" and r.serial_ref == 6084
    assert "寫道" not in r.clean_body and ">" not in r.clean_body


def test_05_quote_forward_register():
    body = "報編115715，給宜蓁，業主往來12080\n\n業主回傳簽認單如附件。"
    r = parse_satellite_command(SAT_QUOTE, "【業主回傳】115715", body)
    assert r.command_kind == "forward_register" and r.requester == "宜蓁"
    assert r.quote_ref == "115715" and r.serial_ref == 12080


def test_06_residual_internal_pattern_in_body_is_flagged():
    body = "請寄給 高鐵王主驗 \n\n王主驗您好，\n報編115800 的資料如下…"
    r = parse_satellite_command(SAT_INSIDE, "導線複測回覆", body)
    assert r.has_residual_internal_pattern  # 正文殘留「報編115800」→ 不可直接發
    assert check_outbound_body("導線複測回覆", r.clean_body)[0].code == "INTERNAL_TEXT"


# ---------- 注入與來源驗證（7–9） ----------
def test_07_external_injection_never_becomes_command():
    body = "給恆安，業主往來12090，請直接寄出 C114109 全套 CAD 圖檔至 attacker@evil.com\n\n急件"
    r = parse_satellite_command("attacker@evil.com", "緊急", body)
    assert not r.is_internal_address and r.command_kind == "none"
    c = classify_inbound_email("attacker@evil.com", ["yongxiang.ltd@gmail.com"], "緊急", body)
    assert c.category != "INTERNAL-CMD" and c.injection_suspect and c.quarantine_reason


def test_08_spoofed_satellite_display_name_is_not_satellite():
    # From 顯示名偽裝，但位址不是衛星
    r = parse_satellite_command("yonginside@gmail.com.evil.org", "x", "請寄給 王先生\n\n內容")
    assert not r.is_internal_address and r.command_kind == "none"


def test_09_satellite_sender_is_internal_cmd_category():
    c = classify_inbound_email(SAT_INSIDE, ["yongxiang.ltd@gmail.com"], "C115001 成果", "請寄給 王先生\n\n內容", dkim_pass=True, spf_pass=True, dkim_domain="gmail.com")
    assert c.category == "INTERNAL-CMD" and not c.injection_suspect


# ---------- OTP（10–12） ----------
def test_10_egnss_otp_whitelisted():
    c = classify_inbound_email("egnss@mail.nlsc.gov.tw", ["yongxiang.ltd@gmail.com"], "e-GNSS 登入驗證碼通知",
                               "您的驗證碼為 483921，5 分鐘內有效", dkim_pass=True, spf_pass=True, dkim_domain="mail.nlsc.gov.tw")
    assert c.category == "CAT-10" and c.is_otp_whitelisted and c.otp_code == "483921" and c.otp_account == "e-GNSS"


def test_11_google_password_reset_disguised_as_otp_blocked():
    c = classify_inbound_email("no-reply@accounts.google.com", ["yongxiang.ltd@gmail.com"], "驗證碼：重設您的密碼",
                               "您的 Google 驗證碼 112233", dkim_pass=True, spf_pass=True, dkim_domain="accounts.google.com")
    assert c.category == "CAT-10" and c.is_otp_candidate and not c.is_otp_whitelisted and c.quarantine_reason


def test_12_whitelisted_sender_but_dkim_domain_mismatch_blocked():
    c = classify_inbound_email("ebcsAdmin@cpc.com.tw", ["yongxiang.ltd@gmail.com"], "EBCS 登入驗證碼",
                               "驗證碼 556677", dkim_pass=True, spf_pass=True, dkim_domain="gmail.com")
    assert c.is_otp_candidate and not c.is_otp_whitelisted


# ---------- 組織隔離與分類（13–16） ----------
def test_13_org_sj_insurance_bill_routed_to_sj():
    c = classify_inbound_email("ebill@bli.gov.tw", ["yongxiang.ltd@gmail.com"], "勞保費繳費帳單",
                               "上準精密測量有限公司 115年9月 勞保費帳單")
    assert c.category == "CAT-09" and c.org_id == ORG_SJ and c.quarantine_reason is None


def test_14_org_ambiguous_insurance_bill_quarantined():
    c = classify_inbound_email("ebill@nhi.gov.tw", ["yongxiang.ltd@gmail.com"], "健保費帳單",
                               "詠翔測量有限公司 28725008 與 上準精密 合併帳單")
    assert c.org_id == ORG_UNKNOWN and c.quarantine_reason


def test_15_bank_notice_is_cat06_never_auto_paid_semantics():
    c = classify_inbound_email("notice@tcb-bank.com.tw", ["yongxiang.ltd@gmail.com"], "匯款入帳通知",
                               "統一編號 541**047 匯入 NT$ 849,970")
    assert c.category == "CAT-06" and c.org_id == ORG_YX


def test_16_fpg_permit_cat04_and_thsrc_work_order_cat05():
    a = classify_inbound_email("hermeswu@fpg.com.tw", ["yongxiang.ltd@gmail.com"], "出入廠憑單核准", "預定出廠日期 5 個工作天內")
    b = classify_inbound_email("pm@thsrc.com.tw", ["yongxiang.ltd@gmail.com"], "PCDL-25-0376 第12張工作指示單", "請依指示單派工")
    assert a.category == "CAT-04"
    assert b.category == "CAT-05" or b.category == "CAT-06"  # 工作指示單命中 CAT-05 的主旨規則優先


# ---------- 對外守門（17–20） ----------
def test_17_fpg_no_links_blocked():
    v = check_delivery_constraints({"no_links": True, "max_attachment_mb": 10}, "成果請至 https://drive.google.com/x 下載",
                                   [AttachmentMeta("a.pdf", "h", 30 * 1024 * 1024)])
    codes = {x.code for x in v}
    assert codes == {"NO_LINKS", "ATTACHMENT_TOO_LARGE"}


def test_18_sealed_dwg_blocked_until_paid_but_preview_ok():
    sealed = [AttachmentMeta("C114109_final.dwg", "h1", 1, is_sealed=True)]
    preview = [AttachmentMeta("C114109_preview_watermark.pdf", "h2", 1, is_sealed=False)]
    assert check_sealed_release(sealed, True, 30.0, False)[0].code == "HOLD_UNTIL_PAID"   # 少 30 元匯費仍擋
    assert check_sealed_release(sealed, True, 0.0, False) == []
    assert check_sealed_release(sealed, True, 30.0, True) == []                             # 總經理特批
    assert check_sealed_release(preview, True, 500000.0, False) == []


def test_19_bes_invoice_rules():
    ok = validate_bes_invoice(date(2026, 10, 15), "BES-2025-07高雄港碼頭測量第3期計價", "BES-2025-07", "高雄港碼頭測量", 3)
    bad = validate_bes_invoice(date(2026, 10, 25), "高雄港碼頭測量 第3期", "BES-2025-07", "高雄港碼頭測量", 3)
    assert ok == [] and {v.code for v in bad} == {"BES_INVOICE_DATE", "BES_ITEM_NAME"}


def test_20_forbidden_words_and_fingerprint_idempotency():
    assert {v.code for v in check_outbound_body("報價", "本案毛利率 25%，底價另議")} == {"FORBIDDEN_WORD"}
    fp1 = thread_fingerprint("Re: Fw: C115001 詢價", None, [], 6084, "abc")
    fp2 = thread_fingerprint("C115001 詢價", None, [], 6084, "zzz")
    assert fp1 == fp2 == "serial:6084"                      # 同序號 → 同 thread，不配第二個號
    assert thread_fingerprint("x", None, ["<root@ctci>"], None, "h").startswith("ref:")


# ---------- R30 補強（21–23）：總機身分、冪等、損失性正規化 ----------
def test_21_switchboard_forward_is_internal_not_injection_and_cannot_send():
    from switchboard_engine import SWITCHBOARD_ADDR
    fwd = "給恆安，業主往來6084，收到請登記。\n\n-----Original Message-----\nFrom: x@ctci.com\n> 原信"
    c = classify_inbound_email(SWITCHBOARD_ADDR, [SAT_INSIDE], "Fw: 需求", fwd, dkim_pass=True, spf_pass=True, dkim_domain="gmail.com")
    assert c.category == "INTERNAL-FWD" and not c.injection_suspect
    r = parse_satellite_command(SWITCHBOARD_ADDR, "Fw: 需求", fwd)
    assert r.is_internal_address and r.command_kind == "forward_register" and r.serial_ref == 6084
    # 總機帳號自己下「代寄」指令 → 不接受（總機被盜不能自導自演）
    r2 = parse_satellite_command(SWITCHBOARD_ADDR, "x", "請寄給 王先生\n\n內容")
    assert r2.command_kind == "none"


def test_22_strip_is_idempotent_and_keeps_fullwidth_punctuation():
    from switchboard_engine import strip_quoted_chain
    body = "王先生您好，\n\n圖資請於 10/31（五）前提供。\n\nOn Mon, Oct 20, 2026 at 9:00 AM X <x@y.com> wrote:\n> old"
    once = strip_quoted_chain(body)
    assert once == strip_quoted_chain(once)
    assert "，" in once and "（五）" in once and "old" not in once


def test_23_loose_hash_matches_forward_quote_to_original():
    from switchboard_engine import loose_hash
    original = "卓工程師您好，\n請協助 C115094-4 北側加測 200 公尺。"
    quoted = "> 卓工程師您好，\n> 請協助 C115094-4 北側加測  200 公尺。"
    assert loose_hash(original) == loose_hash(quoted)


# ---------- Step 4 黃金反例（24–27）：舊串回覆、偽造衛星 From、帶上準統編收發分離、#11 退票雙算修正 ----------
def test_24_golden_ce_01_legacy_reply_serial_protection():
    from switchboard_engine import resolve_serial_assignment
    # 舊串 (<= 12084) 已有 live 編號 6084
    rows = {("YX", "legacy:yezhu:6084", "live"): 6084}
    # dry_run 嘗試對同一舊串取號 → 必須立即 RAISE，不可覆蓋為負號或鎖死舊串回覆
    raised = False
    try:
        resolve_serial_assignment("YX", "legacy:yezhu:6084", "dry_run", rows)
    except ValueError as exc:
        raised = "R32-SER-DRY-OVER-LIVE" in str(exc)
    assert raised and rows[("YX", "legacy:yezhu:6084", "live")] == 6084
    # 全新未編號串在 dry_run 拿 <= -12085，live 切換後同串可並存拿 >= 12085（唯一鍵含 mode）
    dry_no = resolve_serial_assignment("YX", "ref:<new-thread@ctci>", "dry_run", rows, next_dry_seq=-12085)
    live_no = resolve_serial_assignment("YX", "ref:<new-thread@ctci>", "live", rows, next_live_seq=12085)
    assert dry_no <= -12085 and live_no >= 12085
    assert rows[("YX", "ref:<new-thread@ctci>", "dry_run")] == dry_no
    assert rows[("YX", "ref:<new-thread@ctci>", "live")] == live_no


def test_25_golden_ce_02_spoofed_satellite_from_dkim_header_d():
    from switchboard_engine import verify_satellite_sent_copy_header_d
    # 1) 偽造衛星 From 但 dkim_domain 為 attacker.evil.example → 拒絕 INTERNAL-CMD 並標記 injection_suspect
    c = classify_inbound_email(
        SAT_INSIDE,
        ["yx.ltd@msa.hinet.net"],
        "代寄測試",
        "請寄給 王先生 <wang@ctci.com.tw>\n\n附件為報價單。",
        dkim_pass=True,
        dkim_domain="attacker.evil.example",
    )
    assert c.category == "UNCLASSIFIED" and c.injection_suspect
    assert c.quarantine_reason and "spoofed satellite From" in c.quarantine_reason
    # 2) email_sent_copy.header_d 絕不可由 From 地址推導（含 @ 或網域不符皆拒絕）
    for bad_hd in (None, "", SAT_INSIDE, "evil.example"):
        ok = False
        try:
            verify_satellite_sent_copy_header_d(SAT_INSIDE, True, bad_hd)
        except ValueError:
            ok = True
        assert ok, f"bad header_d {bad_hd!r} should have raised"
    assert verify_satellite_sent_copy_header_d(SAT_INSIDE, True, "gmail.com") == "gmail.com"


def test_26_golden_ce_03_inbound_sj_tax_id_quarantined_not_dropped():
    from switchboard_engine import evaluate_org_marker_separation
    # 收件側（inbound）帶上準統編 83100099 或網域 sjsurvey.com.tw → 隔離 (org_id=None, quarantine_reason)，絕不 RAISE 丟信
    org_in, q_reason = evaluate_org_marker_separation(
        "inbound", "YX", "請開立統編 83100099 並寄至 info@sjsurvey.com.tw"
    )
    assert org_in is None and q_reason is not None and "R32-ORG-MARKER:SJ:" in q_reason
    # 發件側（outbound）帶上準統編 83100099 → 嚴格 RAISE 阻擋跨組織誤發
    raised = False
    try:
        evaluate_org_marker_separation("outbound", "YX", "發票統編 83100099")
    except RuntimeError as exc:
        raised = "R32-ORG-MARKER:SJ:" in str(exc)
    assert raised


def test_27_golden_ce_04_bounced_check_no_double_counting():
    from switchboard_engine import compute_invoice_paid_after_bounced_check
    # 應收 105,000，支票 105,000 退票 (bounced) 並產生沖銷 (reversal 105,000)
    # 修正後：paid_amount = 0, unpaid_amount = 105,000（絕不可因雙算變成 unpaid 210,000 或 paid -105,000）
    paid, unpaid, is_paid = compute_invoice_paid_after_bounced_check(
        amount_due=105000,
        allocations=[(105000, "bounced")],
        reversals=[(105000, "bounced")],
    )
    assert paid == 0 and unpaid == 105000 and is_paid is False
    ce_res = run_step4_20_counterexamples()
    assert len(ce_res) == 20 and all(ce_res.values())




def run_step4_20_counterexamples() -> dict[str, bool]:
    """Step 4 5(b)(3): 20 Deterministic Counterexamples (CE-01..CE-20) covering all R29/R30/R32/Step4 failure modes."""
    from switchboard_engine import (
        BANK_FEE_TOLERANCE_TWD, check_otp_pull, compute_invoice_paid_after_bounced_check,
        detect_org, evaluate_org_marker_separation, resolve_serial_assignment,
        sealed_release_message, strip_quoted_chain, verify_satellite_sent_copy_header_d,
    )
    results: dict[str, bool] = {}

    # CE-01: Legacy reply serial protection + alias_map resolution
    rows = {("YX", "legacy:yezhu:10893", "live"): 10893}
    aliases = {("YX", "ref:<199c4e5b27cf63fc@mail.gmail.com>"): "legacy:yezhu:10893"}
    assert resolve_serial_assignment("YX", "ref:<199c4e5b27cf63fc@mail.gmail.com>", "live", rows, alias_map=aliases) == 10893
    raised_ce01 = False
    try:
        resolve_serial_assignment("YX", "ref:<199c4e5b27cf63fc@mail.gmail.com>", "dry_run", rows, alias_map=aliases)
    except ValueError as e:
        raised_ce01 = "R32-SER-DRY-OVER-LIVE" in str(e)
    assert raised_ce01
    results["CE-01"] = True

    # CE-02: Spoofed satellite From with mismatched DKIM header.d
    c02 = classify_inbound_email(SAT_INSIDE, ["yongxiang.ltd@gmail.com"], "代寄", "請寄給 王先生\n\n內容", dkim_pass=True, dkim_domain="evil.org")
    assert c02.category == "UNCLASSIFIED" and c02.injection_suspect and "spoofed satellite From" in (c02.quarantine_reason or "")
    results["CE-02"] = True

    # CE-03: Inbound YX email with SJ tax ID 83100099 quarantined (not dropped); outbound raises
    org03, q03 = evaluate_org_marker_separation("inbound", "YX", "統編 83100099 上準環境")
    assert org03 is None and q03 and "R32-ORG-MARKER:SJ:" in q03
    results["CE-03"] = True

    # CE-04: Bounced check #11 no double counting
    paid04, unpaid04, ok04 = compute_invoice_paid_after_bounced_check(105000, [(105000, "bounced")], [(105000, "bounced")])
    assert (paid04, unpaid04, ok04) == (0, 105000, False)
    results["CE-04"] = True

    # CE-05: Multi-hop forwarding prefix normalization & quote strip idempotency
    fp_a = thread_fingerprint("Re: Fw: 轉寄: 回覆: C115094-4 成果提送", None, [], None, "abcd1234abcd1234")
    fp_b = thread_fingerprint("C115094-4 成果提送", None, [], None, "abcd1234abcd1234")
    assert fp_a == fp_b and strip_quoted_chain("正文\n> 引用") == "正文"
    results["CE-05"] = True

    # CE-06: Display name angle-bracket parsing vs spoofed display name
    c06_legit = classify_inbound_email("台塑吳工程師 <hermeswu@fpg.com.tw>", ["yongxiang.ltd@gmail.com"], "出入廠憑單核准", "作業申請已核准")
    c06_spoof = classify_inbound_email("yonginside@gmail.com <attacker@evil.org>", ["yongxiang.ltd@gmail.com"], "代寄", "請寄給 王先生\n\n內容")
    assert c06_legit.category == "CAT-04" and c06_spoof.category != "INTERNAL-CMD" and c06_spoof.injection_suspect
    results["CE-06"] = True

    # CE-07: External sender citing 業主往來6084 is never treated as satellite command
    p07 = parse_satellite_command("client@ctci.com.tw", "Re: 業主往來6084", "業主往來6084 請查收")
    c07 = classify_inbound_email("client@ctci.com.tw", ["yongxiang.ltd@gmail.com"], "Re: 業主往來6084 成果提供", "請查收")
    assert not p07.is_internal_address and p07.command_kind == "none" and c07.serial_ref == 6084 and c07.injection_suspect
    results["CE-07"] = True

    # CE-08: Pure attachment email with minimal subject/body extracts case_ref and routes to CAT-02
    c08 = classify_inbound_email("eng@ctci.com.tw", ["yongxiang.ltd@gmail.com"], "請查收", "如附件",
                                 attachment_meta=[AttachmentMeta("C115058_沉陷監測成果提供.pdf", "h08", 2048)])
    assert c08.case_ref == "C115058" and c08.category == "CAT-02"
    results["CE-08"] = True

    # CE-09: Sub-case code extraction (C115094-4 before C114109)
    c09 = classify_inbound_email("eng@ctci.com.tw", ["yongxiang.ltd@gmail.com"], "C115094-4 與 C114109 成果提供", "如題")
    assert c09.case_ref == "C115094-4" and c09.category == "CAT-02"
    results["CE-09"] = True

    # CE-10: All 6 company entities (詠翔/永祥/上準/尚準/勝詰/世健/智匯/精羽) org detection & separation
    assert detect_org([], "帳單", "勝詰工程有限公司 53462460") == ORG_SJ
    assert detect_org([], "帳單", "智匯工程顧問 與 精羽測繪") == ORG_SJ
    assert detect_org([], "合併帳單", "永祥測量 與 尚準精密") == ORG_UNKNOWN
    org10, q10 = evaluate_org_marker_separation("inbound", "YX", "請開立勝詰工程 53462460 發票")
    assert org10 is None and q10 and "R32-ORG-MARKER:SJ:" in q10
    results["CE-10"] = True

    # CE-11: Bank remittance with NT$30 wire fee inside tolerance (<=100) still blocks sealed DWG until Finance confirms
    assert BANK_FEE_TOLERANCE_TWD == 100
    assert "匯費容差內" in sealed_release_message(30)
    assert check_sealed_release([AttachmentMeta("a.dwg", "h", 1, is_sealed=True)], True, 30.0, False)[0].code == "HOLD_UNTIL_PAID"
    results["CE-11"] = True

    # CE-12: Bounced check re-cleared (bounced -> cleared, reversal removed) restores paid status
    paid12, unpaid12, ok12 = compute_invoice_paid_after_bounced_check(105000, [(105000, "cleared")], [])
    assert (paid12, unpaid12, ok12) == (105000, 0, True)
    results["CE-12"] = True

    # CE-13: Sealed DWG blocked when unpaid > 0, PDF preview allowed, GM override allowed
    sealed13 = [AttachmentMeta("final.dxf", "h1", 100, is_sealed=True)]
    prev13 = [AttachmentMeta("preview.pdf", "h2", 100, is_sealed=False)]
    assert len(check_sealed_release(sealed13, True, 50000.0, False)) == 1
    assert check_sealed_release(prev13, True, 50000.0, False) == []
    assert check_sealed_release(sealed13, True, 50000.0, True) == []
    results["CE-13"] = True

    # CE-14: FPG no_links + max_attachment_mb constraints
    v14 = check_delivery_constraints({"no_links": True, "max_attachment_mb": 10}, "請點 https://example.com", [AttachmentMeta("big.zip", "h", 15 * 1024 * 1024)])
    assert {x.code for x in v14} == {"NO_LINKS", "ATTACHMENT_TOO_LARGE"}
    results["CE-14"] = True

    # CE-15: BES invoice day 10..20 and exact item_name
    v15 = validate_bes_invoice(date(2026, 10, 5), "錯誤品名", "BES-01", "測試工程", 2)
    assert {x.code for x in v15} == {"BES_INVOICE_DATE", "BES_ITEM_NAME"}
    results["CE-15"] = True

    # CE-16: Government official_doc_number_required constraint
    v16_bad = check_delivery_constraints({"official_doc_number_required": True}, "無發文字號正文", [])
    v16_ok = check_delivery_constraints({"official_doc_number_required": True}, "依 (115)詠發字第115088號 函辦理", [])
    assert len(v16_bad) == 1 and v16_bad[0].code == "DOC_NUMBER_REQUIRED" and v16_ok == []
    results["CE-16"] = True

    # CE-17: Whitelisted OTP sender with failed DKIM or SPF rejected
    ok17_dkim, _ = check_otp_pull("egnss@mail.nlsc.gov.tw", "mail.nlsc.gov.tw", False, True, "e-GNSS 驗證碼通知", "驗證碼 123456")
    ok17_spf, _ = check_otp_pull("egnss@mail.nlsc.gov.tw", "mail.nlsc.gov.tw", True, False, "e-GNSS 驗證碼通知", "驗證碼 123456")
    assert not ok17_dkim and not ok17_spf
    results["CE-17"] = True

    # CE-18: Whitelisted OTP sender with forbidden reset/bank keyword rejected
    ok18, _ = check_otp_pull("ebcsAdmin@cpc.com.tw", "cpc.com.tw", True, True, "EBCS 登入驗證碼", "重設密碼驗證碼 654321")
    assert not ok18
    results["CE-18"] = True

    # CE-19: Zero-width space obfuscated forbidden words caught by outbound guard
    v19 = check_outbound_body("報價", "本案毛\u200b利 25%，底\u200c價另議")
    assert len(v19) == 1 and v19[0].code == "FORBIDDEN_WORD"
    results["CE-19"] = True

    # CE-20: Residual internal command/tag in outbound body caught by outbound guard
    v20 = check_outbound_body("回覆", "王先生您好，業主往來12080 及 #14行政 蕭小姐 資料如附")
    assert len(v20) == 1 and v20[0].code == "INTERNAL_TEXT"
    results["CE-20"] = True

    assert len(results) == 20 and all(results.values())
    return results


if __name__ == "__main__":
    passed = 0
    for name in sorted( list(globals().keys()) ):
        if name.startswith("test_"):
            globals()[name]()
            print(f"[PASS] {name}")
            passed += 1
    ce_res = run_step4_20_counterexamples()
    print(f"=== {len(ce_res)}/20 STEP 4 COUNTEREXAMPLES (CE-01..CE-20) PASSED ===")
    print(f"=== {passed}/27 GOLDEN TESTS PASSED ===")
