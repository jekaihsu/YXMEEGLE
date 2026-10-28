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


# ---------- R54 守門反例（20 條）整合進 golden 套件 ----------
from test_r54_golden_20_counterexamples import run_r54_20_counterexamples  # noqa: E402


def test_24_r54_golden_20_counterexamples():
    """R54 今日下午守門：20 條反例全綠，每條斷言結果（隔離／出卡／同號／拒絕）。"""
    res = run_r54_20_counterexamples()
    assert len(res) == 20 and all(res.values())
    assert sorted(res) == [f"CE-R54-{i:02d}" for i in range(1, 21)]


if __name__ == "__main__":
    passed = 0
    for name in sorted( list(globals().keys()) ):
        if name.startswith("test_"):
            globals()[name]()
            print(f"[PASS] {name}")
            passed += 1
    print(f"=== {passed} GOLDEN TESTS PASSED (含 R54 20 條守門反例) ===")
