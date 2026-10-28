#!/usr/bin/env python3
"""R54 two-stage SLA sentinel / radar runner (clone-only, read-report, no sends).

This module ONLY computes and reports. It never sends Lark messages or emails —
the twice-daily 09:00/16:30 radar is wired by cron to call ``sweep()`` and hand
the result to whatever human-facing surface is approved; raising an alert is a
separate, explicitly-authorised step.

All DB access goes through db.py, which hard-asserts the target is
yongxiang_plumb_r39_clone and refuses the production yongxiang_plumb.
"""
from __future__ import annotations

import argparse
import json

import db


def _q(sql: str):
    return db.query(sql)


def enroll(case_code: str, case_id: str | None = None, received_at: str | None = None) -> None:
    cid = db.literal(case_id) + "::uuid" if case_id else "NULL"
    rec = db.literal(received_at) + "::timestamptz" if received_at else "NULL"
    db.execute(f"SELECT public.r54_enroll_case({db.literal(case_code)}, {cid}, {rec});")


def transition(case_code: str, action: str, actor_id: str | None = None,
               at: str | None = None, snooze_until: str | None = None, note: str | None = None) -> str:
    actor = db.literal(actor_id) + "::uuid" if actor_id else "NULL"
    at_sql = db.literal(at) + "::timestamptz" if at else "NULL"
    sn = db.literal(snooze_until) + "::timestamptz" if snooze_until else "NULL"
    note_sql = db.literal(note) if note else "NULL"
    # db.query json-decodes each output line; to_jsonb(text) -> a bare JSON string.
    rows = _q(
        f"SELECT to_jsonb(public.r54_apply_transition("
        f"{db.literal(case_code)}, {db.literal(action)}, {actor}, {at_sql}, {sn}, {note_sql}));"
    )
    return rows[0] if rows else ""


def radar(as_of: str | None = None) -> list[dict]:
    # to_jsonb(row) -> a JSON object, so each element is already a dict keyed by column.
    as_of_sql = db.literal(as_of) + "::timestamptz" if as_of else "clock_timestamp()"
    return _q(
        "SELECT to_jsonb(r) FROM public.r54_sla_radar(" + as_of_sql + ") r;"
    )


def sweep(as_of: str | None = None) -> list[dict]:
    as_of_sql = db.literal(as_of) + "::timestamptz" if as_of else "clock_timestamp()"
    return _q(
        "SELECT to_jsonb(r) FROM public.r54_radar_sweep(" + as_of_sql + ") r;"
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description="R54 SLA radar (clone-only, report-only)")
    ap.add_argument("cmd", choices=["radar", "sweep"], nargs="?", default="sweep")
    ap.add_argument("--as-of", default=None, help="evaluate at this timestamptz (default: now)")
    args = ap.parse_args(argv)
    db.assert_not_prod_db()
    rows = radar(args.as_of) if args.cmd == "radar" else sweep(args.as_of)
    print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    esc = sum(1 for r in rows if r.get("sla_status") == "ESCALATE")
    warn = sum(1 for r in rows if r.get("sla_status") == "WARN")
    print(f"\n[R54 radar @ {args.as_of or 'now'}] WARN={warn} ESCALATE={esc} total={len(rows)}")
    return rows


if __name__ == "__main__":
    main()
