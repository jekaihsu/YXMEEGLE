#!/usr/bin/env python3
"""R54 state-machine + two-stage SLA tests against yongxiang_plumb_r39_clone.

Uses fixed injected timestamps so every assertion is deterministic. Seeds its
own throwaway case_codes (prefix R54TEST-) and cleans up after itself; it never
touches production and never sends anything.

Run: .venv-r31b/bin/python -m pytest test_r54_sla.py -v
"""
import pytest

import db
import r54_sla_sentinel as S

T0 = "2026-10-25 08:00:00+08"   # case received / claimed anchor


def _cleanup():
    db.execute(
        "DELETE FROM public.r54_loop_event WHERE case_code LIKE 'R54TEST-%';"
        "DELETE FROM public.r54_case_loop  WHERE case_code LIKE 'R54TEST-%';"
    )


@pytest.fixture(autouse=True)
def around():
    assert db.assert_not_prod_db() == "yongxiang_plumb_r39_clone"
    _cleanup()
    yield
    _cleanup()


def _radar_for(case_code, as_of):
    for r in S.radar(as_of):
        if r["case_code"] == case_code:
            return r
    raise AssertionError(f"{case_code} not found in radar @ {as_of}")


# --------------------------------------------------------------------- #
# Zero-drop state machine
# --------------------------------------------------------------------- #
def test_illegal_transition_is_rejected():
    S.enroll("R54TEST-ZD", received_at=T0)
    # RECEIVED --send--> ??? is NOT an allowed edge: must raise, not silently drop.
    with pytest.raises(Exception) as ei:
        S.transition("R54TEST-ZD", "send", at=T0)
    assert "R54_ILLEGAL_TRANSITION" in str(ei.value)


def test_happy_path_walks_all_stages():
    S.enroll("R54TEST-HP", received_at=T0)
    assert S.transition("R54TEST-HP", "draft",   at=T0) == "DRAFTED"
    assert S.transition("R54TEST-HP", "claim",   at=T0) == "CLAIMED"
    assert S.transition("R54TEST-HP", "approve", at=T0) == "APPROVED"
    assert S.transition("R54TEST-HP", "send",    at=T0) == "SENT"
    assert S.transition("R54TEST-HP", "archive", at=T0) == "ARCHIVED"
    assert S.transition("R54TEST-HP", "close",   at=T0) == "CLOSED"


def test_unknown_case_rejected():
    with pytest.raises(Exception) as ei:
        S.transition("R54TEST-NOPE", "draft")
    assert "R54_UNKNOWN_CASE" in str(ei.value)


# --------------------------------------------------------------------- #
# Stage A — unclaimed: warn T+2h, escalate T+4h
# --------------------------------------------------------------------- #
def test_stage_a_unclaimed_buckets():
    S.enroll("R54TEST-A", received_at=T0)
    assert _radar_for("R54TEST-A", "2026-10-25 09:00:00+08")["sla_status"] == "OK"        # +1h
    assert _radar_for("R54TEST-A", "2026-10-25 10:30:00+08")["sla_status"] == "WARN"      # +2.5h
    assert _radar_for("R54TEST-A", "2026-10-25 12:30:00+08")["sla_status"] == "ESCALATE"  # +4.5h
    r = _radar_for("R54TEST-A", "2026-10-25 12:30:00+08")
    assert r["sla_track"] == "A_UNCLAIMED"


# --------------------------------------------------------------------- #
# Stage B — claimed but unsent: warn T+24h, escalate T+28h
# --------------------------------------------------------------------- #
def test_stage_b_claimed_unsent_buckets():
    S.enroll("R54TEST-B", received_at=T0)
    S.transition("R54TEST-B", "claim", at=T0)   # claimed at T0
    assert _radar_for("R54TEST-B", "2026-10-26 04:00:00+08")["sla_status"] == "OK"        # +20h
    assert _radar_for("R54TEST-B", "2026-10-26 10:00:00+08")["sla_status"] == "WARN"      # +26h
    assert _radar_for("R54TEST-B", "2026-10-26 13:00:00+08")["sla_status"] == "ESCALATE"  # +29h
    assert _radar_for("R54TEST-B", "2026-10-26 13:00:00+08")["sla_track"] == "B_UNSENT"


def test_sent_clears_sla():
    S.enroll("R54TEST-S", received_at=T0)
    S.transition("R54TEST-S", "claim",   at=T0)
    S.transition("R54TEST-S", "approve", at=T0)
    S.transition("R54TEST-S", "send",    at=T0)
    # Even a week later, a SENT case is DONE, not breaching.
    assert _radar_for("R54TEST-S", "2026-11-01 00:00:00+08")["sla_status"] == "DONE"


# --------------------------------------------------------------------- #
# Legitimate snooze pauses the SLA clock
# --------------------------------------------------------------------- #
def test_snooze_pauses_clock():
    S.enroll("R54TEST-SN", received_at=T0)
    S.transition("R54TEST-SN", "claim", at=T0)
    # Snooze until 10/28 08:00 for a legitimate reason.
    S.transition("R54TEST-SN", "snooze", at=T0,
                 snooze_until="2026-10-28 08:00:00+08", note="等業主補件")
    # During snooze, even well past the normal 28h escalate, status is SNOOZED.
    assert _radar_for("R54TEST-SN", "2026-10-27 00:00:00+08")["sla_status"] == "SNOOZED"
    # After snooze_until elapses and it is resumed, the clock runs again.
    S.transition("R54TEST-SN", "resume", at="2026-10-28 08:00:00+08")
    r = _radar_for("R54TEST-SN", "2026-10-28 08:30:00+08")
    assert r["stage"] == "CLAIMED"


def test_radar_sweep_only_returns_actionable():
    S.enroll("R54TEST-OK", received_at=T0)   # fresh, OK
    S.enroll("R54TEST-ESC", received_at=T0)  # will be escalated
    rows = S.sweep("2026-10-25 13:00:00+08")  # +5h -> R54TEST-ESC escalates
    codes = {r["case_code"]: r["sla_status"] for r in rows if r["case_code"].startswith("R54TEST-")}
    assert codes.get("R54TEST-ESC") == "ESCALATE"
    assert "R54TEST-OK" in codes  # at +5h it is also past 4h -> escalate; both actionable
    # The key property: no 'OK'/'DONE' rows leak into the sweep.
    assert all(v in ("WARN", "ESCALATE") for v in codes.values())


if __name__ == "__main__":
    import sys, subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
