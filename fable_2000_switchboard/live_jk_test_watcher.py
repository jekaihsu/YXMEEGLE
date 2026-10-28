#!/usr/bin/env python3
"""Real-time WebSocket + Fast Polling watcher for 永祥 · 業主信件助理 (cli_aa5c5ceba4f8de2a) across JK & 林育寬 bot DM chats."""
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import watcher_chat_state as W

LARK_CLI = "/home/box/.local/bin/lark-cli"
CHAT_ID = "oc_01d9828173a2920809b16248fe28989d"
YUKUAN_CHAT_ID = "oc_9d424caa98d70d2e9d11225e9c00b404"
JK_OPEN_ID = "ou_7dfe7ce548da22a0275cba0d92b3bfec"
YUKUAN_OPEN_ID = "ou_122a1fb91c53f3f5c4d98e612ea8fccc"
VINCENT_OPEN_ID = "ou_0a3751d04da583e3ae596543560ef4b7"
APPROVAL_ID = "f4d6e818-e8a3-47a7-97c8-f60ab989c579"
CASE_CODE = "C115055-1"
# Hard ceiling on every blocking lark-cli call so a single hung Lark API request
# can never freeze a handler while it holds STATE_LOCK (R54 bug #2).
LARK_TIMEOUT = 10
STATE_FILE = Path("/tmp/live_jk_test_watcher_state.json")
STATE_LOCK = threading.Lock()

# R55: hard cap on the persisted dedup sets so a long-running watcher does not
# grow processed_ids / processed_events / reacted_ids without bound. We keep the
# most-recent N ids (insertion order preserved) which is far more than the live
# window of messages that could still be re-delivered by WS or HTTP poll.
DEDUP_MAX = 2000

COMPANY_FULL_NAME = "詠翔測量工程有限公司"
COMPANY_SPECIALTIES = "單/多音束測量 ｜ 側掃聲納 ｜ 水中攝影 ｜ UAV攝影測量 ｜ LiDAR高精度掃描測量"

DEFAULT_BODY_CORE = (
    "林工程師您好：\n"
    "收到您的來信。關於 C115055-1 案之水深與地形測量成果：\n"
    "1. 內業圖資（CAD-C115055-BATHY-v2.dwg）與測量報告初稿目前正最後複核中，預計於本週三（10/28）17:00 前寄出供貴司審閱。\n"
    "2. 本次補充測量項目報價單價為 NT$150,000（未稅），計價數量明細表亦會隨信一併附上。"
)


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_employee_signature(open_id: str = JK_OPEN_ID, fallback_name: str = "許喆凱") -> tuple[str, str, str]:
    """Return (full_name, plain_sig_block, html_sig_block) from public.employee in yongxiang_plumb_r39_clone."""
    if open_id == YUKUAN_OPEN_ID and fallback_name == "許喆凱":
        fallback_name = "林育寬"
    try:
        sql = f"""
        SELECT CASE WHEN full_name = '育寬 林' THEN '林育寬' ELSE full_name END,
               COALESCE(NULLIF(job_title,''), NULLIF(group_name,''), NULLIF(department_name,''), '專案負責人'),
               CASE
                   WHEN full_name = '許喆凱' THEN 'jekai@yxsurvey.com.tw'
                   WHEN lark_open_id = '{YUKUAN_OPEN_ID}' OR full_name IN ('林育寬', '育寬 林') THEN 'linyukuan@yxsurvey.com.tw'
                   WHEN work_email IS NOT NULL AND btrim(work_email) <> '' AND work_email <> '@yxsurvey.com.tw' THEN work_email
                   WHEN regexp_replace(lower(COALESCE(name_pinyin,'')), '[^a-z0-9]', '', 'g') <> '' THEN regexp_replace(lower(COALESCE(name_pinyin,'')), '[^a-z0-9]', '', 'g') || '@yxsurvey.com.tw'
                   ELSE regexp_replace(lower(COALESCE(employee_no,'company')), '[^a-z0-9]', '', 'g') || '@yxsurvey.com.tw'
               END AS email,
               COALESCE(NULLIF(work_phone,''), '05-596-0029'),
               COALESCE(email_signature_text, public.fn_employee_email_signature_text(lark_open_id, full_name)),
               email_signature_html
        FROM public.employee
        WHERE lark_open_id = '{open_id}' OR full_name = '{fallback_name}' OR ( '{fallback_name}' = '林育寬' AND full_name = '育寬 林' )
        ORDER BY (lark_open_id = '{open_id}') DESC
        LIMIT 1;
        """
        out = subprocess.check_output(
            ["psql", "-X", "-d", "yongxiang_plumb_r39_clone", "-At", "-F", "\t", "-c", sql],
            text=True,
            timeout=3,
        ).strip()
        if out:
            parts = out.split("\t")
            name = parts[0] if len(parts) > 0 else fallback_name
            title = parts[1] if len(parts) > 1 else "IT主管"
            email = parts[2] if len(parts) > 2 else "jekai@yxsurvey.com.tw"
            phone = parts[3] if len(parts) > 3 else "05-596-0029"
        else:
            name, title, email, phone = fallback_name, "IT主管", "jekai@yxsurvey.com.tw", "05-596-0029"
    except Exception:
        name, title, email, phone = fallback_name, "IT主管", "jekai@yxsurvey.com.tw", "05-596-0029"

    if name == "育寬 林" or open_id == YUKUAN_OPEN_ID:
        name = "林育寬"
        if not email or "chenyukuan" in email:
            email = "linyukuan@yxsurvey.com.tw"
        if not title or title == "IT":
            title = "IT部門 / 系統開發"

    plain_sig = (
        f"祝 商祺\n"
        f"──────────────────\n"
        f"{name}｜{title}\n"
        f"{COMPANY_FULL_NAME}\n"
        f"電話：{phone}\n"
        f"Email：{email}\n"
        f"地址：632 雲林縣虎尾鎮虎中街13號｜網站：www.yxsurvey.com.tw\n"
        f"{COMPANY_SPECIALTIES}"
    )
    html_sig = f"""<table cellpadding="0" cellspacing="0" border="0" style="font-family:'Microsoft JhengHei','PingFang TC',Arial,sans-serif;color:#333;font-size:13px;line-height:1.5;">
<tr><td style="padding-right:14px;border-right:3px solid #0b5e8a;vertical-align:middle;text-align:center;">
<a href="https://www.yxsurvey.com.tw/"><img src="https://www.yxsurvey.com.tw/wp-content/uploads/2020/09/0607png%E8%B3%87%E7%94%A2-1-8.png" alt="{COMPANY_FULL_NAME}" width="110" style="display:block;width:110px;height:auto;border:0;"></a></td>
<td style="padding-left:14px;vertical-align:top;">
<div style="font-size:16px;font-weight:bold;color:#222;">{name}</div>
<div style="color:#0b5e8a;">{title}</div>
<div style="font-weight:bold;margin-bottom:6px;">{COMPANY_FULL_NAME}</div>
<div>電話：{phone}</div>
<div>Email：<a href="mailto:{email}" style="color:#333;text-decoration:none;">{email}</a></div>
<div>地址：632 雲林縣虎尾鎮虎中街13號</div>
<div><a href="https://www.yxsurvey.com.tw/" style="color:#0b5e8a;text-decoration:none;">www.yxsurvey.com.tw</a></div>
<div style="font-size:11px;color:#888;margin-top:4px;">{COMPANY_SPECIALTIES}</div>
</td></tr></table>"""
    return name, plain_sig, html_sig


def resolve_colleague_in_text(text: str) -> tuple[str, str]:
    """Find any active employee full_name mentioned in text and return (lark_open_id, full_name)."""
    if "林育寬" in text or "育寬" in text:
        return YUKUAN_OPEN_ID, "林育寬"
    try:
        sql = """
        SELECT COALESCE(lark_open_id, ''), CASE WHEN full_name = '育寬 林' THEN '林育寬' ELSE full_name END AS fn
        FROM public.employee
        WHERE employment_status = 'active'
        ORDER BY length(full_name) DESC;
        """
        out = subprocess.check_output(
            ["psql", "-X", "-d", "yongxiang_plumb_r39_clone", "-At", "-F", "\t", "-c", sql],
            text=True,
            timeout=3,
        ).strip()
        for line in out.splitlines():
            if "\t" not in line:
                continue
            oid, fn = line.split("\t", 1)
            if fn and fn in text:
                return oid or JK_OPEN_ID, fn
    except Exception:
        pass
    return "", ""


def normalize_company_and_attach_sig(draft_text: str, open_id: str = JK_OPEN_ID, fallback_name: str = "許喆凱") -> str:
    """Ensure official tax/legal name 詠翔測量工程有限公司 is used on the email signature and colleague's personal signature block is attached."""
    _, plain_sig, _ = get_employee_signature(open_id, fallback_name)
    cleaned = draft_text.replace("永祥測量工程股份有限公司", COMPANY_FULL_NAME).replace("永祥測量有限公司", COMPANY_FULL_NAME)
    cleaned = re.sub(r"\n*(?:祝\s*商祺\s*\n*)?─+\n[\s\S]*$", "", cleaned).strip()
    cleaned = re.sub(r"\n*(?:永祥測量|永祥工程|永祥測量工程股份有限公司|詠翔測量|詠翔測量工程有限公司)[^\n]*敬上\s*$", "", cleaned).strip()
    return f"{cleaned}\n\n{plain_sig}"


def load_state():
    if STATE_FILE.exists():
        try:
            st = json.loads(STATE_FILE.read_text())
            st.setdefault("processed_ids", [])
            st.setdefault("processed_events", [])
            st.setdefault("reacted_ids", [])
            st.setdefault("current_draft", normalize_company_and_attach_sig(DEFAULT_BODY_CORE))
            st.setdefault("draft_version", 2)
            st.setdefault("status", "approved")
            st.setdefault("locked_by_open_id", "")
            st.setdefault("locked_by_name", "")
            st.setdefault("active_card_msg_id", "om_x100b62eef0c5f4a0ffd7d56025a5289")
            st.setdefault("all_card_msg_ids", ["om_x100b62ee23a3f4a0fe22829f25972d5", "om_x100b62eef0c5f4a0ffd7d56025a5289"])
            st.setdefault("watched_chats", [CHAT_ID])
            st.setdefault("user_chat_map", {JK_OPEN_ID: CHAT_ID, YUKUAN_OPEN_ID: YUKUAN_CHAT_ID})
            st.setdefault("card_chat_map", {})
            # R54: lift the legacy single-global draft/lock into per-chat + per-case shape.
            return W.migrate_legacy_state(st, st.get("current_draft") or normalize_company_and_attach_sig(DEFAULT_BODY_CORE), CHAT_ID)
        except Exception:
            pass
    fresh = {
        "processed_ids": [],
        "processed_events": [],
        "reacted_ids": [],
        "current_draft": normalize_company_and_attach_sig(DEFAULT_BODY_CORE),
        "draft_version": 2,
        "status": "approved",
        "locked_by_open_id": "",
        "locked_by_name": "",
        "active_card_msg_id": "om_x100b62eef0c5f4a0ffd7d56025a5289",
        "all_card_msg_ids": ["om_x100b62ee23a3f4a0fe22829f25972d5", "om_x100b62eef0c5f4a0ffd7d56025a5289"],
        "watched_chats": [CHAT_ID],
        "user_chat_map": {JK_OPEN_ID: CHAT_ID, YUKUAN_OPEN_ID: YUKUAN_CHAT_ID},
        "card_chat_map": {},
    }
    return W.migrate_legacy_state(fresh, fresh["current_draft"], CHAT_ID)


def _trim(lst):
    """Keep only the most-recent DEDUP_MAX ids (insertion order preserved)."""
    if isinstance(lst, list) and len(lst) > DEDUP_MAX:
        del lst[: len(lst) - DEDUP_MAX]
    return lst


def save_state(state):
    # R55: bound the persisted dedup sets so they cannot grow forever.
    for k in ("processed_ids", "processed_events", "reacted_ids"):
        if k in state:
            _trim(state[k])
    # R55: atomic write so a crash mid-write can never leave a truncated /
    # unparseable state file (which would silently reset ALL dedup on restart
    # and cause double-react / double-process).
    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    os.replace(tmp, STATE_FILE)


def react_to_message(msg_id: str, emoji_type: str = "OK", dry_run: bool = False) -> dict:
    """Immediately add an emoji reaction (<1s) so user knows bot received their message."""
    t0 = time.perf_counter()
    if not msg_id:
        return {"ok": False, "elapsed_ms": 0.0}
    if dry_run or os.environ.get("DRY_RUN_STRESS_TEST") == "1":
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {"ok": True, "emoji_type": emoji_type, "msg_id": msg_id, "elapsed_ms": round(elapsed_ms, 3)}
    try:
        proc = subprocess.run(
            [
                LARK_CLI,
                "api",
                "POST",
                f"/open-apis/im/v1/messages/{msg_id}/reactions",
                "--as",
                "bot",
                "--data",
                json.dumps({"reaction_type": {"emoji_type": emoji_type}}),
            ],
            capture_output=True,
            text=True,
            timeout=6,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        ok = proc.returncode == 0
        log(f"Added reaction {emoji_type} to {msg_id} ({elapsed_ms:.1f}ms, ok={ok})")
        return {"ok": ok, "emoji_type": emoji_type, "msg_id": msg_id, "elapsed_ms": round(elapsed_ms, 2)}
    except Exception as e:
        log(f"Reaction error: {e}")
        return {"ok": False, "error": str(e)}


BASELINE_QUOTE_NTD = 150000
AUTHORIZED_COMMERCIAL_APPROVERS = {JK_OPEN_ID}
ALLOWED_EMAIL_DOMAINS = {"yxsurvey.com.tw", "ceci.org.tw", "example.com"}
UNDO_GRACE_SECONDS = 30
ALLOWED_TEST_RECIPIENT = "jekai@yxsurvey.com.tw"
PENDING_JK_FINAL_APPROVAL = "PENDING_JK_FINAL_APPROVAL"
INTENDED_CLIENT_RECIPIENT = "台灣世曦 · 林工程師 <lin.ceci@example.com>"
RECIPIENT_BADGE_TEXT = f"🎯 按下後實際收件人：{INTENDED_CLIENT_RECIPIENT}"
TEST_PROTECTION_BADGE_TEXT = "🎯 測試保護中：按下只會寄至 jekai@yxsurvey.com.tw（許竣凱），不會外發業主"


def enforce_test_recipient_allowlist(recipient: str) -> str:
    """Hard Lock #2: Programmatic allowlist guard for test/dry-run/preview email dispatch."""
    norm = (recipient or "").strip().lower()
    if not norm or "@gmail.com" in norm or norm != ALLOWED_TEST_RECIPIENT:
        raise PermissionError(
            f"BLOCKED_NON_WHITELIST_RECIPIENT: recipient {recipient!r} is forbidden in test mode; "
            f"only {ALLOWED_TEST_RECIPIENT} is allowed"
        )
    return ALLOWED_TEST_RECIPIENT


def classify_security_gate(reason: str, fallback: str = "G01_PRANK_SPAM") -> str:
    r = reason or ""
    if "重複洗版" in r or "情緒抱怨" in r or "惡搞" in r or "重複字元" in r:
        return "G01_PRANK_SPAM"
    if "提示詞注入" in r or "越權繞過" in r:
        return "G05_PROMPT_INJECTION"
    if "收件網域" in r or "外部私人信箱" in r or "外部雲端連結" in r:
        return "G06_RECIPIENT_DOMAIN"
    if "重大商業變更" in r or "無直接核准外發權限" in r or "權限分級" in r:
        return "G07_RBAC_ESCALATION"
    if "機密財務" in r or "合理工程報價範圍" in r or "法律責任" in r or "匯款帳戶" in r:
        return "G08_MARGIN_PRICE_BOUNDS"
    if "舊版卡片" in r:
        return "G09_STALE_CARD_CAS"
    if "防撞" in r or "認領鎖定" in r:
        return "G10_SOFTLOCK_COLLISION"
    if "未偵測到明確的商務改稿意圖" in r:
        return "G04_STRUCTURED_SLOTS"
    return fallback


GATE_NAMES_MAP = {
    "G01": "惡搞與重複洗版攔截閘",
    "G02": "兩階段核准強制分離閘",
    "G03": "語意包裝前綴後綴剝離閘",
    "G04": "4向意圖分流與白名單槽位閘",
    "G05": "提示詞注入與越權繞過攔截閘",
    "G06": "收件網域白名單與防外洩閘",
    "G07": "RBAC 商業變更主管升級閘",
    "G08": "底價毛利機密與報價邊界閘",
    "G09": "卡片版本 CAS 樂觀鎖防舊卡閘",
    "G10": "跨對話隔離與全局認領防撞軟鎖閘",
}


def record_security_intercept(
    state: dict | None,
    chat_id: str,
    actor_open_id: str,
    actor_name: str,
    input_text: str,
    reason: str,
    gate: str = "",
) -> None:
    if state is None:
        return
    gate_code = gate or classify_security_gate(reason)
    gate_id = gate_code.split("_", 1)[0] if "_" in gate_code else gate_code[:3]
    gate_name = GATE_NAMES_MAP.get(gate_id, gate_code)
    logs = state.setdefault("security_intercept_log", [])
    logs.append({
        "id": f"intercept-{int(time.time()*1000)}",
        "ts": int(time.time()),
        "time_label": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "case_code": CASE_CODE,
        "chat_id": chat_id or "__default__",
        "actor_open_id": actor_open_id,
        "actor_name": actor_name,
        "input_text": input_text,
        "raw_input": input_text,
        "gate": gate_code,
        "gate_id": gate_id,
        "gate_name": gate_name,
        "reason": reason,
        "action_taken": "BLOCKED_KEEP_PENDING",
    })
    if len(logs) > 200:
        del logs[: len(logs) - 200]
    gstats = state.setdefault("gate_stats", {})
    for k in (gate_code, gate_id):
        gentry = gstats.setdefault(k, {"passed": 0, "blocked": 0})
        gentry["blocked"] = int(gentry.get("blocked", 0)) + 1


def build_interactive_card(
    draft_text: str,
    version: int = 1,
    status: str = "pending",
    note_line: str = "",
    actor_name: str = "許喆凱",
    risk_badge: str = "",
) -> dict:
    """Build a mobile-first, non-truncated Card 2.0 JSON for #C115055-1."""
    if status == "approved":
        template = "green"
        tag_text = "✅ 已核准寄出"
        tag_color = "green"
        status_banner = (
            "<font color='green'>✅ **JK 最終審核已放行（測試保護僅寄至 jekai@yxsurvey.com.tw，未外發給業主）**\n"
            "🔒 防撞鎖已生效（其他同仁不會重複回信），並已同步歸檔至永祥「業主往來紀錄」。\n"
            "↩️ **30 秒撤回緩衝期（Undo Grace Period）**：若誤按核准，可於 30 秒內點擊下方按鈕或打字輸入「**撤回**」恢復待確認狀態。</font>"
        )
    elif status in ("PENDING_JK_FINAL_APPROVAL", "pending_jk_final_approval"):
        template = "orange"
        tag_text = "⏸️ 待 JK 最終審核"
        tag_color = "orange"
        status_banner = (
            f"<font color='orange'>⏸️ **已由 {actor_name} 回覆確認，目前卡住等待 JK 最終審核（狀態：PENDING_JK_FINAL_APPROVAL，嚴禁自動寄出）**\n"
            f"{RECIPIENT_BADGE_TEXT}\n"
            f"{TEST_PROTECTION_BADGE_TEXT}</font>"
        )
    elif status == "claimed":
        template = "wathet"
        tag_text = "🔒 處理中"
        tag_color = "blue"
        status_banner = f"🔒 **已由 {actor_name} 認領處理中**（防撞軟鎖已生效，請直接在下方打字告訴我怎麼改稿）"
    elif status == "collision_softlock":
        template = "orange"
        tag_text = "⚠️ 防撞攔截"
        tag_color = "orange"
        status_banner = f"⚠️ **防撞軟鎖提醒：本案目前正由 {actor_name} 認領編輯中**（如需接手請輸入「強制接手」或請原負責人「轉交」）"
    elif status == "handoff":
        template = "wathet"
        tag_text = f"↪️ 已轉交 {actor_name}"
        tag_color = "blue"
        status_banner = f"↪️ **已轉交由 {actor_name} 接手處理**（簽名檔已自動切換為 {actor_name} 專屬簽名檔）"
    elif risk_badge:
        template = "orange"
        tag_text = f"⚠️ 需主管複核 v{version}"
        tag_color = "orange"
        status_banner = (
            "💡 **請過目下方回信草稿（含您的個人專屬簽名檔）**：本草稿含重大商業變更，須由授權主管複核後按 **【✅ 核准並寄出】**；或輸入「恢復原稿」還原。"
        )
    else:
        template = "blue"
        tag_text = f"待確認 v{version}"
        tag_color = "blue"
        status_banner = "💡 **請過目下方回信草稿（含您的個人專屬簽名檔）**：沒問題請按 **【✅ 核准並寄出】**；想改內容請直接在下方打字。"

    elements = [
        {
            "tag": "markdown",
            "content": (
                "**📥 來信重點**：詢問 10 月份 CAD 圖資與報告初稿何時提供審閱，並請附計價明細（⏰ 期限：10/28 17:00）\n"
                "**📐 圖資與報價**：`CAD-C115055-BATHY-v2.dwg` ｜ 補充測量 **NT$ 150,000（未稅）**"
            ),
        },
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": f"**✉️ 擬妥之回信草稿（v{version} · 含專屬簽名檔）**\n"
            + "\n".join(f"> {line}" if line.strip() else ">" for line in draft_text.splitlines()),
        },
    ]

    if risk_badge:
        elements.append({"tag": "markdown", "content": f"<font color='orange'>⚠️ **風險警示（Risk Badge）**：{risk_badge}</font>"})

    if note_line:
        elements.append({"tag": "markdown", "content": f"<font color='green'>{note_line}</font>"})

    elements.append({"tag": "markdown", "content": status_banner})
    elements.append(
        {
            "tag": "markdown",
            "content": f"**{RECIPIENT_BADGE_TEXT}**\n<font color='grey'>{TEST_PROTECTION_BADGE_TEXT}</font>",
        }
    )

    if status != "approved":
        btn_label = (
            "🔐 JK 最終審核放行（僅限許竣凱）"
            if status in ("PENDING_JK_FINAL_APPROVAL", "pending_jk_final_approval")
            else "✅ 核准（同事回覆後待 JK 最終審核）"
        )
        btn_action = (
            "jk_final_approve"
            if status in ("PENDING_JK_FINAL_APPROVAL", "pending_jk_final_approval")
            else "approve_send"
        )
        elements.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": btn_label},
                "type": "primary_filled",
                "width": "fill",
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {
                            "action": btn_action,
                            "case_code": "C115055-1",
                            "draft_version": str(version),
                            "actual_recipient": INTENDED_CLIENT_RECIPIENT,
                            "allowed_test_recipient": ALLOWED_TEST_RECIPIENT,
                        },
                    }
                ],
            }
        )
        elements.append(
            {
                "tag": "column_set",
                "flex_mode": "bisect",
                "horizontal_spacing": "8px",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [
                            {
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "✏️ 改週四交"},
                                "type": "default",
                                "width": "fill",
                                "behaviors": [
                                    {
                                        "type": "callback",
                                        "value": {
                                            "action": "edit_thu",
                                            "case_code": "C115055-1",
                                            "draft_version": str(version),
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [
                            {
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "🔒 我來處理"},
                                "type": "default",
                                "width": "fill",
                                "behaviors": [
                                    {
                                        "type": "callback",
                                        "value": {
                                            "action": "claim",
                                            "case_code": "C115055-1",
                                            "draft_version": str(version),
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        )
    else:
        elements.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "↩️ 30秒內撤回寄送 (Undo)"},
                "type": "default",
                "width": "fill",
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {
                            "action": "undo_send",
                            "case_code": "C115055-1",
                            "draft_version": str(version),
                        },
                    }
                ],
            }
        )

    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": ("✅ 已核准並寄出｜#C115055-1 台61線西濱水深地形測量" if status == "approved" else "📩 業主來信待確認｜#C115055-1 台61線西濱水深地形測量"),
            },
            "subtitle": {"tag": "plain_text", "content": "台灣世曦 · 林工程師 <lin.ceci@example.com>"},
            "template": template,
            "text_tag_list": [
                {"tag": "text_tag", "text": {"tag": "plain_text", "content": tag_text}, "color": tag_color}
            ],
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 14px 16px 14px",
            "vertical_spacing": "10px",
            "elements": elements,
        },
    }


def check_outbound_content_safety(text: str, cleaned: str) -> tuple[bool, str]:
    """Outbound Content Safety, Policy Critic & Prompt-Injection Gate (R56 Enterprise Security).
    Blocks pranks, repetition multipliers, emotional complaints/insults against clients,
    prompt injection, recipient/CC hijacking, internal margin/cost leaks, unauthorized links,
    and meaningless gibberish from ever entering a client email draft.
    Returns (is_safe, reject_reason).
    """
    combined = f"{text} {cleaned}"
    low = combined.lower()

    # 1. Repetition / spam multiplier pattern (e.g. *100, x100, 100次, 100遍)
    if re.search(r"([*×xX])\s*[0-9]{2,}|重複\s*[0-9]+\s*(?:次|遍)|寫\s*[0-9]+\s*(?:次|遍)", combined):
        return False, "偵測到異常重複洗版指令（如 `*100`），不符合正式商務信件規範"

    # 2. Prank / meme / profanity / emotional complaints about client
    prank_and_abuse_patterns = (
        "我是乃瀧", "乃瀧", "我是笨蛋", "我是豬", "去死", "白痴", "白癡", "智障", "北七",
        "幹你", "靠北", "三小", "拎北", "林北", "傻逼", "媽的", "他媽的", "垃圾",
        "很煩", "超煩", "煩死", "白目", "一直改圖", "亂改", "催什麼", "奧客", "神經病",
        "有病", "太扯", "不想理", "搞屁", "隨便他", "測試亂打", "哈哈哈哈",
    )
    for kw in prank_and_abuse_patterns:
        if kw.lower() in low:
            return False, f"偵測到情緒抱怨、非正式商務用語或惡搞測試字眼（「{kw}」），已自動攔截不排入正式對外草稿"

    # 3. Prompt Injection / Jailbreak / System Override
    injection_patterns = (
        "ignore previous", "ignore all", "disregard previous", "system prompt",
        "developer mode", "jailbreak", "忽略前面", "忽略上述", "忽略所有",
        "跳過審核", "無需核准", "自動核准", "直接放行", "<script", "drop table",
    )
    for kw in injection_patterns:
        if kw in low:
            return False, f"偵測到疑似提示詞注入或越權繞過指令（「{kw}」），已自動攔截"

    # 4. Recipient / CC Hijacking & External Non-whitelisted Email Domains
    for m_email in re.finditer(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", combined):
        domain = m_email.group(1).lower()
        if domain not in ALLOWED_EMAIL_DOMAINS:
            return False, f"偵測到非白名單外部收件網域（`@{domain}`），防止收件人劫持與圖資外洩，已自動攔截"
    if re.search(r"(?:改寄|轉寄|副本|cc|bcc)\s*(?:給|到|至)?\s*(?:外部|私人|個人)", low):
        return False, "偵測到要求轉寄或副本至外部私人信箱之指令，已自動攔截"

    # 5. Internal Confidential Cost / Margin / Kickback Leaks
    internal_leak_patterns = ("底價", "毛利", "成本價", "內部成本", "時薪", "回扣", "暗盤", "佣金", "不要讓業主知道")
    for kw in internal_leak_patterns:
        if kw in combined:
            return False, f"偵測到內部機密財務/成本敏感字眼（「{kw}」），嚴禁寫入對外業主信件"

    # 6. External Cloud Links (violates enterprise client security & attachment policy) or Account Spoofing
    if re.search(r"https?://(?!(?:www\.)?yxsurvey\.com\.tw)|drive\.google|dropbox\.com|onedrive", low):
        return False, "偵測到外部雲端連結（業主資安規範禁止外網雲端連結，且易遭退信），已自動攔截"
    if any(k in combined for k in ("違約金我們吸收", "賠償全部", "免費奉送", "不用付錢", "匯款帳戶改", "改匯到")):
        return False, "偵測到未授權之法律責任免除或變更匯款帳戶承諾，已自動攔截"

    # 7. Excessive character repetition (e.g. 啊啊啊啊啊, excluding divider lines ─ or -)
    if re.search(r"([A-Za-z\u4e00-\u9fff])\1{5,}", cleaned):
        return False, "偵測到異常重複字元，已自動攔截"

    return True, ""


validate_outbound_draft_safety = check_outbound_content_safety


def strip_meta_edit_wrappers(text: str) -> str:
    """Strip meta prefix ('把內容改成...') and meta suffix ('...就可以寄出了') so command wrappers never leak into email body."""
    s = text.strip()
    s = re.sub(
        r"^(?:請幫我把內容改成|幫我把內容改成|把內容改成|請把內容改成|把信件內容改成|把內文改成|幫我改成跟他說|幫我跟他說|幫我改成|請幫我改成|幫我改|改成|修改為|改為|請改|跟他說|回覆他說|回信說)[：:，,\s]*",
        "",
        s,
    ).strip()
    s = re.sub(
        r"[，,。\s]*(?:就可以寄出了|就直接寄出|並直接寄出|然後寄出|並寄出|就可以發了|直接寄出|直接發|寄出即可|即可寄出)[！!。\s]*$",
        "",
        s,
    ).strip()
    return s


def _set_slot_risk_meta(state: dict, chat_id: str, seed: str, requires_mgr: bool, risk_badge: str) -> None:
    if state is None:
        return
    slot = W.ensure_chat_slot(state, chat_id, seed)
    slot["requires_manager_approval"] = bool(requires_mgr)
    slot["risk_badge"] = risk_badge or ""
    state["_last_risk_badge"] = risk_badge or ""


def _get_slot_risk_meta(state: dict, chat_id: str, seed: str) -> tuple[bool, str]:
    if state is None:
        return False, ""
    slot = W.ensure_chat_slot(state, chat_id, seed)
    return bool(slot.get("requires_manager_approval", False)), str(slot.get("risk_badge") or "")


def apply_nl_edit(draft: str, text: str, open_id: str = JK_OPEN_ID, state: dict = None, chat_id: str = "") -> tuple[str, str]:
    """Enterprise Structured Business Intent Parser & Rewriter with:
    1) Strict Outbound Content Safety Gate (blocks pranks/gibberish/repetition/complaints/injections/CC hijacking/margin leaks),
    2) Two-Phase Commit (any edit ALWAYS produces a pending preview card first; NEVER edits and sends in one turn),
    3) Structured Intent Whitelist (NEVER blindly replaces draft with raw `• {cleaned_input}`),
    4) Role & Authority Escalation Guard (project decline or >±10% price changes by non-PM/non-manager require manager approval).
    """
    t = text.strip()
    sender_name, _, _ = get_employee_signature(open_id)
    seed = normalize_company_and_attach_sig(DEFAULT_BODY_CORE)
    eff_chat_id = chat_id or (resolve_target_chat(state, open_id) if state is not None else "")

    if any(k in t for k in ("轉交", "交給", "改由", "接手")) and "強制接手" not in t:
        target_oid, target_name = resolve_colleague_in_text(t)
        if target_name:
            core = re.sub(r"\n*(?:祝\s*商祺\s*\n*)?─+\n[\s\S]*$", "", draft).strip()
            idx = t.find(target_name) + len(target_name)
            note_Match = re.sub(r"^[，,：:\s]*(?:處理|確認|複核|負責|接手|幫看)?[，,：:\s]*", "", t[idx:]).strip()
            if note_Match:
                is_safe_note, reason = check_outbound_content_safety(note_Match, note_Match)
                if not is_safe_note:
                    if state is not None:
                        state["_last_reject_reason"] = reason
                    return draft, "rejected_unsafe"
                core += f"\n• 內部交辦備註（由 {target_name} 接手）：{note_Match}。"
            if state is not None:
                W.acquire_lock(state, CASE_CODE, target_oid, target_name)
            return normalize_company_and_attach_sig(core, target_oid, target_name), "handoff"

    if state is not None:
        if W.is_locked_by_other(state, CASE_CODE, open_id) and "強制接手" not in t:
            return draft, "collision_softlock"

    # Undo Send / Recall within 30s Grace Period
    if t.lower() in ("撤回", "取消寄送", "撤回寄送", "取消核准", "undo", "undo send", "收回", "撤回信件") or any(
        k in t.lower() for k in ("撤回寄送", "取消寄送", "撤回核准", "撤回剛才", "undo send")
    ):
        return draft, "undo_send"

    # Reset / Restore original draft intent (available anytime before approve check)
    if any(k in t for k in ("恢復原稿", "回復原稿", "重置草稿", "還原草稿", "還是接", "正常交件")):
        core = DEFAULT_BODY_CORE
        _set_slot_risk_meta(state, eff_chat_id, seed, False, "")
        return normalize_company_and_attach_sig(core, open_id, sender_name), "edit_draft"

    if t in ("1", "核准", "好，寄出", "寄出", "OK", "ok", "同意", "核准寄出", "好", "確認寄出", "核准並寄出", "沒問題，核准寄出", "好，照這樣寄出"):
        is_safe, reason = check_outbound_content_safety(draft, draft)
        if not is_safe:
            if state is not None:
                state["_last_reject_reason"] = reason
            return draft, "rejected_unsafe"
        req_mgr, r_badge = _get_slot_risk_meta(state, eff_chat_id, seed)
        if req_mgr and open_id not in AUTHORIZED_COMMERCIAL_APPROVERS:
            if state is not None:
                state["_last_reject_reason"] = (
                    f"本草稿含重大商業變更（{r_badge or '婉拒承接或報價調整逾 ±10%'}），"
                    f"操作者（{sender_name}）無直接核准外發權限，須由專案主管／總經理（許喆凱）複核核准，或請先輸入「恢復原稿」"
                )
            return draft, "rejected_unauthorized"
        return normalize_company_and_attach_sig(draft, open_id, sender_name), "approve"

    if t in ("2", "認領", "我來處理", "鎖定", "強制接手"):
        if state is not None:
            W.acquire_lock(state, CASE_CODE, open_id, sender_name)
        return normalize_company_and_attach_sig(draft, open_id, sender_name), "claim"

    # LangChain Agent-Inbox / 12-Factor Agents (Factor 7 & 8) 4-Way Intent Router:
    # Strictly separate 'Internal Question / Consultation to Agent' from 'Outbound Draft Edit'!
    # If a colleague asks a question (e.g. '這案子怎麼又改了？', '請問這張圖是哪一版？', '為什麼報價是15萬？'),
    # answer internally with case facts and NEVER mutate or bump the outbound client email draft.
    is_edit_command = any(k in t for k in ("把內容改成", "幫我改", "改成", "修改為", "改為", "加註", "報價改", "單價改", "改週", "改星期", "改禮拜"))
    is_question = (
        ("?" in t or "？" in t or any(q in t for q in ("為什麼", "怎麼又", "請問", "是多少", "哪一版", "誰負責", "什麼時候收到", "目前進度", "查一下")))
        and not is_edit_command
    )
    if is_question:
        is_safe_q, reason_q = check_outbound_content_safety(t, t)
        if not is_safe_q:
            if state is not None:
                state["_last_reject_reason"] = reason_q
            return draft, "rejected_unsafe"
        return draft, "internal_question"

    # Strip meta wrappers before content check & structured intent parsing
    cleaned_input = strip_meta_edit_wrappers(t)
    is_safe, reason = check_outbound_content_safety(t, cleaned_input)
    if not is_safe:
        if state is not None:
            state["_last_reject_reason"] = reason
        return draft, "rejected_unsafe"

    core = re.sub(r"\n*(?:祝\s*商祺\s*\n*)?─+\n[\s\S]*$", "", draft).strip()
    core = re.sub(r"\n*(?:永祥測量|永祥工程|永祥測量工程股份有限公司|詠翔測量|詠翔測量工程有限公司)[^\n]*敬上\s*$", "", core).strip()

    # Structured Intent 1: Project Decline / Refusal (High-Risk Commercial Action)
    if any(k in t for k in ("不做了", "不接", "不承接", "婉拒", "無法承接", "不做", "放棄承接")):
        core = (
            "林工程師您好：\n"
            "收到您的來信。經公司內部評估目前產能與排程後，本案（#C115055-1 台61線西濱水深地形測量）後續補充測量工作我們決定不再承接辦理。\n"
            "造成貴司不便之處，敬請見諒，並感謝貴司過往的支持與協助。"
        )
        needs_mgr = open_id not in AUTHORIZED_COMMERCIAL_APPROVERS
        badge = "重大商業變更：婉拒承接本案（須由專案主管／總經理許喆凱複核核准）" if needs_mgr else "重大商業變更提醒：婉拒承接本案"
        _set_slot_risk_meta(state, eff_chat_id, seed, needs_mgr, badge)
        return normalize_company_and_attach_sig(core, open_id, sender_name), "edit_draft"

    changed = False
    risk_notes = []
    needs_mgr_flag, existing_badge = _get_slot_risk_meta(state, eff_chat_id, seed)

    # Structured Intent 2: Price / Quote Adjustment
    m_price = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(萬|千|w|W)?", cleaned_input)
    if ("單價" in t or "報價" in t or "萬" in t or "元" in t or "錢" in t or "價" in t or "費用" in t) and m_price:
        val = float(m_price.group(1))
        unit = m_price.group(2) or ""
        amt = int(round(val * 10000)) if unit in ("萬", "w", "W") else (int(round(val * 1000)) if unit == "千" else int(round(val)))
        if amt < 10000 or amt > 5000000:
            if state is not None:
                state["_last_reject_reason"] = f"報價金額（NT${amt:,}）超出本案合理工程報價範圍（NT$10,000 ~ NT$5,000,000），疑似誤植或異常指令，已攔截"
            return draft, "rejected_unsafe"
        if "NT$" in core:
            core = re.sub(r"NT\$[0-9,]+（未稅）", f"NT${amt:,}（未稅）", core)
        else:
            core += f"\n2. 本次補充測量項目報價調整為 NT${amt:,}（未稅）。"
        changed = True
        diff_ratio = abs(amt - BASELINE_QUOTE_NTD) / float(BASELINE_QUOTE_NTD)
        if diff_ratio > 0.10:
            pct = int(round(diff_ratio * 100))
            if open_id not in AUTHORIZED_COMMERCIAL_APPROVERS:
                needs_mgr_flag = True
                risk_notes.append(f"報價調整逾 ±10%（原 NT${BASELINE_QUOTE_NTD:,} → NT${amt:,}，變動 {pct}%，須由主管許喆凱複核）")
            else:
                risk_notes.append(f"報價調整逾 ±10%（原 NT${BASELINE_QUOTE_NTD:,} → NT${amt:,}，變動 {pct}%）")

    # Structured Intent 3: Delivery Schedule / Deadline Adjustment
    weekday_map = {
        "週一": "本週一（10/26）", "星期一": "本週一（10/26）", "禮拜一": "本週一（10/26）", "周一": "本週一（10/26）",
        "週二": "本週二（10/27）", "星期二": "本週二（10/27）", "禮拜二": "本週二（10/27）", "周二": "本週二（10/27）",
        "週三": "本週三（10/28）", "星期三": "本週三（10/28）", "禮拜三": "本週三（10/28）", "周三": "本週三（10/28）",
        "週四": "本週四（10/29）", "星期四": "本週四（10/29）", "禮拜四": "本週四（10/29）", "周四": "本週四（10/29）",
        "週五": "本週五（10/30）", "星期五": "本週五（10/30）", "禮拜五": "本週五（10/30）", "周五": "本週五（10/30）",
        "下週一": "下週一（11/2）", "下星期一": "下週一（11/2）", "下禮拜一": "下週一（11/2）",
        "下週二": "下週二（11/3）", "下星期二": "下週二（11/3）", "下禮拜二": "下週二（11/3）",
        "下週三": "下週三（11/4）", "下星期三": "下週三（11/4）", "下禮拜三": "下週三（11/4）",
    }
    matched_day = None
    for kw in sorted(weekday_map.keys(), key=len, reverse=True):
        if kw in t:
            matched_day = weekday_map[kw]
            break
    if matched_day:
        tod = "中午前" if "中午" in t else ("下班前" if "下班" in t else ("上午前" if "上午" in t else "17:00 前"))
        time_str = f"{matched_day}{tod}"
        if re.search(r"(?:本週|下週)[一二三四五六日]（[^）]+）[^\s，。]+前", core):
            core = re.sub(r"(?:本週|下週)[一二三四五六日]（[^）]+）[^\s，。]+前", time_str, core)
        else:
            core += f"\n• 預計提送時間調整為：{time_str}。"
        changed = True

    # Structured Intent 4: Engineering Scope / Deliverable / Technical Note Supplement
    scope_keywords = (
        "加註", "補充", "說明", "範圍", "加密斷面", "不含", "先提供", "控制點",
        "潮位", "先交", "分批", "補齊", "圖資", "報告", "斷面", "高程", "座標",
        "測量", "初稿", "複核", "修正", "格式", "PDF", "pdf", "DWG", "dwg", "明細", "數量",
    )
    if any(k in t for k in scope_keywords) and not matched_day:
        cleaned_note = strip_meta_edit_wrappers(re.sub(r"^(?:加註|補充說明|補充|說明)[：:，,\s]*", "", cleaned_input)).rstrip("。！!")
        if cleaned_note:
            if re.search(r"\n3\.\s*補充說明：[^\n]*", core):
                core = re.sub(r"\n3\.\s*補充說明：[^\n]*", f"\n3. 補充說明：{cleaned_note}。", core)
            else:
                core += f"\n3. 補充說明：{cleaned_note}。"
            changed = True

    if not changed:
        # Refuse arbitrary free-form replacement that lacks a recognized business intent!
        if state is not None:
            state["_last_reject_reason"] = (
                "未偵測到明確的商務改稿意圖（系統已關閉無腦字串直貼，僅開放：交期調整、報價修改、測量範圍/圖資補充說明、轉交同仁、恢復原稿），"
                "為防止口語或非商務文字誤入正式信件，原草稿保持不變"
            )
        return draft, "rejected_unsafe"

    if risk_notes:
        _set_slot_risk_meta(state, eff_chat_id, seed, needs_mgr_flag, "；".join(risk_notes))
    else:
        _set_slot_risk_meta(state, eff_chat_id, seed, needs_mgr_flag, existing_badge)

    final_draft = normalize_company_and_attach_sig(core, open_id, sender_name)
    if state is not None:
        mem = state.setdefault("edit_memory_log", [])
        mem.append({
            "case_code": CASE_CODE,
            "chat_id": eff_chat_id or "__default__",
            "actor_open_id": open_id,
            "actor_name": sender_name,
            "instruction": t,
            "risk_badge": "；".join(risk_notes) if risk_notes else existing_badge,
            "ts": int(time.time()),
        })
        if len(mem) > 200:
            del mem[: len(mem) - 200]
    # TWO-PHASE COMMIT HARD RULE: Never auto-send on the same turn as a text edit!
    return final_draft, "edit_draft"


def patch_cards_in_chat(state: dict, card_obj: dict, chat_id: str):
    """PATCH only the cards that belong to ``chat_id`` — never cross-chat (R54 bug #1)."""
    if os.environ.get("DRY_RUN_STRESS_TEST") == "1":
        return
    payload = json.dumps({"content": json.dumps(card_obj, ensure_ascii=False)}, ensure_ascii=False)
    for mid in W.cards_in_chat(state, chat_id):
        try:
            subprocess.run(
                [LARK_CLI, "api", "PATCH", f"/open-apis/im/v1/messages/{mid}", "--as", "bot", "--data", payload],
                capture_output=True,
                text=True,
                timeout=LARK_TIMEOUT,
            )
        except Exception as e:
            log(f"patch_cards_in_chat error on {mid}: {e}")


# Backwards-compatible alias; now chat-scoped so legacy callers do not fan cross-chat.
def patch_all_cards(state: dict, card_obj: dict, chat_id: str = ""):
    patch_cards_in_chat(state, card_obj, chat_id)


def update_card_by_token(token: str, card_obj: dict):
    if not token or os.environ.get("DRY_RUN_STRESS_TEST") == "1":
        return
    payload = json.dumps({"token": token, "card": card_obj}, ensure_ascii=False)
    try:
        subprocess.run(
            [LARK_CLI, "api", "POST", "/open-apis/interactive/v1/card/update", "--as", "bot", "--data", payload],
            capture_output=True,
            text=True,
            timeout=LARK_TIMEOUT,
        )
    except Exception as e:
        log(f"update_card_by_token error: {e}")


def send_sandbox_email_to_jk(
    draft_text: str,
    open_id: str = JK_OPEN_ID,
    recipient: str = ALLOWED_TEST_RECIPIENT,
    jk_confirmed: bool = False,
) -> dict:
    """Send sandbox loopback email to allowlisted jekai@yxsurvey.com.tw ONLY when explicitly confirmed by JK."""
    target_to = enforce_test_recipient_allowlist(recipient)
    if open_id != JK_OPEN_ID or not jk_confirmed:
        log(
            f"Hard Lock #1: Blocked auto-send for actor open_id={open_id} (jk_confirmed={jk_confirmed}); "
            f"held in {PENDING_JK_FINAL_APPROVAL}."
        )
        return {
            "ok": False,
            "sent": False,
            "status": PENDING_JK_FINAL_APPROVAL,
            "allowed_test_recipient": target_to,
        }
    if os.environ.get("DRY_RUN_STRESS_TEST") == "1":
        return {
            "ok": True,
            "sent": False,
            "dry_run": True,
            "status": "SENT_FROM_JK_DRYRUN",
            "allowed_test_recipient": target_to,
        }
    name, _, html_sig = get_employee_signature(open_id)
    core = re.sub(r"\n*(?:祝\s*商祺\s*\n*)?─+\n[\s\S]*$", "", draft_text).strip()
    paragraphs = "".join(f"<p>{line}</p>" for line in core.splitlines() if line.strip())
    html_body = f"""<div style="font-family:'Microsoft JhengHei','PingFang TC',Arial,sans-serif;font-size:14px;line-height:1.7;color:#1c1a18;">
<p style="background:#eef6f0;border:1px solid #bfe3ce;padding:10px 14px;border-radius:6px;color:#1d7a45;font-size:13px;">
<strong>✅ 沙盒測試信（未外發給業主）</strong>｜{RECIPIENT_BADGE_TEXT}｜{TEST_PROTECTION_BADGE_TEXT}｜案號：<code>#C115055-1</code>｜最終放行人：{name}
</p>
{paragraphs}
<p>祝 商祺</p>
<hr style="border:0;border-top:1px solid #e3e0d9;margin:16px 0;">
{html_sig}
</div>"""
    subject = f"[沙盒核准寄出驗證 - {name}] Re: [#C115055-1] 台61線西濱水深地形測量（原收件人：台灣世曦 林工程師）"
    try:
        subprocess.run(
            [LARK_CLI, "mail", "+send", "--as", "user", "--to", target_to, "--subject", subject, "--body", html_body, "--confirm-send"],
            capture_output=True,
            text=True,
            timeout=LARK_TIMEOUT,
        )
        return {"ok": True, "sent": True, "allowed_test_recipient": target_to}
    except Exception as e:
        log(f"send_sandbox_email_to_jk error: {e}")
        return {"ok": False, "sent": False, "error": str(e), "allowed_test_recipient": target_to}


def send_bot_markdown(md_text: str, target_chat_id: str = "", target_user_id: str = "") -> str:
    if os.environ.get("DRY_RUN_STRESS_TEST") == "1":
        return "om_dryrun_md"
    tmp = Path("/tmp/bot_reply_msg.md")
    tmp.write_text(md_text)
    cmd = [LARK_CLI, "im", "+messages-send", "--as", "bot"]
    if target_chat_id:
        cmd.extend(["--chat-id", target_chat_id])
    elif target_user_id:
        cmd.extend(["--user-id", target_user_id])
    else:
        cmd.extend(["--chat-id", CHAT_ID])
    cmd.extend(["--markdown", f"@{tmp}"])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=LARK_TIMEOUT)
        return json.loads(proc.stdout).get("data", {}).get("message_id", "")
    except Exception as e:
        log(f"send_bot_markdown error: {e}")
        return ""


def send_bot_card(card_obj: dict, target_chat_id: str = "", target_user_id: str = "") -> str:
    if os.environ.get("DRY_RUN_STRESS_TEST") == "1":
        return "om_dryrun_card"
    card_json_str = json.dumps(card_obj, ensure_ascii=False)
    cmd = [LARK_CLI, "im", "+messages-send", "--as", "bot"]
    if target_chat_id:
        cmd.extend(["--chat-id", target_chat_id])
    elif target_user_id:
        cmd.extend(["--user-id", target_user_id])
    else:
        cmd.extend(["--chat-id", CHAT_ID])
    cmd.extend(["--msg-type", "interactive", "--content", card_json_str])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=LARK_TIMEOUT)
        return json.loads(proc.stdout).get("data", {}).get("message_id", "")
    except Exception as e:
        log(f"send_bot_card error: {e}")
        return ""


def resolve_target_chat(state: dict, operator_id: str = "", msg_id: str = "", explicit_chat_id: str = "") -> str:
    if explicit_chat_id:
        if explicit_chat_id not in state.setdefault("watched_chats", [CHAT_ID]):
            state["watched_chats"].append(explicit_chat_id)
        if operator_id:
            state.setdefault("user_chat_map", {})[operator_id] = explicit_chat_id
        return explicit_chat_id
    if msg_id and msg_id in state.get("card_chat_map", {}):
        return state["card_chat_map"][msg_id]
    if operator_id and operator_id in state.get("user_chat_map", {}):
        return state["user_chat_map"][operator_id]
    return ""


def handle_card_button(ev: dict):
    with STATE_LOCK:
        state = load_state()
        ev_id = ev.get("event_id") or f"{ev.get('message_id')}_{ev.get('timestamp')}"
        if ev_id in state["processed_events"]:
            return
        state["processed_events"].append(ev_id)

        raw_val = ev.get("action_value", "{}")
        try:
            val = json.loads(raw_val) if isinstance(raw_val, str) else (raw_val or {})
        except Exception:
            val = {}
        action = val.get("action", "approve_send")
        token = ev.get("token", "")
        seed = normalize_company_and_attach_sig(DEFAULT_BODY_CORE)
        operator_id = ev.get("operator_id") or JK_OPEN_ID
        operator_name, _, _ = get_employee_signature(operator_id)
        # Resolve the chat this card lives in FIRST (prefer the card's own chat).
        msg_id = ev.get("message_id") or ""
        target_chat_id = W.chat_for_card(state, msg_id) or resolve_target_chat(state, operator_id, msg_id, ev.get("chat_id", ""))
        if not msg_id:
            slot = W.ensure_chat_slot(state, target_chat_id, seed)
            msg_id = slot.get("active_card_msg_id", "")
        if msg_id:
            W.register_card(state, target_chat_id, msg_id, seed)

        cur_draft, ver, cur_status = W.get_draft(state, target_chat_id, seed)
        req_mgr, r_badge = _get_slot_risk_meta(state, target_chat_id, seed)
        draft = normalize_company_and_attach_sig(cur_draft, operator_id, operator_name)
        log(f"Card action received: action={action} msg_id={msg_id} chat={target_chat_id} operator={operator_name} ({operator_id})")

        # 1. Stale Card Version Gate (R56 Attack #7 Fix): block clicks from outdated cards
        btn_ver_raw = val.get("draft_version")
        if btn_ver_raw is not None:
            try:
                btn_ver = int(btn_ver_raw)
            except (ValueError, TypeError):
                btn_ver = int(ver)
            if btn_ver != int(ver):
                stale_note = f"⚠️ 您點擊的是舊版卡片（v{btn_ver}），目前最新草稿為 v{ver}，請在最新卡片確認後再按核准"
                log(f"Blocked stale card button click: v{btn_ver} != v{ver}")
                record_security_intercept(state, target_chat_id, operator_id, operator_name, f"[Button:{action} v{btn_ver}]", stale_note, "G09_STALE_CARD_CAS")
                card = build_interactive_card(
                    draft,
                    ver,
                    status=cur_status if cur_status in ("pending", "claimed", "handoff", "approved") else "pending",
                    note_line=stale_note,
                    actor_name=operator_name,
                    risk_badge=r_badge,
                )
                update_card_by_token(token, card)
                patch_cards_in_chat(state, card, target_chat_id)
                ack_id = send_bot_markdown(
                    f"⚠️ **您點擊的是舊版卡片（v{btn_ver}），目前最新草稿為 v{ver}，請在最新卡片確認後再按核准！**（本次點擊未寄出）",
                    target_chat_id=target_chat_id,
                    target_user_id=operator_id,
                )
                if ack_id:
                    state["processed_ids"].append(ack_id)
                save_state(state)
                return

        # 2. Global Anti-Collision Softlock Gate on Card Buttons
        if action in ("approve", "approve_send", "edit_thu", "quick_thu_noon") and W.is_locked_by_other(state, CASE_CODE, operator_id):
            holder = W.lock_holder_name(state, CASE_CODE) or "其他同仁"
            record_security_intercept(state, target_chat_id, operator_id, operator_name, f"[Button:{action}]", f"防撞攔截：本案目前由 {holder} 認領鎖定中", "G10_SOFTLOCK_COLLISION")
            card = build_interactive_card(
                draft,
                ver,
                status="collision_softlock",
                note_line=f"⚠️ 防撞攔截：{operator_name} 嘗試按鈕操作，但本案目前由 {holder} 認領鎖定中",
                actor_name=holder,
                risk_badge=r_badge,
            )
            update_card_by_token(token, card)
            patch_cards_in_chat(state, card, target_chat_id)
            ack_id = send_bot_markdown(
                f"⚠️ **防撞軟鎖提醒**：本案目前正由 **{holder}** 認領編輯中。如需接手請先輸入「強制接手」。",
                target_chat_id=target_chat_id,
                target_user_id=operator_id,
            )
            if ack_id:
                state["processed_ids"].append(ack_id)
            save_state(state)
            return

        if action in ("approve", "approve_send", "jk_final_approve"):
            # 3. Role & Authority Gate + Content Safety Gate before button send
            is_safe, safe_reason = check_outbound_content_safety(draft, draft)
            if not is_safe:
                card = build_interactive_card(
                    draft, ver, status="pending",
                    note_line=f"🛡️ 安全閘門攔截：{safe_reason}（未寄出）",
                    actor_name=operator_name, risk_badge=r_badge,
                )
                update_card_by_token(token, card)
                patch_cards_in_chat(state, card, target_chat_id)
                ack_id = send_bot_markdown(
                    f"🛡️ **對外信件安全閘門攔截（未寄出）**：{safe_reason}",
                    target_chat_id=target_chat_id, target_user_id=operator_id,
                )
                if ack_id:
                    state["processed_ids"].append(ack_id)
                save_state(state)
                return

            if req_mgr and operator_id not in AUTHORIZED_COMMERCIAL_APPROVERS:
                unauth_note = f"🛡️ 權限分級攔截：本草稿含重大商業變更（{r_badge}），須由專案主管／總經理（許喆凱）複核核准"
                record_security_intercept(state, target_chat_id, operator_id, operator_name, f"[Button:{action}]", unauth_note, "G07_RBAC_ESCALATION")
                card = build_interactive_card(
                    draft, ver, status="pending",
                    note_line=unauth_note,
                    actor_name=operator_name, risk_badge=r_badge,
                )
                update_card_by_token(token, card)
                patch_cards_in_chat(state, card, target_chat_id)
                ack_id = send_bot_markdown(
                    f"🛡️ **權限分級閘門攔截（未寄出）**\n"
                    f"• **原因**：本草稿涉及重大商業條件變更（{r_badge}），操作者（**{operator_name}**）無直接核准外發權限。\n"
                    f"• **處理方式**：請由專案主管／總經理（**許喆凱**）點擊核准，或輸入「**恢復原稿**」還原標準報價與承接內容。",
                    target_chat_id=target_chat_id,
                    target_user_id=operator_id,
                )
                if ack_id:
                    state["processed_ids"].append(ack_id)
                save_state(state)
                return

            # Hard Lock #1: Colleague button click MUST transition to PENDING_JK_FINAL_APPROVAL and NEVER auto-send
            if operator_id != JK_OPEN_ID:
                W.set_draft(state, target_chat_id, draft, ver, PENDING_JK_FINAL_APPROVAL, seed)
                slot = W.ensure_chat_slot(state, target_chat_id, seed)
                slot["jk_final_send_status"] = PENDING_JK_FINAL_APPROVAL
                slot["colleague_approved_by_open_id"] = operator_id
                slot["colleague_approved_by_name"] = operator_name
                slot["auto_send_blocked"] = True
                slot["allowed_test_recipient"] = ALLOWED_TEST_RECIPIENT
                W.release_lock(state, CASE_CODE)
                card = build_interactive_card(
                    draft,
                    ver,
                    status=PENDING_JK_FINAL_APPROVAL,
                    note_line=f"⏸️ 同仁（{operator_name}）已確認草稿，已卡住等待 JK 最終審核（狀態：{PENDING_JK_FINAL_APPROVAL}，系統嚴禁自動寄出）",
                    actor_name=operator_name,
                )
                update_card_by_token(token, card)
                patch_cards_in_chat(state, card, target_chat_id)
                ack_id = send_bot_markdown(
                    f"⏸️ **已記錄您（{operator_name}）的核准回覆！目前狀態已鎖定為 `{PENDING_JK_FINAL_APPROVAL}`（等待 JK 最終審核放行，系統嚴禁自動寄出）。**\n"
                    f"• {RECIPIENT_BADGE_TEXT}\n"
                    f"• {TEST_PROTECTION_BADGE_TEXT}",
                    target_chat_id=target_chat_id,
                    target_user_id=operator_id,
                )
            else:
                W.set_draft(state, target_chat_id, draft, ver, "approved", seed)
                slot = W.ensure_chat_slot(state, target_chat_id, seed)
                now_ts = time.time()
                slot["approved_at_ts"] = now_ts
                slot["undo_deadline_ts"] = now_ts + UNDO_GRACE_SECONDS
                slot["approved_by_open_id"] = operator_id
                slot["approved_by_name"] = operator_name
                slot["jk_final_send_status"] = "SENT_FROM_JK_DRYRUN"
                slot["allowed_test_recipient"] = ALLOWED_TEST_RECIPIENT
                _set_slot_risk_meta(state, target_chat_id, seed, False, "")
                W.release_lock(state, CASE_CODE)
                card = build_interactive_card(draft, ver, status="approved", note_line=f"✅ 已由 {operator_name} 最終審核放行並完成沙盒寄送（30 秒內可按下方按鈕或輸入「撤回」取消寄送）", actor_name=operator_name)
                update_card_by_token(token, card)
                patch_cards_in_chat(state, card, target_chat_id)
                send_sandbox_email_to_jk(draft, operator_id, ALLOWED_TEST_RECIPIENT, jk_confirmed=True)
                ack_id = send_bot_markdown(
                    f"✅ **JK 最終審核已放行！（測試保護僅寄至 `jekai@yxsurvey.com.tw`，未外發給業主）**\n"
                    f"• {RECIPIENT_BADGE_TEXT}\n"
                    f"• {TEST_PROTECTION_BADGE_TEXT}\n"
                    f"• ↩️ **30 秒撤回緩衝期**：若誤按核准，請於 **30 秒內**點擊卡片上的【↩️ 30秒內撤回寄送 (Undo)】或直接打字輸入「**撤回**」。",
                    target_chat_id=target_chat_id,
                    target_user_id=operator_id,
                )
        elif action == "undo_send":
            slot = W.ensure_chat_slot(state, target_chat_id, seed)
            deadline = float(slot.get("undo_deadline_ts") or 0)
            now_ts = time.time()
            if cur_status != "approved":
                ack_id = send_bot_markdown(
                    f"ℹ️ **目前草稿（v{ver}）尚未寄出（狀態為待確認），無需撤回，您可直接打字修改內容。**",
                    target_chat_id=target_chat_id,
                    target_user_id=operator_id,
                )
            elif deadline > 0 and now_ts > deadline:
                ack_id = send_bot_markdown(
                    f"⚠️ **已超過 {UNDO_GRACE_SECONDS} 秒撤回緩衝期，本信件（v{ver}）已完成正式歸檔，無法撤回！**",
                    target_chat_id=target_chat_id,
                    target_user_id=operator_id,
                )
            else:
                W.set_draft(state, target_chat_id, draft, ver, "pending", seed)
                slot["approved_at_ts"] = 0
                slot["undo_deadline_ts"] = 0
                ulog = state.setdefault("undo_history_log", [])
                ulog.append({
                    "case_code": CASE_CODE,
                    "chat_id": target_chat_id or "__default__",
                    "actor_open_id": operator_id,
                    "actor_name": operator_name,
                    "draft_version": ver,
                    "via": "card_button",
                    "ts": int(now_ts),
                })
                undo_note = f"↩️ 已由 {operator_name} 於 {UNDO_GRACE_SECONDS} 秒緩衝期內撤回寄送（v{ver} 已恢復為待確認狀態，可繼續修改）"
                card = build_interactive_card(draft, ver, status="pending", note_line=undo_note, actor_name=operator_name, risk_badge=r_badge)
                update_card_by_token(token, card)
                patch_cards_in_chat(state, card, target_chat_id)
                ack_id = send_bot_markdown(
                    f"↩️ **已成功撤回寄送！（草稿 v{ver} 已拉回「待確認」狀態）**\n"
                    f"• 操作人：**{operator_name}**（於 30 秒緩衝期內攔截撤回，信件未外發給業主）\n"
                    f"• 您現在可以繼續打字修改交期、報價或補充說明，確認後再按【✅ 核准並寄出】。",
                    target_chat_id=target_chat_id,
                    target_user_id=operator_id,
                )
        elif action in ("edit_thu", "quick_thu_noon"):
            draft, _ = apply_nl_edit(draft, "改週四中午前交", operator_id, state, target_chat_id)
            ver += 1
            W.set_draft(state, target_chat_id, draft, ver, "pending", seed)
            _, r_badge_after = _get_slot_risk_meta(state, target_chat_id, seed)
            card = build_interactive_card(draft, ver, status="pending", note_line=f"✏️ 已由 {operator_name} 更新為 v{ver}：交付時間改為「本週四（10/29）中午前」", actor_name=operator_name, risk_badge=r_badge_after)
            update_card_by_token(token, card)
            patch_cards_in_chat(state, card, target_chat_id)
            ack_id = send_bot_markdown(
                f"✏️ **已將卡片草稿更新為「本週四（10/29）中午前」交付（v{ver} · 附上 {operator_name} 專屬簽名檔）！**\n"
                "• 確認無誤請直接按卡片上的 **【✅ 核准並寄出】**，或繼續打字調整。",
                target_chat_id=target_chat_id,
                target_user_id=operator_id,
            )
        elif action in ("claim", "claim_lock"):
            W.set_draft(state, target_chat_id, draft, ver, "claimed", seed)
            W.acquire_lock(state, CASE_CODE, operator_id, operator_name)
            card = build_interactive_card(draft, ver, status="claimed", note_line=f"🔒 已由 {operator_name} 鎖定處理中（防重複回覆已啟動）", actor_name=operator_name, risk_badge=r_badge)
            update_card_by_token(token, card)
            patch_cards_in_chat(state, card, target_chat_id)
            ack_id = send_bot_markdown(
                f"🔒 **已為您（{operator_name}）鎖定本案（#C115055-1）！** 請直接打字告訴我要修改的內容。",
                target_chat_id=target_chat_id,
                target_user_id=operator_id,
            )
        else:
            ack_id = ""

        if ack_id:
            state["processed_ids"].append(ack_id)
        save_state(state)


def handle_user_text(content: str, msg_id: str, sender_id: str = JK_OPEN_ID, chat_id: str = ""):
    with STATE_LOCK:
        state = load_state()
        if msg_id in state["processed_ids"]:
            return
        state["processed_ids"].append(msg_id)
        need_react = msg_id not in state["reacted_ids"]
        if need_react:
            state["reacted_ids"].append(msg_id)
        target_chat_id = resolve_target_chat(state, sender_id, msg_id, chat_id)
        save_state(state)

    if need_react:
        react_to_message(msg_id, "OK")

    with STATE_LOCK:
        state = load_state()
        text = content.strip()
        if text.startswith("{"):
            try:
                j = json.loads(text)
                text = j.get("text", text).strip()
            except Exception:
                pass
        if not text:
            return

        sender_name, _, _ = get_employee_signature(sender_id)
        log(f"Handling user text from {sender_id} ({sender_name}) in {target_chat_id}: {text!r} (msg_id={msg_id})")
        seed = normalize_company_and_attach_sig(DEFAULT_BODY_CORE)
        draft, ver, _ = W.get_draft(state, target_chat_id, seed)
        base_ver = ver  # compare-and-swap baseline for every write in this handler
        new_draft, kind = apply_nl_edit(draft, text, sender_id, state, target_chat_id)
        req_mgr, r_badge = _get_slot_risk_meta(state, target_chat_id, seed)

        if kind == "internal_question":
            ack_id = send_bot_markdown(
                f"💬 **內部案況查詢回覆（未修改對外草稿 v{ver}）**\n"
                f"• **您的提問**：「{text}」\n"
                f"• **本案事實（#C115055-1 台61線西濱水深地形測量）**：業主為台灣世曦林工程師，詢問 10 月份內業圖資（`CAD-C115055-BATHY-v2.dwg`）與測量報告初稿交期（原訂本週三 10/28 17:00 前），補充測量報價基準為 **NT$150,000（未稅）**。\n"
                f"• 💡 *如需修改對外回信草稿，請明確下達修改項目（如「改週四中午前交」、「報價改 16 萬」或「加註：控制點成果一併附上」）。*",
                target_chat_id=target_chat_id,
                target_user_id=sender_id,
            )
            if ack_id:
                state["processed_ids"].append(ack_id)
        elif kind == "undo_send":
            slot = W.ensure_chat_slot(state, target_chat_id, seed)
            _, _, cur_status = W.get_draft(state, target_chat_id, seed)
            deadline = float(slot.get("undo_deadline_ts") or 0)
            now_ts = time.time()
            if cur_status != "approved":
                ack_id = send_bot_markdown(
                    f"ℹ️ **目前草稿（v{ver}）尚未寄出（狀態為待確認），無需撤回，您可直接打字修改內容。**",
                    target_chat_id=target_chat_id,
                    target_user_id=sender_id,
                )
            elif deadline > 0 and now_ts > deadline:
                ack_id = send_bot_markdown(
                    f"⚠️ **已超過 {UNDO_GRACE_SECONDS} 秒撤回緩衝期，本信件（v{ver}）已完成正式歸檔，無法撤回！**",
                    target_chat_id=target_chat_id,
                    target_user_id=sender_id,
                )
            else:
                W.set_draft_cas(state, target_chat_id, draft, ver, "pending", seed, base_ver)
                slot["approved_at_ts"] = 0
                slot["undo_deadline_ts"] = 0
                ulog = state.setdefault("undo_history_log", [])
                ulog.append({
                    "case_code": CASE_CODE,
                    "chat_id": target_chat_id or "__default__",
                    "actor_open_id": sender_id,
                    "actor_name": sender_name,
                    "draft_version": ver,
                    "via": "text_command",
                    "ts": int(now_ts),
                })
                undo_note = f"↩️ 已依 {sender_name} 的指令「{text}」於 {UNDO_GRACE_SECONDS} 秒緩衝期內撤回寄送（v{ver} 已恢復為待確認狀態）"
                card = build_interactive_card(draft, ver, status="pending", note_line=undo_note, actor_name=sender_name, risk_badge=r_badge)
                patch_cards_in_chat(state, card, target_chat_id)
                ack_id = send_bot_markdown(
                    f"↩️ **收到「{text}」！已於 {UNDO_GRACE_SECONDS} 秒緩衝期內成功撤回寄送（草稿 v{ver} 已拉回「待確認」狀態）。**\n"
                    f"• 信件未外發給業主，您現在可以繼續打字調整交期、報價或補充說明。",
                    target_chat_id=target_chat_id,
                    target_user_id=sender_id,
                )
            if ack_id:
                state["processed_ids"].append(ack_id)
        elif kind in ("rejected_unsafe", "rejected_unauthorized"):
            reason = state.pop("_last_reject_reason", "內容不符合正式商務對外信件規範或權限不足")
            gate_code = "G07_RBAC_ESCALATION" if kind == "rejected_unauthorized" else ""
            record_security_intercept(state, target_chat_id, sender_id, sender_name, text, reason, gate_code)
            gate_title = "權限分級閘門" if kind == "rejected_unauthorized" else "對外信件安全閘門"
            card = build_interactive_card(
                draft,
                ver,
                status="pending",
                note_line=f"🛡️ {gate_title}攔截：{reason}（原草稿 v{ver} 保持不變，未寄出）",
                actor_name=sender_name,
                risk_badge=r_badge,
            )
            patch_cards_in_chat(state, card, target_chat_id)
            ack_id = send_bot_markdown(
                f"🛡️ **{gate_title}已攔截本次操作（未寄出）**\n"
                f"• **攔截原因**：{reason}\n"
                f"• **保護機制**：為防止誤發、越權承諾或非商務測試內容直接寄給業主，原草稿（v{ver}）保持不變；且任何內容修改都必須**先預覽新草稿、再單獨點擊【✅ 核准並寄出】**。",
                target_chat_id=target_chat_id,
                target_user_id=sender_id,
            )
            if ack_id:
                state["processed_ids"].append(ack_id)
        elif kind == "collision_softlock":
            holder = W.lock_holder_name(state, CASE_CODE) or "其他同仁"
            record_security_intercept(state, target_chat_id, sender_id, sender_name, text, f"防撞攔截：目前由 {holder} 認領鎖定中", "G10_SOFTLOCK_COLLISION")
            card = build_interactive_card(draft, ver, status="collision_softlock", note_line=f"⚠️ 防撞攔截：{sender_name} 嘗試修改，但目前由 {holder} 認領鎖定中", actor_name=holder, risk_badge=r_badge)
            patch_cards_in_chat(state, card, target_chat_id)
            ack_id = send_bot_markdown(
                f"⚠️ **防撞軟鎖提醒**：本案目前正由 **{holder}** 認領編輯中。如需強制接手請回覆「強制接手」。",
                target_chat_id=target_chat_id,
                target_user_id=sender_id,
            )
            if ack_id:
                state["processed_ids"].append(ack_id)
        elif kind == "handoff":
            ver += 1
            target_name = W.lock_holder_name(state, CASE_CODE) or sender_name
            W.set_draft_cas(state, target_chat_id, new_draft, ver, "handoff", seed, base_ver)
            card = build_interactive_card(new_draft, ver, status="handoff", note_line=f"↪️ 已由 {sender_name} 轉交給 {target_name} 接手（v{ver}）", actor_name=target_name, risk_badge=r_badge)
            patch_cards_in_chat(state, card, target_chat_id)
            ack_id = send_bot_markdown(
                f"↪️ **已轉交給 {target_name} 處理！** 草稿下方已自動掛上 **{target_name}** 的專屬簽名檔。",
                target_chat_id=target_chat_id,
                target_user_id=sender_id,
            )
            if ack_id:
                state["processed_ids"].append(ack_id)
        elif kind == "approve":
            if sender_id != JK_OPEN_ID:
                W.set_draft_cas(state, target_chat_id, new_draft, ver, PENDING_JK_FINAL_APPROVAL, seed, base_ver)
                slot = W.ensure_chat_slot(state, target_chat_id, seed)
                slot["jk_final_send_status"] = PENDING_JK_FINAL_APPROVAL
                slot["colleague_approved_by_open_id"] = sender_id
                slot["colleague_approved_by_name"] = sender_name
                slot["auto_send_blocked"] = True
                slot["allowed_test_recipient"] = ALLOWED_TEST_RECIPIENT
                _set_slot_risk_meta(state, target_chat_id, seed, False, "")
                W.release_lock(state, CASE_CODE)
                card = build_interactive_card(
                    new_draft,
                    ver,
                    status=PENDING_JK_FINAL_APPROVAL,
                    note_line=f"⏸️ 同仁（{sender_name}）回覆「{text}」確認，已卡住等待 JK 最終審核（狀態：{PENDING_JK_FINAL_APPROVAL}，嚴禁自動寄出）",
                    actor_name=sender_name,
                )
                patch_cards_in_chat(state, card, target_chat_id)
                ack_id = send_bot_markdown(
                    f"⏸️ **收到「{text}」！已記錄 {sender_name} 的核准回覆，狀態鎖定為 `{PENDING_JK_FINAL_APPROVAL}`（等待 JK 最終審核放行，系統嚴禁自動寄出）。**\n"
                    f"• {RECIPIENT_BADGE_TEXT}\n"
                    f"• {TEST_PROTECTION_BADGE_TEXT}",
                    target_chat_id=target_chat_id,
                    target_user_id=sender_id,
                )
            else:
                W.set_draft_cas(state, target_chat_id, new_draft, ver, "approved", seed, base_ver)
                slot = W.ensure_chat_slot(state, target_chat_id, seed)
                now_ts = time.time()
                slot["approved_at_ts"] = now_ts
                slot["undo_deadline_ts"] = now_ts + UNDO_GRACE_SECONDS
                slot["approved_by_open_id"] = sender_id
                slot["approved_by_name"] = sender_name
                slot["jk_final_send_status"] = "SENT_FROM_JK_DRYRUN"
                slot["allowed_test_recipient"] = ALLOWED_TEST_RECIPIENT
                _set_slot_risk_meta(state, target_chat_id, seed, False, "")
                W.release_lock(state, CASE_CODE)
                card = build_interactive_card(new_draft, ver, status="approved", note_line=f"✅ 已依 {sender_name} 的回覆「{text}」最終放行寄出（30 秒內可按下方按鈕或輸入「撤回」取消寄送）", actor_name=sender_name)
                patch_cards_in_chat(state, card, target_chat_id)
                send_sandbox_email_to_jk(new_draft, sender_id, ALLOWED_TEST_RECIPIENT, jk_confirmed=True)
                ack_id = send_bot_markdown(
                    f"✅ **收到「{text}」！JK 最終審核已放行並寄出沙盒測試信（僅寄至 `jekai@yxsurvey.com.tw`，未外發給業主）。**\n"
                    f"• {RECIPIENT_BADGE_TEXT}\n"
                    f"• {TEST_PROTECTION_BADGE_TEXT}\n"
                    f"• ↩️ **30 秒撤回緩衝期**：若誤按核准，可於 **30 秒內**點擊卡片上的【↩️ 30秒內撤回寄送 (Undo)】或直接輸入「**撤回**」。",
                    target_chat_id=target_chat_id,
                    target_user_id=sender_id,
                )
            if ack_id:
                state["processed_ids"].append(ack_id)
        elif kind == "claim":
            W.set_draft_cas(state, target_chat_id, new_draft, ver, "claimed", seed, base_ver)
            W.acquire_lock(state, CASE_CODE, sender_id, sender_name)  # text-claim must take the global softlock too
            card = build_interactive_card(new_draft, ver, status="claimed", note_line=f"🔒 已由 {sender_name} 鎖定處理中", actor_name=sender_name, risk_badge=r_badge)
            patch_cards_in_chat(state, card, target_chat_id)
            ack_id = send_bot_markdown(
                f"🔒 **已鎖定由 {sender_name} 處理！** 請直接打字告訴我要修改的內容。",
                target_chat_id=target_chat_id,
                target_user_id=sender_id,
            )
            if ack_id:
                state["processed_ids"].append(ack_id)
        else:
            ver += 1
            W.set_draft_cas(state, target_chat_id, new_draft, ver, "pending", seed, base_ver)
            note_txt = f"✏️ 已依 {sender_name} 的指示「{text}」更新草稿（v{ver} · 含個人專屬簽名檔）"
            if r_badge:
                note_txt += f"｜⚠️ {r_badge}"
            card = build_interactive_card(new_draft, ver, status="pending", note_line=note_txt, actor_name=sender_name, risk_badge=r_badge)
            patch_cards_in_chat(state, card, target_chat_id)
            new_cid = send_bot_card(card, target_chat_id=target_chat_id, target_user_id=sender_id)
            if new_cid:
                W.register_card(state, target_chat_id, new_cid, seed)
                state["processed_ids"].append(new_cid)
        save_state(state)


def parse_ndjson_stream(stream, callback):
    """Parse multi-line pretty JSON objects emitted by `lark-cli event consume` on stdout."""
    buf = []
    depth = 0
    in_str = False
    escape = False
    while True:
        ch = stream.read(1)
        if not ch:
            break
        if depth == 0:
            if ch == "{":
                buf = ["{"]
                depth = 1
                in_str = False
                escape = False
            continue
        buf.append(ch)
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    raw = "".join(buf)
                    buf = []
                    try:
                        obj = json.loads(raw)
                        callback(obj)
                    except Exception as e:
                        log(f"JSON parse error: {e}")


# R55: exponential reconnect backoff so a hard-failing `lark-cli event consume`
# (bad binary, revoked creds, Lark outage) can never spin in a tight 1s crash
# loop. Backoff grows 1→2→4…→MAX; a connection that stayed up past
# WS_HEALTHY_SECS is treated as healthy and resets the backoff to the floor.
WS_BACKOFF_MIN = 1.0
WS_BACKOFF_MAX = 30.0
WS_HEALTHY_SECS = 30.0


def _consume_with_backoff(event_name: str, callback, loop_name: str, _max_iters: int | None = None):
    backoff = WS_BACKOFF_MIN
    iters = 0
    while _max_iters is None or iters < _max_iters:
        iters += 1
        started = time.monotonic()
        try:
            log(f"Starting {event_name} consumer...")
            proc = subprocess.Popen(
                [LARK_CLI, "event", "consume", event_name, "--as", "bot"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            parse_ndjson_stream(proc.stdout, callback)
            proc.wait()
        except Exception as e:
            log(f"{loop_name} error: {e}")
        uptime = time.monotonic() - started
        if uptime >= WS_HEALTHY_SECS:
            backoff = WS_BACKOFF_MIN  # a long-lived connection: reset backoff
        log(f"{loop_name} disconnected after {uptime:.1f}s; reconnecting in {backoff:.1f}s")
        time.sleep(backoff)
        backoff = min(backoff * 2.0, WS_BACKOFF_MAX)


def card_ws_consumer_loop(_max_iters: int | None = None):
    _consume_with_backoff("card.action.trigger", handle_card_button, "card_ws_consumer_loop", _max_iters)


def _on_msg_event(ev: dict):
    mid = ev.get("message_id") or ev.get("id")
    sender_type = ev.get("sender_type")
    sender_id = ev.get("sender_id") or JK_OPEN_ID
    chat_id = ev.get("chat_id") or ""
    content = (ev.get("content") or "").strip()
    if mid and sender_type == "user" and content:
        handle_user_text(content, mid, sender_id, chat_id)


def msg_ws_consumer_loop(_max_iters: int | None = None):
    _consume_with_backoff("im.message.receive_v1", _on_msg_event, "msg_ws_consumer_loop", _max_iters)


def poll_chat_loop():
    while True:
        try:
            with STATE_LOCK:
                chats = list(dict.fromkeys(load_state().get("watched_chats", [CHAT_ID])))
            for cid in chats:
                if not cid:
                    continue
                proc = subprocess.run(
                    [
                        LARK_CLI,
                        "api",
                        "GET",
                        "/open-apis/im/v1/messages",
                        "--params",
                        json.dumps({"container_id_type": "chat", "container_id": cid, "page_size": 5, "sort_type": "ByCreateTimeDesc"}),
                        "--as",
                        "bot",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    items = data.get("data", {}).get("items", [])
                    for m in reversed(items):
                        if m.get("deleted"):
                            continue
                        mid = m.get("message_id")
                        sender_type = m.get("sender", {}).get("sender_type")
                        sender_id = m.get("sender", {}).get("id") or JK_OPEN_ID
                        raw_body = m.get("body", {}).get("content", "")
                        if mid and sender_type == "user" and raw_body:
                            handle_user_text(raw_body, mid, sender_id, cid)
        except Exception as e:
            log(f"poll error: {e}")
        time.sleep(1.5)


def main():
    with STATE_LOCK:
        st = load_state()
        for done_id in (
            "om_x100b62ee2533d8a0ed572e9d10a2286",
            "om_x100b62ee23a3f4a0fe22829f25972d5",
            "om_x100b62eefd71d8a0eedb15a981f55fb",
            "om_x100b62eef0c5f4a0ffd7d56025a5289",
            "om_x100b62ee85f1f4a0ed5272872779fed",
        ):
            if done_id not in st["processed_ids"]:
                st["processed_ids"].append(done_id)
        if not st.get("current_draft"):
            st["current_draft"] = normalize_company_and_attach_sig(DEFAULT_BODY_CORE, YUKUAN_OPEN_ID, "林育寬")
        save_state(st)

    log("live_jk_test_watcher started (multi-chat enabled)!")
    t1 = threading.Thread(target=card_ws_consumer_loop, daemon=True)
    t1.start()
    t2 = threading.Thread(target=msg_ws_consumer_loop, daemon=True)
    t2.start()
    poll_chat_loop()


if __name__ == "__main__":
    main()
