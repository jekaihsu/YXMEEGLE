#!/usr/bin/env python3
"""R53 two-stage SLA state machine — thin Python driver over sql/011_r53_two_stage_sla.sql.

All time is INJECTED via explicit ``now`` arguments; nothing here reads the wall
clock, so behaviour is fully deterministic and unit-testable. No Email/Lark is
ever sent: escalations only enqueue mock rows into public.notification_outbox.

Connects ONLY to the test clone yongxiang_plumb_r39_clone (guarded below).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

CLONE_DB = "yongxiang_plumb_r39_clone"
PROD_DB = "yongxiang_plumb"

# 7 states of the model.
UNCLAIMED = "UNCLAIMED"
CLAIMED = "CLAIMED"
WAITING_UPSTREAM_DATA = "WAITING_UPSTREAM_DATA"
SENT = "SENT"
ESCALATED_L1 = "ESCALATED_L1"
ESCALATED_L2 = "ESCALATED_L2"
RESOLVED = "RESOLVED"
STATES = (UNCLAIMED, CLAIMED, WAITING_UPSTREAM_DATA, SENT,
          ESCALATED_L1, ESCALATED_L2, RESOLVED)

TAIPEI = timezone(timedelta(hours=8))


def connect(dbname: str = CLONE_DB):
    if dbname != CLONE_DB:
        raise ValueError(f"R53 engine only connects to {CLONE_DB}, refused {dbname!r}")
    conn = psycopg2.connect(dbname=dbname, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()
    cur.execute("SELECT current_database()")
    got = cur.fetchone()["current_database"]
    if got == PROD_DB or got != CLONE_DB:
        conn.close()
        raise RuntimeError(f"FATAL: refused non-clone DB {got!r}")
    return conn


# --------------------------------------------------------------------------- #
# Transitions. Every call takes an explicit ``now`` datetime.
# --------------------------------------------------------------------------- #
def create_tracker(conn, org_id: str, case_id: str, now: datetime) -> dict:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO public.r53_sla_tracker(org_id, case_id, status, arrived_at,
             clock_started_at, created_at, updated_at)
           VALUES (%s,%s,'UNCLAIMED',%s,%s,%s,%s) RETURNING *""",
        (org_id, case_id, now, now, now, now))
    return cur.fetchone()


def _call(conn, fn: str, tracker_id: str, now: datetime, *extra) -> dict:
    cur = conn.cursor()
    placeholders = ",".join(["%s"] * (1 + len(extra) + 1))
    cur.execute(f"SELECT * FROM public.{fn}({placeholders})",
                (tracker_id, *extra, now))
    return cur.fetchone()


def claim(conn, tracker_id, assignee_id, now):
    cur = conn.cursor()
    cur.execute("SELECT * FROM public.r53_claim(%s,%s,%s)", (tracker_id, assignee_id, now))
    return cur.fetchone()


def snooze(conn, tracker_id, now):
    return _call(conn, "r53_snooze", tracker_id, now)


def resume(conn, tracker_id, now):
    return _call(conn, "r53_resume", tracker_id, now)


def mark_sent(conn, tracker_id, now):
    return _call(conn, "r53_mark_sent", tracker_id, now)


def resolve(conn, tracker_id, now):
    return _call(conn, "r53_resolve", tracker_id, now)


def run_escalations(conn, now) -> int:
    cur = conn.cursor()
    cur.execute("SELECT public.r53_run_escalations(%s) AS n", (now,))
    return cur.fetchone()["n"]


def is_sweep_time(conn, now) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT public.r53_is_sweep_time(%s) AS b", (now,))
    return cur.fetchone()["b"]


def radar_sweep(conn, now) -> list[dict]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM public.r53_radar_sweep(%s)", (now,))
    return cur.fetchall()


def get(conn, tracker_id) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT * FROM public.r53_sla_tracker WHERE id=%s", (tracker_id,))
    return cur.fetchone()


def live_age_seconds(conn, tracker_id, now) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT public.r53_live_age_seconds(t,%s) AS s FROM public.r53_sla_tracker t WHERE id=%s",
        (now, tracker_id))
    return cur.fetchone()["s"]
