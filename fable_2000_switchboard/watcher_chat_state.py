#!/usr/bin/env python3
"""Per-chat draft state with a global per-case anti-collision lock (R54).

Fixes the real race in live_jk_test_watcher.py where a single global
``current_draft`` / ``draft_version`` / ``active_card_msg_id`` / ``all_card_msg_ids``
was shared across JK's DM chat and 林育寬's DM chat. Two people testing in two
different chats clobbered each other's draft, and ``patch_all_cards`` fanned a
single draft out onto *every* card in *every* chat.

Design (agreed in R53/R54 discussion with JK):

* **Draft editing state is per-chat.**  Each chat_id owns its own
  ``current_draft`` / ``draft_version`` / ``status`` / ``active_card_msg_id`` /
  ``all_card_msg_ids``.  A card is only ever patched together with other cards
  *in the same chat*.
* **The anti-collision lock (防撞鎖) stays GLOBAL per case.**  This is the whole
  point of the softlock: if 林育寬 claims #C115055-1 in his chat, JK must not be
  able to silently edit/approve the same client letter from his chat.  The lock
  is keyed by case_code, not by chat.

This module is intentionally free of any network / lark-cli / subprocess calls
so it can be unit-tested deterministically.
"""
from __future__ import annotations

import copy
from typing import Any, Optional


# A brand-new per-chat draft slot. ``None`` fields mean "inherit the seed draft".
def _blank_chat_slot(seed_draft: str, seed_version: int = 1) -> dict:
    return {
        "current_draft": seed_draft,
        "draft_version": seed_version,
        "status": "pending",
        "active_card_msg_id": "",
        "all_card_msg_ids": [],
    }


def ensure_chat_slot(state: dict, chat_id: str, seed_draft: str, seed_version: int = 1) -> dict:
    """Return the per-chat draft slot for ``chat_id``, creating it on first use.

    Falls back gracefully: if ``chat_id`` is empty (e.g. a card callback that did
    not carry chat_id), a shared ``"__default__"`` slot is used so single-chat
    behaviour is byte-for-byte identical to the legacy watcher.
    """
    key = chat_id or "__default__"
    chats = state.setdefault("chats", {})
    if key not in chats:
        chats[key] = _blank_chat_slot(seed_draft, seed_version)
    return chats[key]


def get_draft(state: dict, chat_id: str, seed_draft: str) -> tuple[str, int, str]:
    slot = ensure_chat_slot(state, chat_id, seed_draft)
    return slot["current_draft"], int(slot["draft_version"]), slot["status"]


def set_draft(
    state: dict,
    chat_id: str,
    draft: str,
    version: int,
    status: str,
    seed_draft: str,
) -> dict:
    slot = ensure_chat_slot(state, chat_id, seed_draft)
    slot["current_draft"] = draft
    slot["draft_version"] = int(version)
    slot["status"] = status
    return slot


class DraftVersionConflict(Exception):
    """Raised when a compare-and-swap write loses a race with a concurrent edit."""


def set_draft_cas(
    state: dict,
    chat_id: str,
    draft: str,
    new_version: int,
    status: str,
    seed_draft: str,
    expected_version: int,
) -> dict:
    """Optimistic-lock write: only commit if the slot is still at ``expected_version``.

    This is the compare-and-swap guard that stops two concurrent edits *in the same
    chat / on the same case* from silently clobbering each other. The caller reads
    ``draft_version`` first, computes its new draft, then commits here; if another
    writer bumped the version in between, this raises ``DraftVersionConflict`` and the
    in-flight draft is NOT overwritten.
    """
    slot = ensure_chat_slot(state, chat_id, seed_draft)
    current = int(slot["draft_version"])
    if current != int(expected_version):
        raise DraftVersionConflict(
            f"chat={chat_id or '__default__'} expected v{expected_version} but slot is at v{current}"
        )
    slot["current_draft"] = draft
    slot["draft_version"] = int(new_version)
    slot["status"] = status
    return slot


def register_card(state: dict, chat_id: str, msg_id: str, seed_draft: str) -> None:
    """Record a card message id *scoped to its chat* and mark it active there."""
    if not msg_id:
        return
    slot = ensure_chat_slot(state, chat_id, seed_draft)
    if msg_id not in slot["all_card_msg_ids"]:
        slot["all_card_msg_ids"].append(msg_id)
    slot["active_card_msg_id"] = msg_id
    # Reverse index so a card callback that only knows msg_id can find its chat.
    state.setdefault("card_chat_map", {})[msg_id] = chat_id or "__default__"


def cards_in_chat(state: dict, chat_id: str) -> list[str]:
    """Card ids to PATCH for this chat ONLY — never cross-chat."""
    key = chat_id or "__default__"
    slot = (state.get("chats") or {}).get(key)
    if not slot:
        return []
    ids = list(dict.fromkeys([*slot.get("all_card_msg_ids", []), slot.get("active_card_msg_id", "")]))
    return [m for m in ids if m]


def chat_for_card(state: dict, msg_id: str) -> str:
    return (state.get("card_chat_map") or {}).get(msg_id, "")


# --------------------------------------------------------------------------- #
# Global per-case anti-collision lock (shared across ALL chats).
# --------------------------------------------------------------------------- #
def case_lock(state: dict, case_code: str) -> dict:
    locks = state.setdefault("case_locks", {})
    return locks.setdefault(case_code, {"open_id": "", "name": ""})


def is_locked_by_other(state: dict, case_code: str, open_id: str) -> bool:
    lock = case_lock(state, case_code)
    holder = lock.get("open_id") or ""
    return bool(holder) and holder != open_id


def acquire_lock(state: dict, case_code: str, open_id: str, name: str) -> None:
    lock = case_lock(state, case_code)
    lock["open_id"] = open_id
    lock["name"] = name


def release_lock(state: dict, case_code: str) -> None:
    """Release the softlock — MUST be called on approve/handoff completion so the
    case does not stay collision-locked forever (bug #3)."""
    lock = case_lock(state, case_code)
    lock["open_id"] = ""
    lock["name"] = ""


def lock_holder_name(state: dict, case_code: str) -> str:
    return case_lock(state, case_code).get("name") or ""


def migrate_legacy_state(state: dict, seed_draft: str, default_chat_id: str) -> dict:
    """One-time upgrade of a legacy single-global state blob to the per-chat shape.

    Preserves JK's existing draft under his chat so a restart mid-test is lossless.
    """
    state = copy.deepcopy(state)
    if "chats" not in state:
        slot = _blank_chat_slot(
            state.get("current_draft", seed_draft),
            int(state.get("draft_version", 1)),
        )
        slot["status"] = state.get("status", "pending")
        slot["active_card_msg_id"] = state.get("active_card_msg_id", "")
        slot["all_card_msg_ids"] = list(state.get("all_card_msg_ids", []))
        state["chats"] = {(default_chat_id or "__default__"): slot}
    if "case_locks" not in state:
        state["case_locks"] = {}
        legacy_holder = state.get("locked_by_open_id") or ""
        if legacy_holder:
            state["case_locks"]["C115055-1"] = {
                "open_id": legacy_holder,
                "name": state.get("locked_by_name", ""),
            }
    return state
