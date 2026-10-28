#!/usr/bin/env python3
"""R55 signature & brand guard tests.

Guarantees for every generated draft body:
  (a) the official company full name '詠翔測量工程有限公司' is force-injected;
  (b) a non-empty sign-off block is always present (never blank);
  (c) ZERO residual forbidden strings ('永祥工程', '永祥測量...', '宣蓉').

Network/DB are NOT touched: we import the server module and exercise the pure
`enforce_brand` function and, when the DB is reachable, the watcher signature
builder. Both are the two force-injection points in the product.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
COMPANY = "詠翔測量工程有限公司"
FORBIDDEN = ["永祥工程", "永祥測量", "宣蓉"]


def _load(modname: str, path: Path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def srv():
    # Import without binding sockets: the module only defines handlers at import.
    return _load("_sbx_server", ROOT / "switchboard_ui_server.py")


# ---- Representative draft bodies as produced by the :5188 endpoints --------
DRAFTS = [
    # legacy signoff that MUST be rewritten
    "林課長您好：\n\n期末成果圖敬請查收。\n\n永祥工程 敬上",
    # stale股份有限公司 variant mid-body
    "本案由永祥測量工程股份有限公司辦理。\n\n永祥工程 敬上",
    # forbidden person name present
    "請洽行政宣蓉確認請款日期。\n\n永祥工程 敬上",
    # NO signoff at all -> fallback must inject one
    "吳工程師您好：\n北側管線修正圖已完成，隨信附上對外版 PDF。",
    # empty body
    "",
    # already-correct body stays correct (idempotent)
    "陳主任您好：\n\n報告已完成，敬請查收。\n\n" + COMPANY + " 敬上",
]


@pytest.mark.parametrize("body", DRAFTS)
def test_enforce_brand_contract(srv, body):
    out = srv.enforce_brand(body)
    # (a) company full name force-injected
    assert COMPANY in out, f"missing company name in: {out!r}"
    # (b) non-empty sign-off present
    assert f"{COMPANY} 敬上" in out, f"missing sign-off in: {out!r}"
    assert out.strip(), "output unexpectedly blank"
    # (c) zero forbidden residue
    for bad in FORBIDDEN:
        assert bad not in out, f"forbidden token {bad!r} survived in: {out!r}"


def test_enforce_brand_idempotent(srv):
    body = "測試內文。\n\n永祥工程 敬上"
    once = srv.enforce_brand(body)
    twice = srv.enforce_brand(once)
    assert once == twice
    assert once.count(f"{COMPANY} 敬上") == 1


def test_no_forbidden_in_live_templates():
    """Static scan: live code/templates/seed must carry no forbidden strings."""
    # Templates + seed data that feed generated output. (The server modules are
    # excluded here because their `enforce_brand` guard legitimately embeds the
    # forbidden tokens as detection patterns; those paths are covered by the
    # behavioural tests above.)
    targets = [
        "seed_yezhu_real_db.py",
        "laptop_ui_bundle/seed_yezhu_real_db.py",
        "ui/index.html",
        "static/index.html",
        "static/simple_yezhu.html",
        "laptop_ui_bundle/ui/index.html",
        "/workspace/signature/jk_signature.html",
        "/workspace/signature/robin_signature.html",
        "/workspace/signature/signatures.txt",
    ]
    hits = []
    for rel in targets:
        p = ROOT / rel
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8")
        for bad in ["永祥工程", "永祥測量", "宣蓉"]:
            if bad in txt:
                hits.append(f"{rel}: {bad}")
    assert not hits, f"forbidden strings still present: {hits}"


# ---- Signature coverage: 67/67 active staff, no blank signature ------------
def _psql(sql: str):
    import subprocess
    try:
        return subprocess.check_output(
            ["psql", "-X", "-d", "yongxiang_plumb_r39_clone", "-At", "-c", sql],
            text=True, timeout=5,
        ).strip()
    except Exception:
        return None


def test_signature_coverage_67_of_67():
    row = _psql(
        "SELECT count(*), "
        "count(*) FILTER (WHERE COALESCE("
        "NULLIF(btrim(COALESCE(email_signature_text,'')),''),"
        "NULLIF(btrim(COALESCE(public.fn_employee_email_signature_text(lark_open_id, full_name),'')),'')"
        ") IS NULL) "
        "FROM public.employee WHERE org_id='YX' AND employment_status='active';"
    )
    if row is None:
        pytest.skip("clone DB not reachable")
    total, empty = row.split("|")
    assert total == "67", f"expected 67 active staff, got {total}"
    assert empty == "0", f"{empty} active staff resolve to a BLANK signature"


def test_watcher_signature_always_company_and_nonempty():
    """Watcher sig builder must never return a blank sig and always carry the
    official company name, even on DB failure (hardcoded fallback path)."""
    if not (ROOT / "live_jk_test_watcher.py").exists():
        pytest.skip("watcher module absent")
    w = _load("_sbx_watcher", ROOT / "live_jk_test_watcher.py")
    # Unknown open_id -> DB miss -> fallback path; must still be valid.
    name, plain_sig, html_sig = w.get_employee_signature("ou_nonexistent_xxx", "測試員")
    assert name, "empty sender name"
    assert plain_sig.strip(), "blank plain signature block"
    assert COMPANY in plain_sig, "company name missing from signature"
    for bad in FORBIDDEN:
        assert bad not in plain_sig, f"forbidden {bad!r} in signature"
    # normalize_company_and_attach_sig guarantees sig attachment + scrub.
    out = w.normalize_company_and_attach_sig(
        "測試內文。\n\n永祥工程 敬上", "ou_nonexistent_xxx", "測試員"
    )
    assert COMPANY in out
    assert "永祥工程" not in out
    assert out.strip()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
