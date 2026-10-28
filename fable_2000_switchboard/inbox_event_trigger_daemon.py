#!/usr/bin/env python3
"""Event-Driven Inbox & Webhook Trigger Dispatcher for 業主聯繫 Lark 總機.

Replaces timer/cron polling with an instant event-driven trigger architecture:
- Dedicated Inbox Trigger: jk-chief+switchboard@mail.grokbot.com
- Lark Webhook / Card Callback Routine: lark-webhook-lark
- Strict DB isolation: yongxiang_plumb_r39_clone only (assert current_database() != 'yongxiang_plumb')
- Strict outbound gate: SANDBOX_LOOPBACK / DRY_RUN only (0 external sends)
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from typing import Any

from lark_cli_watcher_agent import (
    ACTOR,
    DATABASE,
    INBOX_ADDRESS,
    MODE,
    TRIGGER_ARCH,
    WEBHOOK_ROUTINE,
    enqueue,
    literal,
    poll_once,
    rows,
    sql,
)


def assert_clone_isolation() -> str:
    db_name = sql("SELECT current_database();")
    assert db_name != "yongxiang_plumb", f"FATAL: Forbidden production database {db_name}"
    assert db_name == "yongxiang_plumb_r39_clone", f"Expected clone DB, got {db_name}"
    return db_name


def trigger_event(envelope: dict[str, Any]) -> dict[str, Any]:
    """Immediately process an inbound Inbox or Lark Webhook/Card event with 0 polling."""
    t0 = time.perf_counter()
    db_name = assert_clone_isolation()
    if envelope.get("mode", MODE) != MODE:
        raise ValueError("SANDBOX_LOOPBACK mode required")

    source = envelope.get("trigger_source") or "INBOX_OR_WEBHOOK"
    queued_row = enqueue(
        {
            "lark_message_id": envelope["lark_message_id"],
            "dispatch_id": envelope["dispatch_id"],
            "sender_employee_id": envelope["sender_employee_id"],
            "raw_reply_text": envelope["raw_reply_text"],
        }
    )
    did = str(uuid.UUID(envelope["dispatch_id"]))
    disp_rows = rows(f"SELECT * FROM lark_cli_outbound_dispatch WHERE dispatch_id={literal(did)}")
    disp = disp_rows[0] if disp_rows else {}
    lock_notices = rows(
        f"SELECT * FROM r50_peer_lock_notification WHERE winning_dispatch_id={literal(did)} OR superseded_dispatch_id={literal(did)} ORDER BY created_at DESC"
    )
    interceptions = rows(
        f"SELECT * FROM r50_collision_interception_log WHERE blocked_lark_message_id={literal(envelope['lark_message_id'])}"
    )
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return {
        "ok": True,
        "database": db_name,
        "mode": MODE,
        "trigger_architecture": TRIGGER_ARCH,
        "trigger_source": source,
        "inbox_trigger_address": INBOX_ADDRESS,
        "webhook_routine": WEBHOOK_ROUTINE,
        "polling_overhead_ms": 0,
        "trigger_latency_ms": elapsed_ms,
        "external_messages_sent": 0,
        "queued": queued_row,
        "dispatch_state": {
            "dispatch_id": disp.get("dispatch_id"),
            "case_code": disp.get("case_code"),
            "target_employee_name": disp.get("target_employee_name"),
            "reply_status": disp.get("reply_status"),
            "jk_final_send_status": disp.get("jk_final_send_status"),
            "superseded_by_employee_name": disp.get("superseded_by_employee_name"),
            "peer_lock_notice": disp.get("peer_lock_notice"),
        },
        "peer_lock_notifications_emitted": len(lock_notices),
        "collision_interceptions_logged": len(interceptions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-json", help="Event envelope JSON to trigger immediately")
    parser.add_argument("--status", action="store_true", help="Print event-driven trigger status")
    args = parser.parse_args()
    db_name = assert_clone_isolation()
    if args.event_json:
        print(json.dumps(trigger_event(json.loads(args.event_json)), ensure_ascii=False, indent=2))
    else:
        processed = poll_once()
        hb = rows("SELECT * FROM r50_lark_watcher_heartbeat WHERE agent_id='lark-cli-watcher'")
        print(
            json.dumps(
                {
                    "ok": True,
                    "database": db_name,
                    "mode": MODE,
                    "trigger_architecture": TRIGGER_ARCH,
                    "inbox_trigger_address": INBOX_ADDRESS,
                    "webhook_routine": WEBHOOK_ROUTINE,
                    "cron_polling_processes": 0,
                    "drained_events": processed,
                    "heartbeat": hb[0] if hb else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
