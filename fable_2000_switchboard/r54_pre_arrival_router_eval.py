#!/usr/bin/env python3
"""
r54_pre_arrival_router_eval.py — R54「時光機」評估：Pre-arrival-only 路由。

契約：
  * 評估每封信 m 時，router 只能讀 received_at < m.received_at 的歷史資料。
    嚴禁讀「未來信」或事後回填欄位當作評估時可見的證據。
  * 本檔對同一組指標各跑兩次，唯一差別是「可見視窗」：
      - LEAKY（舊法 / 禁用）：可見 = 整個語料（含未來信）→ 事後諸葛，指標虛高。
      - CUTOFF（本法 / 強制）：可見 = received_at < m.received_at → 真正到信時能知道的。
    兩者用「同一個」evaluate() 函數，只差 visible 視窗，從結構上證明 cutoff 生效。
  * 報表每項指標都附分子 (hits) 與分母 (N)。
  * canary leak test：構造一封信，其唯一命中線索只存在於「未來信」。
      LEAKY 會命中（洩漏）；CUTOFF 不命中（未洩漏）→ 證明 cutoff 真正擋住未來資訊。
  * 唯讀：本程式不寫 DB、不發信（actual_sends = 0）。

用法：
  PG_DSN=postgresql://postgres:postgres@127.0.0.1:5432/yongxiang_plumb_r39_clone \
    python r54_pre_arrival_router_eval.py
輸出：r54_pre_arrival_eval_report.json / r54_pre_arrival_eval_report.md
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from switchboard_engine import classify_inbound_email, detect_org  # noqa: E402

ROOT = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=8))
SERIAL_RE = re.compile(r"業主往來\s*0*(\d{1,6})")
SUBJECT_PREFIX_RE = re.compile(r"^((re|fw|fwd|回覆|轉寄)\s*[:：]\s*)+", re.I)


@dataclass
class Mail:
    id: str
    received_at: datetime
    from_addr: str
    to_addrs: list[str]
    subject: str
    body: str
    category: str                # 回填後的 pseudo-label（stored）
    org_id: str                  # 回填後的 pseudo-label（stored）
    message_id: Optional[str] = None
    is_canary: bool = False

    @property
    def serial(self) -> Optional[str]:
        m = SERIAL_RE.search((self.subject or "") + " " + (self.body or ""))
        return m.group(1) if m else None

    @property
    def subject_root(self) -> str:
        s = SUBJECT_PREFIX_RE.sub("", self.subject or "")
        return re.sub(r"\s+", "", s).lower()


# ---------------------------------------------------------------------------
# 五個偽標籤指標：evaluate(m, visible) → (applicable, hit)
#   applicable=False 代表這封信不計入該指標的分母 N。
#   visible 是「router 這一刻被允許讀到的其他信」；LEAKY/CUTOFF 只差這個清單。
# ---------------------------------------------------------------------------
def metric_category_reproduction(m: Mail, visible: list[Mail]) -> tuple[bool, bool]:
    """① 類別重現：引擎對 m 本身重新分類，是否重現回填的 CAT 類別（per-email，不依賴歷史）。"""
    if not (m.category or "").startswith("CAT-"):
        return False, False
    c = classify_inbound_email(m.from_addr, m.to_addrs, m.subject, m.body)
    return True, (c.category == m.category)


def metric_org_attribution(m: Mail, visible: list[Mail]) -> tuple[bool, bool]:
    """② 組織歸屬：引擎對 m 本身判定 org，是否等於回填 org（per-email，不依賴歷史）。"""
    if not m.org_id:
        return False, False
    return True, (detect_org(m.to_addrs, m.subject, m.body) == m.org_id)


def metric_sender_known(m: Mail, visible: list[Mail]) -> tuple[bool, bool]:
    """③ 寄件者已知：到信當下，此寄件者是否已在可見歷史出現過（可據歷史脈絡路由）。"""
    return True, any(e.from_addr == m.from_addr for e in visible)


def metric_subject_thread(m: Mail, visible: list[Mail]) -> tuple[bool, bool]:
    """④ 主旨串接：到信當下，同一主旨串（去 Re:/Fw:）是否已在可見歷史出現。"""
    if not m.subject_root:
        return False, False
    return True, any(e.subject_root == m.subject_root for e in visible)


def metric_serial_continuity(m: Mail, visible: list[Mail]) -> tuple[bool, bool]:
    """⑤ 序號串接：帶業主往來序號的信，到信當下同序號是否已在可見歷史出現（舊串回覆沿用同號）。"""
    if not m.serial:
        return False, False
    return True, any(e.serial == m.serial for e in visible)


METRICS: list[tuple[str, str, Callable[[Mail, list[Mail]], tuple[bool, bool]]]] = [
    ("category_reproduction", "類別重現（per-email 控制組）", metric_category_reproduction),
    ("org_attribution", "組織歸屬（per-email 控制組）", metric_org_attribution),
    ("sender_known", "寄件者已知（歷史依賴）", metric_sender_known),
    ("subject_thread", "主旨串接（歷史依賴）", metric_subject_thread),
    ("serial_continuity", "序號串接（歷史依賴）", metric_serial_continuity),
]


# ---------------------------------------------------------------------------
# 兩種可見視窗
# ---------------------------------------------------------------------------
def visible_leaky(m: Mail, corpus: list[Mail]) -> list[Mail]:
    """舊法（禁用）：看得到整個語料，包含未來信。"""
    return [e for e in corpus if e.id != m.id]


def visible_cutoff(m: Mail, corpus: list[Mail]) -> list[Mail]:
    """本法（強制）：只看得到 received_at < m.received_at 的歷史。"""
    return [e for e in corpus if e.id != m.id and e.received_at < m.received_at]


def run_metrics(corpus: list[Mail], window: Callable[[Mail, list[Mail]], list[Mail]]) -> dict:
    out = {}
    for key, label, fn in METRICS:
        n = hits = 0
        for m in corpus:
            applicable, hit = fn(m, window(m, corpus))
            if applicable:
                n += 1
                hits += int(hit)
        out[key] = {"label": label, "hits": hits, "N": n,
                    "rate": round(hits / n, 4) if n else None}
    return out


# ---------------------------------------------------------------------------
# 載入語料（唯讀）
# ---------------------------------------------------------------------------
def load_corpus(dsn: str) -> list[Mail]:
    import psycopg
    rows = []
    with psycopg.connect(dsn) as conn:
        cur = conn.execute("""
            SELECT id::text, received_at, from_addr, coalesce(to_addrs,'{}'),
                   coalesce(subject,''), coalesce(body_new_text, body_text, ''),
                   coalesce(category,''), coalesce(org_id,''), message_id
              FROM email_message
             WHERE received_at IS NOT NULL
             ORDER BY received_at, id
        """)
        for r in cur.fetchall():
            rows.append(Mail(id=r[0], received_at=r[1], from_addr=(r[2] or "").strip().lower(),
                             to_addrs=list(r[3] or []), subject=r[4], body=r[5],
                             category=r[6], org_id=r[7], message_id=r[8]))
    return rows


# ---------------------------------------------------------------------------
# canary leak test：命中線索只存在於未來信
# ---------------------------------------------------------------------------
def build_canary(corpus: list[Mail]) -> tuple[Mail, list[Mail]]:
    """
    構造一封 canary 信 X（序號 999999、全新寄件者、全新主旨串），
    其唯一「同序號 / 同寄件者 / 同主旨」線索放在一封比 X『更晚』到的未來信 Y。
    回傳 (X, corpus_with_canary)。
    """
    base = max((m.received_at for m in corpus), default=datetime(2026, 1, 1, tzinfo=TZ))
    t_x = base + timedelta(hours=1)
    t_y = base + timedelta(hours=2)  # 未來信，比 X 晚
    canary_sender = "canary-sender@leaktest.invalid"
    canary_subject = "CANARY 時光機洩漏測試 業主往來999999"
    x = Mail(id="CANARY-X", received_at=t_x, from_addr=canary_sender, to_addrs=["yongxiang.ltd@gmail.com"],
             subject=canary_subject, body="業主往來999999 本封為 canary；線索只在未來信 Y。",
             category="", org_id="YX", message_id="<canary-x@leaktest.invalid>", is_canary=True)
    y = Mail(id="CANARY-Y", received_at=t_y, from_addr=canary_sender, to_addrs=["yongxiang.ltd@gmail.com"],
             subject="Re: " + canary_subject, body="業主往來999999 未來回覆（Y 比 X 晚到）。",
             category="", org_id="YX", message_id="<canary-y@leaktest.invalid>", is_canary=True)
    return x, corpus + [x, y]


def run_canary(corpus: list[Mail]) -> dict:
    x, aug = build_canary(corpus)
    result = {}
    for key, label, fn in METRICS:
        if key in ("category_reproduction", "org_attribution"):
            continue  # per-email 控制組與歷史無關，不參與洩漏測試
        _, leaky_hit = fn(x, visible_leaky(x, aug))
        _, cutoff_hit = fn(x, visible_cutoff(x, aug))
        result[key] = {"label": label, "leaky_hit": bool(leaky_hit), "cutoff_hit": bool(cutoff_hit),
                       "leak_blocked": bool(leaky_hit and not cutoff_hit)}
    # 只要有任一歷史依賴指標在 LEAKY 命中、CUTOFF 不命中，即證明 cutoff 擋住了未來資訊
    result["_canary_passed"] = any(v["leak_blocked"] for v in result.values() if isinstance(v, dict))
    return result


def build_report(corpus: list[Mail]) -> dict:
    leaky = run_metrics(corpus, visible_leaky)
    cutoff = run_metrics(corpus, visible_cutoff)
    canary = run_canary(corpus)
    deltas = {}
    for key, _label, _fn in METRICS:
        lr, cr = leaky[key]["rate"], cutoff[key]["rate"]
        deltas[key] = round((lr - cr), 4) if (lr is not None and cr is not None) else None
    dropped = [k for k, d in deltas.items() if d and d > 0]
    return {
        "generated_for": "R54 時光機評估（pre-arrival-only 路由）",
        "dsn_database": "yongxiang_plumb_r39_clone",
        "corpus_size": len(corpus),
        "rule": "router 評估每封信 m 時只讀 received_at < m.received_at；禁讀未來信與事後回填證據",
        "actual_sends": 0,
        "writes": 0,
        "metrics_leaky_forbidden": leaky,
        "metrics_cutoff_enforced": cutoff,
        "delta_leaky_minus_cutoff": deltas,
        "metrics_that_dropped_under_cutoff": dropped,
        "canary_leak_test": canary,
        "verdict": {
            "cutoff_effective": bool(dropped) and bool(canary.get("_canary_passed")),
            "note": ("有歷史依賴指標在 cutoff 後下降，且 canary 在 LEAKY 命中、CUTOFF 未命中 → cutoff 生效。"
                     if (bool(dropped) and canary.get("_canary_passed"))
                     else "指標未下降或 canary 未被擋 → 先懷疑 cutoff 未生效。"),
        },
    }


def render_md(rep: dict) -> str:
    L = ["# R54 時光機評估報表（Pre-arrival-only 路由）", "",
         f"- 語料庫：`{rep['dsn_database']}`，共 **{rep['corpus_size']}** 封（received_at 非空）",
         f"- 規則：{rep['rule']}",
         f"- 唯讀：actual_sends = **{rep['actual_sends']}**、DB writes = **{rep['writes']}**", "",
         "## 五項指標：LEAKY（舊法，含未來信）vs CUTOFF（本法，只讀歷史）", "",
         "| 指標 | 分子/分母 LEAKY | LEAKY 率 | 分子/分母 CUTOFF | CUTOFF 率 | 掉幅 |",
         "|---|---|---|---|---|---|"]
    for key, label, _fn in METRICS:
        lk, ct = rep["metrics_leaky_forbidden"][key], rep["metrics_cutoff_enforced"][key]
        delta = rep["delta_leaky_minus_cutoff"][key]
        L.append(f"| {label} | {lk['hits']}/{lk['N']} | "
                 f"{'' if lk['rate'] is None else f'{lk['rate']*100:.1f}%'} | "
                 f"{ct['hits']}/{ct['N']} | "
                 f"{'' if ct['rate'] is None else f'{ct['rate']*100:.1f}%'} | "
                 f"{'' if delta is None else f'{delta*100:.1f}pp'} |")
    L += ["", f"**cutoff 後下降的指標**：{', '.join(rep['metrics_that_dropped_under_cutoff']) or '（無）'}", "",
          "## Canary 洩漏測試（命中線索只在未來信）", "",
          "| 指標 | LEAKY 命中 | CUTOFF 命中 | 洩漏已擋 |", "|---|---|---|---|"]
    for key, v in rep["canary_leak_test"].items():
        if not isinstance(v, dict):
            continue
        L.append(f"| {v['label']} | {'✅' if v['leaky_hit'] else '—'} | "
                 f"{'✅' if v['cutoff_hit'] else '—'} | {'✅ 擋住' if v['leak_blocked'] else '—'} |")
    L += ["", f"- canary 判定：{'通過（cutoff 擋住未來資訊）' if rep['canary_leak_test'].get('_canary_passed') else '未通過'}",
          "", "## 結論", "", f"- cutoff 是否生效：**{'是' if rep['verdict']['cutoff_effective'] else '否'}**",
          f"- {rep['verdict']['note']}", ""]
    return "\n".join(L)


def main() -> int:
    dsn = os.environ.get("PG_DSN") or "postgresql://postgres:postgres@127.0.0.1:5432/yongxiang_plumb_r39_clone"
    corpus = load_corpus(dsn)
    rep = build_report(corpus)
    (ROOT / "r54_pre_arrival_eval_report.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (ROOT / "r54_pre_arrival_eval_report.md").write_text(render_md(rep), encoding="utf-8")
    print(render_md(rep))
    print(f"\n[written] r54_pre_arrival_eval_report.json / .md  (actual_sends=0, writes=0)")
    return 0 if rep["verdict"]["cutoff_effective"] else 2


if __name__ == "__main__":
    sys.exit(main())
