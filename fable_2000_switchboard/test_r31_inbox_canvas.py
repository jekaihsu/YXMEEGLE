"""
test_r31_inbox_canvas.py — R31 三件套 API 黃金測試（無需 Postgres，走 InMemoryRepo）
執行：python3 -m pytest -q test_r31_inbox_canvas.py
另含 SQL 靜態對照：008 的 canvas 視圖欄位是否在 Python 白名單規則下被正確裁剪。
"""
from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

import inbox_canvas_api as api

SQL_IDS = {"case.open_commitments", "invoice.unpaid", "outbound.gate_violations", "settlement.margin", "otp.seconds_left",
           "quote.diff_count", "review.reject_count", "subcontract.margin_delta"}
ORG = "00000000-0000-0000-0000-000000000001"
E_FIELD, E_PM, E_GM, E_ADMIN = "YX-F01", "YX-PM1", "YX-GM", "YX-ADM1"


def H(emp, role, org=ORG):
    return {"X-Employee-Id": emp, "X-Actor-Role": role, "X-Org-Id": org}


def mk_card(**over):
    base = {"org_id": ORG, "role": "settlement", "kind": "approve", "title": "C114109 結算待簽：未結承諾 2 筆",
            "assignee_employee_id": E_PM, "priority": 80,
            "evidence_numbers": [{"label": "未結承諾", "value": 2, "sql_id": "case.open_commitments"},
                                 {"label": "未收款", "value": 48000, "sql_id": "invoice.unpaid"},
                                 {"label": "毛利率", "value": 0.31, "sql_id": "settlement.margin"}],
            "actions": [{"action": "approve", "label": "簽核"}, {"action": "reject", "label": "退回"}, {"action": "unsure", "label": "不確定"}],
            "canvas_view": 6, "canvas_ref": {"settlement_id": "S-1"},
            "source_event_key": "settlement:S-1:ready_for_vp", "idempotency_key": "card:settlement:S-1:ready_for_vp:v1"}
    base.update(over)
    return base


V6_ROW = {"settlement_id": "S-1", "case_id": "C-1", "case_code": "C114109", "customer_name": "台塑", "client_total": 300000,
          "client_received": 252000, "client_unpaid": 48000, "labor_std_cost": 120000, "external_cost": 60000,
          "projected_total_cost": 180000, "projected_margin": 120000, "margin_ratio_now": 0.40, "margin_ratio_after": 0.31,
          "open_commitments": 2, "bonus_pool_total": 36000, "bonus_pool_allocation": {"YX-PM1": 12000},
          "state": "ready_for_vp"}


@pytest.fixture
def env():
    repo = api.InMemoryRepo(sql_ids=set(SQL_IDS))
    repo.canvas[(6, "S-1")] = dict(V6_ROW)
    repo.canvas[(2, "C-1")] = {"case_id": "C-1", "quote_no": "Q2026012", "quote_total": 300000, "wo_total": 300000, "diff_count": 0,
                               "quote_lines": [{"item": "地形測量", "unit_price": 1500}], "customer_name": "台塑"}
    cid = repo.add_card(mk_card())
    return repo, TestClient(api.build_app(repo)), cid


# ---------- 1. 數字必綁 SQL 來源 ----------
def test_01_evidence_without_sql_id_rejected(env):
    repo, _, _ = env
    bad = mk_card(idempotency_key="k2", source_event_key="e2",
                  evidence_numbers=[{"label": "未收款", "value": 48000}])
    with pytest.raises(ValueError, match="evidence_shape"):
        repo.add_card(bad)


def test_02_evidence_unknown_sql_id_rejected(env):
    repo, _, _ = env
    bad = mk_card(idempotency_key="k3", source_event_key="e3",
                  evidence_numbers=[{"label": "x", "value": 1, "sql_id": "made.up"}])
    with pytest.raises(ValueError, match="evidence_sql_unknown:made.up"):
        repo.add_card(bad)


def test_03_more_than_three_numbers_rejected(env):
    repo, _, _ = env
    ev = [{"label": f"n{i}", "value": i, "sql_id": "invoice.unpaid"} for i in range(4)]
    with pytest.raises(ValueError, match="evidence_count"):
        repo.add_card(mk_card(idempotency_key="k4", source_event_key="e4", evidence_numbers=ev))


def test_04_inbox_returns_card_with_sql_ids(env):
    _, client, cid = env
    r = client.get("/inbox", params={"role": "settlement"}, headers=H(E_PM, "pm"))
    assert r.status_code == 200
    cards = r.json()["cards"]
    assert [c["id"] for c in cards] == [cid]
    assert all("sql_id" in e for e in cards[0]["evidence_numbers"])
    assert len(cards[0]["evidence_numbers"]) <= 3 and 1 <= len(cards[0]["actions"]) <= 3


def test_05_inbox_double_check_drops_card_if_sql_id_vanishes(env):
    repo, client, cid = env
    repo.sql_ids.discard("settlement.margin")      # 模擬 evidence_sql 被刪
    r = client.get("/inbox", params={"role": "settlement"}, headers=H(E_PM, "pm"))
    assert r.json()["count"] == 0


# ---------- 2. 欄位白名單（API 層） ----------
def test_06_non_gm_cannot_get_bonus_pool_in_view6(env):
    _, client, cid = env
    for role in ("pm", "vp", "finance", "admin", "sales", "field_member"):
        r = client.get(f"/canvas/{cid}", headers=H(E_PM if role in ("pm", "vp") else E_GM, role))
        if r.status_code == 200:
            cols = set(r.json()["row"].keys())
            assert not (cols & api.GM_ONLY_COLUMNS), f"{role} leaked {cols & api.GM_ONLY_COLUMNS}"


def test_07_gm_gets_bonus_pool_in_view6(env):
    _, client, cid = env
    r = client.get(f"/canvas/{cid}", headers=H(E_GM, "gm"))
    assert r.status_code == 200
    assert api.GM_ONLY_COLUMNS <= set(r.json()["row"].keys())


def test_08_vp_sees_margin_but_not_bonus(env):
    _, client, cid = env
    r = client.get(f"/canvas/{cid}", headers=H("YX-VP", "vp"))
    row = r.json()["row"]
    assert "projected_margin" in row and "bonus_pool_total" not in row


def test_09_forbidden_columns_never_pass_for_any_role():
    poison = {"hourly_rate": 300, "base_salary": 42000, "monthly_salary": 1, "wage_x": 1, "net_pay": 1, "insured_salary": 45800,
              "bank_account_no": "x", "id_number": "x", "case_code": "C114109"}
    for role in api.ACTOR_RANK:
        for view in range(1, 7):
            out = api.project_columns(view, role, poison)
            assert set(out) == {"case_code"}, (role, view, out)


def test_10_forbidden_regex_matches_sql_definition():
    sql = open(os.path.join(os.path.dirname(__file__), "008_r31_inbox_and_canvas_views.sql"), encoding="utf-8").read()
    m = re.search(r"canvas_forbidden_column[\s\S]*?'(\((?:hourly|[^']+)\))'", sql)
    assert m, "forbidden regex not found in 008"
    assert m.group(1) == api.FORBIDDEN_COLUMN_RE.pattern, "Python/SQL forbidden regex drifted"


def test_11_sql_view6_bonus_columns_exist_and_are_gm_only_in_seed():
    sql = open(os.path.join(os.path.dirname(__file__), "008_r31_inbox_and_canvas_views.sql"), encoding="utf-8").read()
    assert "bonus_pool_total" in sql and "bonus_pool_allocation" in sql
    # 白名單種子：bonus 欄位只在 actor_role='gm' 之外排除
    assert re.search(r"bonus_pool.*gm", sql, re.S)


def test_12_quote_lines_hidden_below_sales(env):
    repo, client, _ = env
    cid = repo.add_card(mk_card(role="case", kind="confirm", canvas_view=2, canvas_ref={"case_id": "C-1"}, assignee_employee_id=E_FIELD,
                                actions=[{"action": "confirm", "label": "確認"}], idempotency_key="k12", source_event_key="e12"))
    r = client.get(f"/canvas/{cid}", headers=H(E_FIELD, "field_member"))
    assert r.status_code == 200 and "quote_lines" not in r.json()["row"] and "diff_count" in r.json()["row"]
    r = client.get(f"/canvas/{cid}", headers=H("YX-S1", "pm"))
    assert "quote_lines" in r.json()["row"]


def test_13_canvas_404_for_other_org_or_non_assignee_low_rank(env):
    _, client, cid = env
    assert client.get(f"/canvas/{cid}", headers=H(E_GM, "gm", org="00000000-0000-0000-0000-000000000002")).status_code == 404
    assert client.get(f"/canvas/{cid}", headers=H(E_FIELD, "field_member")).status_code == 404


# ---------- 3. POST /cards/{id}/act 冪等 + 稽核 ----------
def test_14_act_requires_idempotency_key(env):
    _, client, cid = env
    r = client.post(f"/cards/{cid}/act", json={"action": "approve"}, headers=H(E_PM, "pm"))
    assert r.status_code == 422


def test_15_act_writes_one_audit_row_and_replays(env):
    repo, client, cid = env
    hdr = {**H(E_PM, "pm"), "Idempotency-Key": "act-1"}
    r1 = client.post(f"/cards/{cid}/act", json={"action": "approve", "payload": {"note": "ok"}}, headers=hdr)
    r2 = client.post(f"/cards/{cid}/act", json={"action": "approve", "payload": {"note": "ok"}}, headers=hdr)
    assert r1.status_code == 200 and r1.json()["replayed"] is False and r1.json()["to_state"] == "acted"
    assert r2.status_code == 200 and r2.json()["replayed"] is True and r2.json()["to_state"] == "acted"
    assert len(repo.action_log) == 1
    log = repo.action_log["act-1"]
    assert log["from_state"] == "open" and log["to_state"] == "acted" and log["actor"] == E_PM and log["idempotency_key"] == "act-1"


def test_16_second_distinct_action_after_acted_is_409(env):
    _, client, cid = env
    client.post(f"/cards/{cid}/act", json={"action": "approve"}, headers={**H(E_PM, "pm"), "Idempotency-Key": "a1"})
    r = client.post(f"/cards/{cid}/act", json={"action": "reject"}, headers={**H(E_PM, "pm"), "Idempotency-Key": "a2"})
    assert r.status_code == 409


def test_17_rank_enforced_and_escalation_path(env):
    repo, client, _ = env
    cid = repo.add_card(mk_card(assignee_employee_id=E_FIELD, idempotency_key="k17", source_event_key="e17"))
    # field_member 不能 approve（min rank 20），但可以 unsure → escalated
    r = client.post(f"/cards/{cid}/act", json={"action": "approve"}, headers={**H(E_FIELD, "field_member"), "Idempotency-Key": "b1"})
    assert r.status_code == 409
    r = client.post(f"/cards/{cid}/act", json={"action": "unsure"}, headers={**H(E_FIELD, "field_member"), "Idempotency-Key": "b2"})
    assert r.json()["to_state"] == "escalated"
    # escalated 之後只有 pm+ 可 approve
    r = client.post(f"/cards/{cid}/act", json={"action": "approve"}, headers={**H(E_ADMIN, "admin"), "Idempotency-Key": "b3"})
    assert r.status_code == 409
    r = client.post(f"/cards/{cid}/act", json={"action": "approve"}, headers={**H(E_PM, "pm"), "Idempotency-Key": "b4"})
    assert r.json()["to_state"] == "acted"
    assert [l["to_state"] for l in repo.action_log.values()] == ["escalated", "acted"]


def test_18_non_assignee_low_rank_cannot_act(env):
    _, client, cid = env
    r = client.post(f"/cards/{cid}/act", json={"action": "approve"}, headers={**H("YX-S9", "sales"), "Idempotency-Key": "c1"})
    assert r.status_code == 409 and "assignee" in r.json()["detail"]


def test_19_dry_run_card_not_actable_and_not_in_inbox(env):
    repo, client, _ = env
    cid = repo.add_card(mk_card(mode="dry_run", idempotency_key="k19", source_event_key="settlement:S-1:ready_for_vp"))  # 同事件可與 live 並存
    assert client.get("/inbox", params={"role": "settlement"}, headers=H(E_PM, "pm")).json()["count"] == 1
    r = client.post(f"/cards/{cid}/act", json={"action": "approve"}, headers={**H(E_PM, "pm"), "Idempotency-Key": "d1"})
    assert r.status_code == 409 and "dry_run" in r.json()["detail"]


def test_20_duplicate_live_card_for_same_event_rejected(env):
    repo, _, _ = env
    with pytest.raises(ValueError, match="duplicate live card"):
        repo.add_card(mk_card(idempotency_key="k20"))


def test_21_single_assignee_required_and_illegal_action_rejected(env):
    repo, _, _ = env
    with pytest.raises(ValueError, match="assignee_required"):
        repo.add_card(mk_card(assignee_employee_id=None, idempotency_key="k21", source_event_key="e21"))
    with pytest.raises(ValueError, match="action_not_allowed:ack"):
        repo.add_card(mk_card(actions=[{"action": "ack"}], idempotency_key="k21b", source_event_key="e21b"))


def test_22_transition_table_matches_sql_seed():
    sql = open(os.path.join(os.path.dirname(__file__), "008_r31_inbox_and_canvas_views.sql"), encoding="utf-8").read()
    rows = re.findall(r"\('(approve|choose|confirm|fix|inform)','(open|escalated)','(\w+)','(acted|escalated)',(\d+)\)", sql)
    assert rows, "card_state_transition seed not found"
    sql_map = {(k, f, a): (t, int(r)) for k, f, a, t, r in rows}
    assert sql_map == api.TRANSITIONS, {"only_sql": set(sql_map) - set(api.TRANSITIONS), "only_py": set(api.TRANSITIONS) - set(sql_map)}
