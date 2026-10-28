#!/usr/bin/env python3
"""Unit tests for the R54 per-chat draft state + global case lock.

Run: python3 -m pytest test_watcher_chat_state.py -v
"""
import watcher_chat_state as W

JK_CHAT = "oc_01d9828173a2920809b16248fe28989d"
YUKUAN_CHAT = "oc_9d424caa98d70d2e9d11225e9c00b404"
JK_OID = "ou_jk"
YUKUAN_OID = "ou_yukuan"
SEED = "林工程師您好：\n關於 C115055-1 ..."
CASE = "C115055-1"


# --------------------------------------------------------------------------- #
# 1. Regression: the OLD global model clobbers across chats.
# --------------------------------------------------------------------------- #
def test_legacy_global_model_clobbers_across_chats():
    """Documents the bug: one shared current_draft => last writer wins, and a
    single all_card_msg_ids list fans one draft onto both chats' cards."""
    legacy = {
        "current_draft": SEED,
        "draft_version": 1,
        "all_card_msg_ids": ["om_jk_card"],
        "active_card_msg_id": "om_jk_card",
    }
    # JK edits price in his chat.
    legacy["current_draft"] = "JK: NT$180,000"
    legacy["draft_version"] = 2
    legacy["all_card_msg_ids"].append("om_yukuan_card")  # 林育寬's card joins the SAME list
    # 林育寬 edits delivery date in his chat -> overwrites the single global draft.
    legacy["current_draft"] = "YUKUAN: 週五交件"
    legacy["draft_version"] = 3

    # JK's edit is gone, and patch would hit BOTH cards with 林育寬's text.
    assert legacy["current_draft"] == "YUKUAN: 週五交件"
    assert "om_jk_card" in legacy["all_card_msg_ids"]
    assert "om_yukuan_card" in legacy["all_card_msg_ids"]  # cross-chat fan-out


# --------------------------------------------------------------------------- #
# 2. New model: drafts are isolated per chat.
# --------------------------------------------------------------------------- #
def test_per_chat_drafts_do_not_clobber():
    st = {}
    W.set_draft(st, JK_CHAT, "JK: NT$180,000", 2, "pending", SEED)
    W.set_draft(st, YUKUAN_CHAT, "YUKUAN: 週五交件", 2, "pending", SEED)

    jk_draft, jk_ver, _ = W.get_draft(st, JK_CHAT, SEED)
    yk_draft, yk_ver, _ = W.get_draft(st, YUKUAN_CHAT, SEED)

    assert jk_draft == "JK: NT$180,000"
    assert yk_draft == "YUKUAN: 週五交件"
    assert jk_ver == yk_ver == 2  # independent versions


def test_cards_never_cross_chat():
    st = {}
    W.register_card(st, JK_CHAT, "om_jk_card", SEED)
    W.register_card(st, YUKUAN_CHAT, "om_yukuan_card", SEED)

    assert W.cards_in_chat(st, JK_CHAT) == ["om_jk_card"]
    assert W.cards_in_chat(st, YUKUAN_CHAT) == ["om_yukuan_card"]
    # The reverse index lets a bare card callback recover its chat.
    assert W.chat_for_card(st, "om_yukuan_card") == YUKUAN_CHAT


def test_multiple_cards_same_chat_all_patched():
    st = {}
    W.register_card(st, JK_CHAT, "om_jk_1", SEED)
    W.register_card(st, JK_CHAT, "om_jk_2", SEED)
    ids = W.cards_in_chat(st, JK_CHAT)
    assert ids == ["om_jk_1", "om_jk_2"]  # both, de-duped, no cross-chat leakage


# --------------------------------------------------------------------------- #
# 3. Global anti-collision lock survives the per-chat split.
# --------------------------------------------------------------------------- #
def test_global_lock_blocks_other_chat():
    st = {}
    W.acquire_lock(st, CASE, YUKUAN_OID, "林育寬")
    # JK, from a DIFFERENT chat, is still blocked on the same case.
    assert W.is_locked_by_other(st, CASE, JK_OID) is True
    # The holder himself is not blocked.
    assert W.is_locked_by_other(st, CASE, YUKUAN_OID) is False
    assert W.lock_holder_name(st, CASE) == "林育寬"


def test_lock_released_on_completion():
    st = {}
    W.acquire_lock(st, CASE, YUKUAN_OID, "林育寬")
    assert W.is_locked_by_other(st, CASE, JK_OID) is True
    W.release_lock(st, CASE)  # approve/handoff done
    # Now JK can act again — no permanent softlock (fixes bug #3).
    assert W.is_locked_by_other(st, CASE, JK_OID) is False


def test_two_cases_independent_locks():
    st = {}
    W.acquire_lock(st, "C115055-1", YUKUAN_OID, "林育寬")
    W.acquire_lock(st, "C999999-1", JK_OID, "許喆凱")
    assert W.is_locked_by_other(st, "C115055-1", JK_OID) is True
    assert W.is_locked_by_other(st, "C999999-1", JK_OID) is False


# --------------------------------------------------------------------------- #
# 4. Legacy migration is lossless.
# --------------------------------------------------------------------------- #
def test_migrate_legacy_state_preserves_draft_and_lock():
    legacy = {
        "current_draft": "JK working draft v4",
        "draft_version": 4,
        "status": "claimed",
        "active_card_msg_id": "om_live",
        "all_card_msg_ids": ["om_old", "om_live"],
        "locked_by_open_id": JK_OID,
        "locked_by_name": "許喆凱",
    }
    st = W.migrate_legacy_state(legacy, SEED, JK_CHAT)
    draft, ver, status = W.get_draft(st, JK_CHAT, SEED)
    assert draft == "JK working draft v4"
    assert ver == 4 and status == "claimed"
    assert W.cards_in_chat(st, JK_CHAT) == ["om_old", "om_live"]
    # Legacy global lock mapped onto the live case.
    assert W.is_locked_by_other(st, CASE, YUKUAN_OID) is True


def test_cas_blocks_concurrent_same_chat_clobber():
    """set_draft_cas is the second line of defence: two edits on the SAME case in the
    SAME chat cannot silently overwrite each other (optimistic lock)."""
    st = {}
    W.set_draft(st, JK_CHAT, "v1 body", 1, "pending", SEED)
    # Two handlers both read v1.
    _, base_ver, _ = W.get_draft(st, JK_CHAT, SEED)
    assert base_ver == 1
    # Writer A commits v2 first.
    W.set_draft_cas(st, JK_CHAT, "A edit", base_ver + 1, "pending", SEED, expected_version=base_ver)
    # Writer B still thinks it is on v1 -> must be rejected, A's edit preserved.
    try:
        W.set_draft_cas(st, JK_CHAT, "B edit", base_ver + 1, "pending", SEED, expected_version=base_ver)
        assert False, "expected DraftVersionConflict"
    except W.DraftVersionConflict:
        pass
    draft, ver, _ = W.get_draft(st, JK_CHAT, SEED)
    assert draft == "A edit" and ver == 2


def test_cas_commits_when_version_matches():
    st = {}
    W.set_draft(st, JK_CHAT, "v1", 1, "pending", SEED)
    W.set_draft_cas(st, JK_CHAT, "v2", 2, "approved", SEED, expected_version=1)
    draft, ver, status = W.get_draft(st, JK_CHAT, SEED)
    assert (draft, ver, status) == ("v2", 2, "approved")


def test_empty_chat_id_falls_back_to_default_slot():
    st = {}
    W.set_draft(st, "", "fallback draft", 1, "pending", SEED)
    draft, _, _ = W.get_draft(st, "", SEED)
    assert draft == "fallback draft"
    # A card with no chat still patches only within the default slot.
    W.register_card(st, "", "om_nochat", SEED)
    assert W.cards_in_chat(st, "") == ["om_nochat"]


if __name__ == "__main__":
    import sys
    import subprocess
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
