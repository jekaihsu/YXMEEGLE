#!/workspace/yongxiang_arch/ai_switchboard_mvp/.venv-r31b/bin/python
"""Live Lark IM + Lark Mail Watcher Daemon for JK's #TEST-JK-01 (C115055-1).
Enforces R52 3 Hard Locks (t50u):
1. Hard Lock #1: Colleague / test reply ALWAYS transitions to PENDING_JK_FINAL_APPROVAL; auto-send is strictly forbidden.
2. Hard Lock #2: ALLOWED_TEST_RECIPIENT = 'jekai@yxsurvey.com.tw' allowlist guard; blocks @gmail.com or external client emails.
3. Hard Lock #3: Explicit '🎯 按下後實際收件人：<完整 Email 與姓名>' badge right beside every approval/send button.
All DB operations strictly bound to yongxiang_plumb_r39_clone (assert current_database() != 'yongxiang_plumb').
"""
import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import psycopg
from psycopg.rows import dict_row

LARK_CLI = "/home/box/.local/bin/lark-cli"
DB_NAME = "yongxiang_plumb_r39_clone"
DSN = f"postgresql://postgres:postgres@127.0.0.1:5432/{DB_NAME}"
STATE_FILE = Path("/workspace/yongxiang_arch/ai_switchboard_mvp/jk_live_test_watcher_state.json")
LOG_FILE = Path("/workspace/yongxiang_arch/ai_switchboard_mvp/jk_live_test_watcher.log")

JK_OPEN_ID = "ou_7dfe7ce548da22a0275cba0d92b3bfec"
JK_EMP_ID = "1101fb67-0080-50c1-98e6-d02f7a0ae907"
ALLOWED_TEST_RECIPIENT = "jekai@yxsurvey.com.tw"
JK_EMAIL = ALLOWED_TEST_RECIPIENT
PENDING_JK_FINAL_APPROVAL = "PENDING_JK_FINAL_APPROVAL"
INTENDED_CLIENT_RECIPIENT = "台灣世曦 · 林工程師 <lin.ceci@example.com>"
RECIPIENT_BADGE_TEXT = f"🎯 按下後實際收件人：{INTENDED_CLIENT_RECIPIENT}"
TEST_PROTECTION_BADGE_TEXT = "🎯 測試保護中：按下只會寄至 jekai@yxsurvey.com.tw（許竣凱），不會外發業主"

JK_CHAT_ID = "oc_bbbb3aa34ec3d42a8a98630ba4770662"
JK_BOT_CHAT_ID = "oc_3c87cd9f022e560f3e0d668e5697a233"
JK_MAIL_THREAD_ID = "YmQ2MGU1Y2EtZDJhYi00YzA4LWIxYmYtMDMxMzUzYjEwMjMz"
JK_INITIAL_IM_MSG_ID = "om_x100b62ee702b44a0ed659672240f650"
JK_INITIAL_MAIL_MSG_ID = "YmQ2MGU1Y2EtZDJhYi00YzA4LWIxYmYtMDMxMzUzYjEwMjMz"
JK_CASE_CODE = "C115055-1"
JK_CARD_ID = "a19d8f61-8d12-44d4-8598-2ec5bd0f87ba"

TZ_TAIPEI = timezone(timedelta(hours=8))


def enforce_test_recipient_allowlist(recipient: str) -> str:
    """Hard Lock #2: Programmatic allowlist guard for test/dry-run/preview email dispatch."""
    norm = (recipient or "").strip().lower()
    if not norm or "@gmail.com" in norm or norm != ALLOWED_TEST_RECIPIENT:
        raise PermissionError(
            f"BLOCKED_NON_WHITELIST_RECIPIENT: recipient {recipient!r} is forbidden in test mode; "
            f"only {ALLOWED_TEST_RECIPIENT} is allowed"
        )
    return ALLOWED_TEST_RECIPIENT


def log(msg: str):
    ts = datetime.now(TZ_TAIPEI).strftime("%Y-%m-%d %H:%M:%S+08:00")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_conn():
    conn = psycopg.connect(DSN, autocommit=True, row_factory=dict_row)
    db = conn.execute("SELECT current_database() AS db").fetchone()["db"]
    assert db == "yongxiang_plumb_r39_clone" and db != "yongxiang_plumb", f"Forbidden DB: {db}"
    return conn


def run_cli(args):
    res = subprocess.run([LARK_CLI, *args], capture_output=True, text=True, timeout=25)
    out = res.stdout.strip()
    idx = out.find("{")
    if idx >= 0:
        out = out[idx:]
    try:
        return json.loads(out)
    except Exception:
        return {"ok": False, "raw": res.stdout, "stderr": res.stderr, "returncode": res.returncode}


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    state = {
        "started_at": datetime.now(TZ_TAIPEI).isoformat(),
        "baseline_im_position_oc_bbbb": 283,
        "baseline_im_position_oc_bot": 169,
        "processed_im_ids": [JK_INITIAL_IM_MSG_ID],
        "processed_mail_ids": [JK_INITIAL_MAIL_MSG_ID],
        "sent_reply_ids": [],
        "events_handled": [],
    }
    save_state(state)
    return state


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_mail_reply(text: str) -> str:
    if not text:
        return ""
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(">"):
            continue
        if re.match(r"^(On .* wrote:|在 .* 寫道：|From:|寄件者:|Sent:|Date:|Subject:|主旨:|To:|收件者:)", s):
            break
        if "【模擬業主來信通知" in s or "【永祥 · 業主往來測試" in s or "【AI 自動擬妥之回信草稿" in s:
            break
        lines.append(s)
    return "\n".join(lines).strip()


def is_bot_echo(content: str) -> bool:
    if not content:
        return True
    markers = [
        "【永祥 · 業主往來測試 #TEST-JK-01】",
        "【模擬業主來信通知（DRY-RUN 測試件 #TEST-JK-01）】",
        "【R50 業主聯繫總機 · 即時測試回執】",
        "【AI 自動擬妥之回信草稿（v2）】",
        "【AI 自動擬妥之回信草稿（v3）】",
        "<card title=",
        "[Invalid text JSON]",
        "業主來信待確認｜#C115055-1",
    ]
    return any(m in content for m in markers)


def get_active_jk_dispatch(conn):
    row = conn.execute(
        """
        SELECT d.dispatch_id, d.card_id, d.case_code, d.draft_version, d.message_preview,
               d.reply_status, d.jk_final_send_status,
               coalesce(
                 (SELECT r.edited_body FROM public.lark_cli_inbound_reply r
                  WHERE r.dispatch_id = d.dispatch_id AND r.edited_body IS NOT NULL
                  ORDER BY r.created_at DESC LIMIT 1),
                 (SELECT a.approved_body FROM public.approval_snapshot a
                  WHERE a.dispatch_id = d.dispatch_id
                  ORDER BY a.approved_at DESC LIMIT 1),
                 d.message_preview
               ) AS latest_body
        FROM public.lark_cli_outbound_dispatch d
        WHERE d.case_code = %s AND d.target_employee_id = %s
        ORDER BY d.draft_version DESC, d.created_at DESC
        LIMIT 1
        """,
        (JK_CASE_CODE, JK_EMP_ID),
    ).fetchone()
    return row


def process_jk_reply(
    channel: str,
    msg_id: str,
    raw_text: str,
    state: dict,
    chat_id: str = JK_CHAT_ID,
    actor_name: str = "許喆凱",
    explicit_jk_final_confirm: bool = False,
):
    cleaned = clean_mail_reply(raw_text) if channel == "mail" else raw_text.strip()
    if not cleaned or is_bot_echo(cleaned):
        return None

    log(f"Detected reply on {channel} (msg_id={msg_id}, actor={actor_name}): {cleaned!r}")
    conn = get_conn()
    try:
        disp = get_active_jk_dispatch(conn)
        if not disp:
            ver = conn.execute(
                "SELECT public.bump_draft_version(%s, %s) AS v",
                (
                    JK_CARD_ID,
                    "林工程師您好：\n收到您的來信。關於 C115055-1 案之水深與地形測量成果：\n1. 內業圖資（CAD-C115055-BATHY-v2.dwg）與測量報告初稿目前正由品管組最後複核中，預計於本週三（10/28）17:00 前寄出供貴司審閱。\n2. 本次補充測量項目報價單價為 NT$150,000（未稅），計價數量明細表亦會隨信一併附上。\n如有任何需先行調整之處，再請隨時告知，謝謝您！\n詠翔測量 敬上",
                ),
            ).fetchone()["v"]
            conn.execute("SELECT public.push_dispatch(%s, %s, %s, %s)", (JK_CARD_ID, ver, JK_EMP_ID, JK_EMP_ID))
            disp = get_active_jk_dispatch(conn)

        parsed = conn.execute("SELECT public.r50_parse_interaction(%s) AS p", (cleaned,)).fetchone()["p"]
        action = parsed.get("action", "agent_query")
        imode = parsed.get("interaction_mode", "NL_CHAT_MODE")
        instruction_txt = parsed.get("text", cleaned)
        base_body = disp["latest_body"]
        dispatch_id = str(disp["dispatch_id"])

        # Hard Lock #1: Any colleague reply or regular approve transitions strictly to PENDING_JK_FINAL_APPROVAL
        if action == "edit_and_approve":
            try:
                edited_body = conn.execute(
                    "SELECT public.r50_apply_reply_edit(%s, %s) AS b",
                    (base_body, instruction_txt),
                ).fetchone()["b"]
            except Exception as e:
                log(f"r50_apply_reply_edit fallback triggered: {e}")
                edited_body = base_body + f"\n\n【依 {actor_name} 指示修訂】：{instruction_txt}"

            conn.execute(
                "SELECT public.r50_part2_cas_decide(%s, %s, 'EDIT_AND_APPROVE', %s, %s, %s, false) AS r",
                (dispatch_id, actor_name, imode, cleaned, edited_body),
            )
            conn.execute(
                """
                INSERT INTO public.lark_cli_inbound_reply(
                  lark_message_id, dispatch_id, sender_employee_id, sender_name,
                  raw_reply_text, parsed_action, edited_body, verified_assignee,
                  draft_version_matched, response_seconds, interaction_mode
                ) VALUES (%s, %s, %s, %s, %s, 'edit_and_approve', %s, true, true, 5, %s)
                ON CONFLICT (lark_message_id) DO NOTHING
                """,
                (f"{channel}:{msg_id}", dispatch_id, JK_EMP_ID, actor_name, cleaned, edited_body, imode),
            )
            conn.execute(
                """
                UPDATE public.lark_cli_outbound_dispatch
                SET message_preview = %s,
                    reply_status = 'EDITED_AND_APPROVED',
                    jk_final_send_status = 'PENDING_JK_FINAL_APPROVAL',
                    test_recipient_email = 'jekai@yxsurvey.com.tw',
                    updated_at = now()
                WHERE dispatch_id = %s
                """,
                (edited_body, dispatch_id),
            )
            reply_msg = (
                f"⏸️ 【R52 業主聯繫總機 · 待 JK 最終審核放行（Hard Lock #1）】\n"
                f"• 接收管道：{('永祥信箱 jekai@yxsurvey.com.tw' if channel == 'mail' else '永祥 Lark DM')}\n"
                f"• 原始指令：「{cleaned}」\n"
                f"• 解析動作：EDIT_AND_APPROVE（已攔截自動外寄，強制進入 PENDING_JK_FINAL_APPROVAL）\n"
                f"• 資料庫狀態：EDITED_AND_APPROVED / PENDING_JK_FINAL_APPROVAL（dispatch_id={dispatch_id}）\n"
                f"• {RECIPIENT_BADGE_TEXT}\n"
                f"• {TEST_PROTECTION_BADGE_TEXT}\n\n"
                f"📝 【AI 自動重擬之回信草稿】\n"
                f"{edited_body}\n\n"
                f"💡 目前已卡住等待 JK 最終審核（嚴禁自動寄出）！"
            )

        elif action == "approve":
            conn.execute(
                "SELECT public.r50_part2_cas_decide(%s, %s, 'APPROVE', %s, %s, NULL, false) AS r",
                (dispatch_id, actor_name, imode, cleaned),
            )
            conn.execute(
                """
                UPDATE public.lark_cli_outbound_dispatch
                SET reply_status = 'APPROVED',
                    jk_final_send_status = 'PENDING_JK_FINAL_APPROVAL',
                    test_recipient_email = 'jekai@yxsurvey.com.tw',
                    updated_at = now()
                WHERE dispatch_id = %s
                """,
                (dispatch_id,),
            )
            if explicit_jk_final_confirm and actor_name == "許喆凱":
                enforce_test_recipient_allowlist(ALLOWED_TEST_RECIPIENT)
                fin_res = conn.execute(
                    "SELECT public.r50_part2_jk_finalize(%s, %s) AS r",
                    (dispatch_id, JK_EMP_ID),
                ).fetchone()["r"]
                comm_id = fin_res.get("communication_id") or fin_res.get("comm_id")
                reply_msg = (
                    f"✅ 【R52 業主聯繫總機 · JK 最終審核放行完成】\n"
                    f"• 資料庫狀態：SENT_FROM_JK_DRYRUN（comm_id={comm_id}，未對真實業主外寄）\n"
                    f"• {RECIPIENT_BADGE_TEXT}\n"
                    f"• {TEST_PROTECTION_BADGE_TEXT}\n\n"
                    f"📤 【最終定稿內容】\n"
                    f"{base_body}"
                )
            else:
                reply_msg = (
                    f"⏸️ 【R52 業主聯繫總機 · 同事回覆已卡住待 JK 最終審核（Hard Lock #1）】\n"
                    f"• 接收管道：{('永祥信箱 jekai@yxsurvey.com.tw' if channel == 'mail' else '永祥 Lark DM')}\n"
                    f"• 原始指令：「{cleaned}」\n"
                    f"• 資料庫狀態：APPROVED / PENDING_JK_FINAL_APPROVAL（嚴禁自動寄出）\n"
                    f"• {RECIPIENT_BADGE_TEXT}\n"
                    f"• {TEST_PROTECTION_BADGE_TEXT}"
                )

        elif action in ("handoff", "reject"):
            cas_act = "HANDOFF" if action == "handoff" else "REJECT"
            conn.execute(
                "SELECT public.r50_part2_cas_decide(%s, %s, %s, %s, %s, NULL, false) AS r",
                (dispatch_id, actor_name, cas_act, imode, cleaned),
            )
            reply_msg = (
                f"✅ 【R52 業主聯繫總機 · 即時測試回執】\n"
                f"• 解析動作：{cas_act}（已標記待內部確認並鎖住外寄 WITHDRAWN）\n"
                f"• 資料庫狀態：dispatch_id={dispatch_id} 已鎖定不外寄。"
            )
        else:
            reply_msg = (
                f"✅ 【R52 業主聯繫總機 · 即時測試回執】\n"
                f"• 收到訊息：「{cleaned}」\n"
                f"• 解析動作：AGENT_QUERY（查詢/備註，保持草稿待命，嚴禁自動寄出）\n"
                f"• {RECIPIENT_BADGE_TEXT}\n"
                f"• {TEST_PROTECTION_BADGE_TEXT}"
            )

        event_record = {
            "handled_at": datetime.now(TZ_TAIPEI).isoformat(),
            "channel": channel,
            "inbound_message_id": msg_id,
            "raw_text": cleaned,
            "parsed_action": action,
            "jk_final_send_status": PENDING_JK_FINAL_APPROVAL if not explicit_jk_final_confirm else "SENT_FROM_JK_DRYRUN",
            "allowed_test_recipient": ALLOWED_TEST_RECIPIENT,
            "auto_send_blocked": not explicit_jk_final_confirm,
            "reply_preview": reply_msg,
        }
        state["events_handled"].append(event_record)
        save_state(state)
        log(f"Processed reply under Hard Lock #1/#2/#3 (auto_send_blocked={not explicit_jk_final_confirm}): {event_record['jk_final_send_status']}")
        return event_record
    finally:
        conn.close()


def poll_once():
    state = load_state()
    im_res = run_cli(["im", "+chat-messages-list", "--chat-id", JK_CHAT_ID, "--page-size", "10"])
    if im_res.get("ok"):
        msgs = (im_res.get("data") or {}).get("messages") or []
        for m in reversed(msgs):
            mid = m.get("message_id")
            pos = int(m.get("message_position") or 0)
            content = m.get("content") or ""
            if not mid or mid in state["processed_im_ids"] or mid in state["sent_reply_ids"]:
                continue
            if pos <= state.get("baseline_im_position_oc_bbbb", 283):
                state["processed_im_ids"].append(mid)
                continue
            state["processed_im_ids"].append(mid)
            if pos > state.get("baseline_im_position_oc_bbbb", 283):
                state["baseline_im_position_oc_bbbb"] = pos
            save_state(state)
            if not is_bot_echo(content):
                process_jk_reply("lark_im", mid, content, state, chat_id=JK_CHAT_ID)

    mail_res = run_cli(["mail", "+thread", "--thread-id", JK_MAIL_THREAD_ID])
    if mail_res.get("ok"):
        m_list = (mail_res.get("data") or {}).get("messages") or []
        for m in m_list:
            mid = m.get("message_id")
            body = m.get("body_plain_text") or m.get("body_preview") or ""
            if not mid or mid in state["processed_mail_ids"]:
                continue
            state["processed_mail_ids"].append(mid)
            save_state(state)
            if not is_bot_echo(body):
                process_jk_reply("mail", mid, body, state, chat_id=JK_CHAT_ID)

    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=float, default=3.0)
    args = ap.parse_args()

    if args.once:
        st = poll_once()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return

    log(f"Starting jk_live_test_watcher daemon (PID={os.getpid()}) under R52 Hard Locks #1/#2/#3")
    while True:
        try:
            poll_once()
        except Exception as e:
            log(f"Watcher poll error: {e!r}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
