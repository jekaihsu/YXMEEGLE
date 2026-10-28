#!/usr/bin/env python3
"""
Apply Fable R42 (009d3_r41_fixpack.sql) + JK t788u/t789u/t797u Real Product DB Seed on Laptop/Box
Strictly targets yongxiang_plumb_r39_clone (asserts current_db != 'yongxiang_plumb').
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import db
import seed_yezhu_real_db


def lock_laptop_scripts():
    locked_files = []
    candidate_roots = []
    if os.name == "nt":
        candidate_roots.extend([
            Path(r"C:\Users\asus\wt-plumb-v2"),
            Path(r"C:\Users\asus\email_harmony_rag"),
            Path(r"C:\Users\asus\yongxiang_arch"),
            Path(r"C:\Users\asus\owner_reply_clean_app"),
            Path(r"\\wsl$\Ubuntu-22.04\workspace\wt-plumb-v2"),
            Path(r"\\wsl$\Ubuntu-22.04\workspace\email_harmony_rag"),
            Path(r"\\wsl$\Ubuntu-22.04\workspace\yongxiang_arch"),
        ])
        single_files = [
            Path(r"C:\Users\asus\write_r31b_report.py"),
            Path(r"\\wsl$\Ubuntu-22.04\workspace\write_r31b_report.py"),
        ]
    else:
        candidate_roots.extend([
            Path("/workspace/wt-plumb-v2"),
            Path("/workspace/email_harmony_rag"),
            Path("/workspace/yongxiang_arch/ai_switchboard_mvp"),
        ])
        single_files = [Path("/workspace/write_r31b_report.py")]

    py_files = [f for f in single_files if f.exists()]
    for croot in candidate_roots:
        try:
            if croot.exists():
                for f in croot.rglob("*.py"):
                    if ".venv" in str(f) or "site-packages" in str(f) or "__pycache__" in str(f):
                        continue
                    py_files.append(f)
        except Exception:
            pass

    for f in py_files:
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
            if "yongxiang_plumb" not in txt:
                continue
            new_txt = re.sub(r"yongxiang_plumb(?!_r39_clone|_clone|_test)", "yongxiang_plumb_r39_clone", txt)
            new_txt = new_txt.replace("!= 'yongxiang_plumb_r39_clone'", "!= 'yongxiang_plumb'")
            new_txt = new_txt.replace('!= "yongxiang_plumb_r39_clone"', '!= "yongxiang_plumb"')
            new_txt = new_txt.replace('== "yongxiang_plumb_r39_clone"', '== "yongxiang_plumb"')
            new_txt = new_txt.replace("== 'yongxiang_plumb_r39_clone'", "== 'yongxiang_plumb'")
            if new_txt != txt:
                f.write_text(new_txt, encoding="utf-8")
                locked_files.append(str(f))
        except Exception:
            pass
    return locked_files


def main():
    cur_db = db.assert_not_prod_db()
    assert cur_db != "yongxiang_plumb", f"FATAL: Forbidden from connecting to production DB (got {cur_db})"
    print(f"[1/6] Connected to non-prod clone DB: {cur_db}")

    locked = lock_laptop_scripts()
    print(f"[2/6] Locked scripts to yongxiang_plumb_r39_clone: {len(locked)} modified")

    # Locate 009d3_r41_fixpack.sql
    fixpack_candidates = [
        ROOT / "r42" / "009d3_r41_fixpack.sql",
        Path("/workspace/fable/r42/009d3_r41_fixpack.sql"),
    ]
    fixpack = next((p for p in fixpack_candidates if p.exists()), None)
    assert fixpack is not None, "009d3_r41_fixpack.sql not found"
    sha = hashlib.sha256(fixpack.read_bytes()).hexdigest()
    expected_sha = "5731aa15e07977327dbf3113553731a43f11779163a05221811f2ed84c7995a0"
    assert sha == expected_sha, f"SHA mismatch: got {sha}, expected {expected_sha}"
    print(f"[3/6] Verified 009d3_r41_fixpack.sql sha256={sha}")

    if os.name == "nt":
        for dst_dir in [Path(r"C:\Users\asus\fable\r42"), Path(r"\\wsl$\Ubuntu-22.04\workspace\fable\r42")]:
            try:
                dst_dir.mkdir(parents=True, exist_ok=True)
                for fname in ["009d3_r41_fixpack.sql", "cleanup_18_residual_synthetic_rows_DRAFT.sql", "009d3_targeted_checks.sql"]:
                    src = ROOT / "r42" / fname
                    if src.exists():
                        shutil.copy2(src, dst_dir / fname)
            except Exception:
                pass
        alt_ui = Path(r"C:\Users\asus\yongxiang_switchboard_ui")
        if alt_ui.exists():
            shutil.copy2(ROOT / "ui" / "index.html", alt_ui / "index.html")
            if (alt_ui / "ui").exists():
                shutil.copy2(ROOT / "ui" / "index.html", alt_ui / "ui" / "index.html")

    # Apply 009d3_r41_fixpack.sql
    sql_text = fixpack.read_text(encoding="utf-8")
    db.execute(sql_text)
    print("[4/6] Applied 009d3_r41_fixpack.sql cleanly")

    # Apply JK t788u (林瑩瑄 resigned, 羅薇 active admin) & gold_label annotator_a=羅薇, annotator_b=吳柏頤
    db.execute(
        """
        BEGIN;
        UPDATE public.employee SET employment_status = 'resigned', role_code = NULL
         WHERE id = '26a901c0-d648-529e-842f-b778a86cb559'::uuid;
        UPDATE public.employee SET role_code = 'admin', employment_status = 'active'
         WHERE id IN (
           'c22b9383-60ec-5bcf-8bb1-4131de44b420'::uuid,
           '45ab4194-04c9-59ef-bbd9-f1559b830c38'::uuid,
           '18d11143-a1c8-5afd-bcf1-229e064e930c'::uuid
         );
        UPDATE public.switchboard_gold_label
           SET annotator_a = '羅薇',
               annotator_b = '吳柏頤'
         WHERE annotator_a IS DISTINCT FROM '羅薇' OR annotator_b IS DISTINCT FROM '吳柏頤';
        COMMIT;
        """
    )
    print("[5/6] Enforced JK t788u (林瑩瑄 resigned, 羅薇/朱雅琪/郭倢瑛 active admins, gold_label 羅薇/吳柏頤)")

    # Seed real product tables (929 cases, 12,105 correspondence rows, 11 agents/connectors)
    seed_res = seed_yezhu_real_db.seed_database()
    print("[6/6] Seeded real product tables:", json.dumps(seed_res, ensure_ascii=False))

    # Final verification query
    summary = db.query(
        """
        SELECT jsonb_build_object(
            'current_db', current_database(),
            'r32_assert_all', public.r32_assert_all(),
            'wb_cases', (SELECT count(*) FROM public.yezhu_workbench_case),
            'corr_ledger', (SELECT count(*) FROM public.yezhu_correspondence_ledger),
            'agent_roster', (SELECT count(*) FROM public.switchboard_agent_roster),
            'active_admins', (SELECT jsonb_agg(full_name ORDER BY full_name) FROM public.employee WHERE role_code = 'admin' AND employment_status = 'active'),
            'lin_yingxuan_status', (SELECT employment_status FROM public.employee WHERE id = '26a901c0-d648-529e-842f-b778a86cb559'::uuid),
            'gold_label_annotators', (SELECT jsonb_agg(DISTINCT annotator_a || '/' || annotator_b) FROM public.switchboard_gold_label)
        )
        """
    )[0]
    print("VERIFICATION_SUMMARY:", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
