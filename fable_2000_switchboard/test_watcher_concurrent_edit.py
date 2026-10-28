#!/usr/bin/env python3
"""Integration tests for per-chat draft isolation + CAS in live_jk_test_watcher.

Reproduces the two-chat concurrent-edit scenario:
  * JK edits in chat oc_01d9828173a2920809b16248fe28989d
  * 林育寬 edits in chat oc_9d424caa98d70d2e9d11225e9c00b404
and proves (a) their drafts never clobber each other, and (b) a stale write on
the SAME chat/case is rejected by the compare-and-swap version guard instead of
silently overwriting an in-flight draft.

ALL I/O is stubbed — no DB (psql), no network (lark-cli), no real email/Lark send.
Run: python3 -m pytest test_watcher_concurrent_edit.py -v
"""
import importlib
import json

import pytest

import watcher_chat_state as W

live = importlib.import_module("live_jk_test_watcher")

JK_CHAT = live.CHAT_ID
YK_CHAT = live.YUKUAN_CHAT_ID
JK_OID = live.JK_OPEN_ID
YK_OID = live.YUKUAN_OPEN_ID
CASE = live.CASE_CODE


@pytest.fixture(autouse=True)
def stub_all_io(tmp_path, monkeypatch):
    """Isolate state to a temp file and stub every subprocess / network call."""
    monkeypatch.setattr(live, "STATE_FILE", tmp_path / "state.json")

    # Deterministic signatures — no psql.
    def fake_sig(open_id=JK_OID, fallback_name="許喆凱"):
        if open_id == YK_OID:
            return "林育寬", "林育寬-sig", "<b>林育寬</b>"
        return "許喆凱", "許喆凱-sig", "<b>許喆凱</b>"

    monkeypatch.setattr(live, "get_employee_signature", fake_sig)
    monkeypatch.setattr(live, "resolve_colleague_in_text",
                        lambda t: (YK_OID, "林育寬") if ("林育寬" in t or "育寬" in t) else ("", ""))

    # Kill ALL outbound side effects.
    monkeypatch.setattr(live, "react_to_message", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(live, "patch_cards_in_chat", lambda *a, **k: None)
    monkeypatch.setattr(live, "patch_all_cards", lambda *a, **k: None)
    monkeypatch.setattr(live, "update_card_by_token", lambda *a, **k: None)
    monkeypatch.setattr(live, "send_sandbox_email_to_jk", lambda *a, **k: None)

    sent = []
    monkeypatch.setattr(live, "send_bot_markdown",
                        lambda md, **k: sent.append(("md", md, k)) or f"om_md_{len(sent)}")
    monkeypatch.setattr(live, "send_bot_card",
                        lambda card, **k: sent.append(("card", card, k)) or f"om_card_{len(sent)}")
    # Belt-and-braces: any subprocess call should blow up the test, never run.
    monkeypatch.setattr(live.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("subprocess.run called")))
    monkeypatch.setattr(live.subprocess, "check_output",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("subprocess.check_output called")))
    return sent


def _read_state():
    return json.loads(live.STATE_FILE.read_text())


def _draft_in(chat_id):
    st = _read_state()
    seed = live.normalize_company_and_attach_sig(live.DEFAULT_BODY_CORE)
    d, v, s = W.get_draft(st, chat_id, seed)
    return d, v, s


# --------------------------------------------------------------------------- #
# 1. Two chats editing simultaneously must NOT clobber each other.
# --------------------------------------------------------------------------- #
def test_two_chats_concurrent_edit_isolated():
    # JK changes the price in his chat.
    live.handle_user_text("報價改 18 萬", "m_jk_1", sender_id=JK_OID, chat_id=JK_CHAT)
    # 林育寬 changes the delivery date in his chat.
    live.handle_user_text("改週五交件", "m_yk_1", sender_id=YK_OID, chat_id=YK_CHAT)

    jk_draft, jk_ver, _ = _draft_in(JK_CHAT)
    yk_draft, yk_ver, _ = _draft_in(YK_CHAT)

    # JK's edit survived and is NOT contaminated by 林育寬's edit.
    assert "180,000" in jk_draft
    assert "週五" not in jk_draft
    # 林育寬's edit survived and is NOT contaminated by JK's edit.
    assert "週五" in yk_draft
    assert "180,000" not in yk_draft
    # Each chat tracks its own version counter (JK's chat inherits the migrated
    # legacy seed v2 -> v3; 林育寬's fresh slot v1 -> v2). The point is they are
    # tracked independently, not shared.
    assert jk_ver >= 2 and yk_ver >= 2


def test_cards_registered_per_chat_only():
    live.handle_user_text("報價改 18 萬", "m_jk_1", sender_id=JK_OID, chat_id=JK_CHAT)
    live.handle_user_text("改週五交件", "m_yk_1", sender_id=YK_OID, chat_id=YK_CHAT)
    st = _read_state()
    jk_cards = set(W.cards_in_chat(st, JK_CHAT))
    yk_cards = set(W.cards_in_chat(st, YK_CHAT))
    assert jk_cards and yk_cards
    assert jk_cards.isdisjoint(yk_cards)  # no card leaks across chats


# --------------------------------------------------------------------------- #
# 2. Global anti-collision lock spans chats (claim in one blocks the other).
# --------------------------------------------------------------------------- #
def test_claim_in_one_chat_blocks_edit_from_other_chat():
    # 林育寬 claims the case in HIS chat.
    live.handle_user_text("我來處理", "m_yk_claim", sender_id=YK_OID, chat_id=YK_CHAT)
    st = _read_state()
    assert W.lock_holder_name(st, CASE) == "林育寬"

    # JK now tries to edit from HIS (different) chat -> must be soft-locked out,
    # and JK's chat draft must be untouched.
    jk_before, ver_before, _ = _draft_in(JK_CHAT)
    live.handle_user_text("報價改 18 萬", "m_jk_blocked", sender_id=JK_OID, chat_id=JK_CHAT)
    jk_after, ver_after, _ = _draft_in(JK_CHAT)
    assert jk_after == jk_before
    assert ver_after == ver_before  # no version bump on a blocked edit
    assert "180,000" not in jk_after


# --------------------------------------------------------------------------- #
# 3. Compare-and-swap: a stale same-chat write is rejected, not clobbering.
# --------------------------------------------------------------------------- #
def test_cas_rejects_stale_same_chat_write():
    seed = live.normalize_company_and_attach_sig(live.DEFAULT_BODY_CORE)
    st = {}
    # Seed the slot and read its real starting version (fresh slots start at v1).
    _, base, _ = W.get_draft(st, JK_CHAT, seed)
    # Editor A reads base, computes a new draft, commits -> base+1.
    W.set_draft_cas(st, JK_CHAT, "A edit", base + 1, "pending", seed, expected_version=base)
    assert W.get_draft(st, JK_CHAT, seed)[1] == base + 1

    # Editor B had ALSO read v2 (stale) and now tries to commit on top of it.
    with pytest.raises(W.DraftVersionConflict):
        W.set_draft_cas(st, JK_CHAT, "B edit", base + 1, "pending", seed, expected_version=base)

    # A's in-flight draft is intact — B did not silently overwrite it.
    assert W.get_draft(st, JK_CHAT, seed)[0] == "A edit"


def test_cas_allows_fresh_write():
    seed = live.normalize_company_and_attach_sig(live.DEFAULT_BODY_CORE)
    st = {}
    _, base, _ = W.get_draft(st, JK_CHAT, seed)
    W.set_draft_cas(st, JK_CHAT, "next", base + 1, "pending", seed, expected_version=base)
    # Re-read current version, then commit on top -> succeeds.
    _, cur, _ = W.get_draft(st, JK_CHAT, seed)
    W.set_draft_cas(st, JK_CHAT, "newer", cur + 1, "pending", seed, expected_version=cur)
    assert W.get_draft(st, JK_CHAT, seed)[0] == "newer"


if __name__ == "__main__":
    import subprocess
    import sys
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
