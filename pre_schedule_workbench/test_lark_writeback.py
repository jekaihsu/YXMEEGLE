"""
MOCK / DRY-RUN tests for the Lark Base writeback robustness layer (app.py).

SAFETY: these tests NEVER hit the network. They inject a fake lark-cli runner
(app.LARK_CLI_RUNNER) and monkeypatch time.sleep, so no real call to
open.larksuite / feishu is made and 吳科翰's clean demo rows are untouched.

Run:  python3 test_lark_writeback.py
"""
import json
import app


def _upsert_response(record_id):
    return json.dumps({
        "ok": True,
        "data": {"record": {"record_id_list": [record_id]}},
    })


def _rate_limited_response():
    # Shape mimicking a Lark 429 with a Retry-After hint.
    return json.dumps({
        "ok": False, "code": 1254290, "msg": "too many requests",
        "retry_after": 1,
    })


SLOT = {
    "slot_id": "PS-GHA-20261026-01",
    "work_date": "2026-10-26",
    "employee_name": "羅薇",          # 宣蓉 -> 羅薇
    "team_group": "地形A",
    "department_group": "外業部門",
    "slot_type": "出工",
    "start_time": "08:30", "end_time": "10:30", "hours": 2.0,
    "case_code": "C115016-6", "case_name": "台積電AP7廠區",
    "work_item": "施工放樣/鑑界",
    "v3_person_record_id": "recvqOQ3NKP7bd",
    "v3_case_record_id": "recvplqwMOmC17",
    "lark_record_id": "",
}


def test_429_then_200_backoff():
    sleeps = []
    # Simulated Lark backend: first a mocked record store keyed by idempotency key.
    store = {}

    def runner(cmd):
        # parse idempotency key + optional record-id from the dry-run cmd
        idem = cmd[cmd.index("--idempotency-key") + 1]
        rid = None
        if "--record-id" in cmd:
            rid = cmd[cmd.index("--record-id") + 1]
        runner.n += 1
        if runner.n == 1:
            return _rate_limited_response()          # transient 429
        # idempotent upsert: one logical row per idempotency key
        if idem not in store:
            store[idem] = rid or f"recMOCK_{len(store)+1:04d}"
        return _upsert_response(store[idem])
    runner.n = 0

    app.LARK_CLI_RUNNER = runner
    app.time.sleep = lambda s: sleeps.append(s)

    rec_id = app.sync_slot_to_lark_base(dict(SLOT))

    assert runner.n == 2, f"expected retry after 429, got {runner.n} calls"
    assert len(sleeps) == 1, f"expected exactly one backoff sleep, got {sleeps}"
    assert sleeps[0] >= 1.0, f"Retry-After=1 not respected: {sleeps[0]}"
    assert rec_id.startswith("rec"), rec_id
    print(f"[PASS] 429->200: retried once, backoff slept {sleeps[0]:.3f}s, rec_id={rec_id}")
    return store, rec_id


def test_idempotent_double_write_main():
    sleeps = []
    store = {}

    def runner(cmd):
        idem = cmd[cmd.index("--idempotency-key") + 1]
        rid = cmd[cmd.index("--record-id") + 1] if "--record-id" in cmd else None
        if idem not in store:
            store[idem] = rid or f"recMOCK_{len(store)+1:04d}"
        return _upsert_response(store[idem])

    app.LARK_CLI_RUNNER = runner
    app.time.sleep = lambda s: sleeps.append(s)

    row = dict(SLOT)
    rec1 = app.sync_slot_to_lark_base(row)
    # second write of the SAME logical slot (simulating a retry / re-submit).
    # Even with NO lark_record_id persisted locally, idempotency key dedupes.
    row2 = dict(SLOT)  # lark_record_id still ""
    rec2 = app.sync_slot_to_lark_base(row2)

    assert len(store) == 1, f"idempotency broken: {len(store)} logical rows: {store}"
    assert rec1 == rec2, f"same slot produced different ids: {rec1} vs {rec2}"
    print(f"[PASS] idempotent: two writes of {SLOT['slot_id']} -> ONE row ({rec1}); store={store}")


if __name__ == "__main__":
    print("=== MOCK/DRY-RUN Lark Base writeback tests (no network) ===")
    try:
        test_429_then_200_backoff()
        test_idempotent_double_write_main()
        print("\nALL TESTS PASSED")
    finally:
        app.LARK_CLI_RUNNER = None  # restore
