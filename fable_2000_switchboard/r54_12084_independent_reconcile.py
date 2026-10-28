#!/usr/bin/env python3
"""
r54_12084_independent_reconcile.py — R54 Sheet 12,084 列「獨立內容對帳」。

契約：
  * 嚴禁使用 backfill 連結（email_link / client_communication.email_message_id / serial_root）當答案。
    本檔只用三個「內容」維度，對每一列獨立重對：
      1. 日期 ±1 天
      2. 網域（counterparty → 網域對照，對上信件的外部網域）
      3. 主旨相似度（difflib，去前綴 Re:/Fw: 與空白）
    案號 case_code 作為最強的「獨立內容鍵」交叉核對（兩側皆有，且非 backfill 連結）。
  * 產出三數：對上(Matched) / 弱對(Weak) / 對不上(Unmatched)。
  * 各抽 30 列（共 90）給羅薇目檢：CSV + Markdown。
  * 把原本的「0 缺號」改報成誠實三欄：真實信(Real) / 占位(Placeholder) / 未回填(Unbackfilled)。
  * 唯讀：不寫 DB、不發信（actual_sends = 0）。

用法：
  PG_DSN=postgresql://postgres:postgres@127.0.0.1:5432/yongxiang_plumb_r39_clone \
    python r54_12084_independent_reconcile.py
輸出：r54_reconcile_12084/{summary.json,summary.md,luowei_review_sample_3x30.csv,.md}
"""
from __future__ import annotations

import csv
import difflib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
OUTDIR = ROOT / "r54_reconcile_12084"
CASE_RE = re.compile(r"([ABCMVXZ][0-9]{6}(?:-[0-9A-Z]{1,3})?)", re.I)
SUBJECT_PREFIX_RE = re.compile(r"^((re|fw|fwd|回覆|轉寄|fwd?)\s*[:：]\s*)+", re.I)

# 內部/系統網域：不作為「對上業主」的網域證據
INTERNAL_DOMAINS = {"gmail.com", "yxsurvey.com.tw", "yx.ltd", "larksuite.com",
                    "service.larksuite.com", "billing.larksuite.com", "email.claude.com"}

# counterparty（公司名片語）→ 外部網域對照（由 company_entities + 語料觀察到的網域整理）
COUNTERPARTY_DOMAIN = {
    "台灣塑膠": ["fpg.com.tw", "fpcc.com.tw"], "台塑": ["fpg.com.tw", "fpcc.com.tw"],
    "南亞": ["npc.com.tw", "fpg.com.tw"], "台化": ["fcfc.com.tw"], "麥寮": ["fpcc.com.tw"],
    "福懋": ["fpg.com.tw"], "台灣高速鐵路": ["thsrc.com.tw"], "高鐵": ["thsrc.com.tw"],
    "中華工程": ["bes.com.tw"], "中鼎": ["ctci.com"], "緯穎": ["wiwynn.com"],
    "華新麗華": ["walsin.com"], "經濟部水利署": ["wra.gov.tw", "water.gov.tw"],
    "水利署": ["wra.gov.tw", "water.gov.tw"], "台灣電力": ["taipower.com.tw"], "台電": ["taipower.com.tw"],
    "民航局": ["caa.gov.tw"], "交通部": ["motc.gov.tw"],
}


def norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or "")).lower()


def subject_root(s: str) -> str:
    return norm(SUBJECT_PREFIX_RE.sub("", s or ""))


def case_codes(text: str) -> set[str]:
    return {m.upper() for m in CASE_RE.findall(text or "")}


def counterparty_domains(counterparty: str) -> list[str]:
    cp = counterparty or ""
    out: list[str] = []
    for key, doms in COUNTERPARTY_DOMAIN.items():
        if key in cp:
            out.extend(doms)
    return out


@dataclass
class Email:
    id: str
    dt: Optional[date]
    domains: set[str]
    cases: set[str]
    subj_root: str
    subject: str


@dataclass
class SheetRow:
    row_no: int
    serial_no: Optional[int]
    direction: str
    dt: Optional[date]
    counterparty: str
    subject: str
    case_code: str
    problems: list
    row_hash: str


def _parse_date(v) -> Optional[date]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(str(v)[:10], fmt).date()
            except ValueError:
                continue
    return None


def load_data(dsn: str) -> tuple[list[SheetRow], list[Email]]:
    import psycopg
    sheet: list[SheetRow] = []
    emails: list[Email] = []
    with psycopg.connect(dsn) as conn:
        for (payload, row_hash) in conn.execute(
                "SELECT payload, row_hash FROM backfill_sheet_row "
                "WHERE payload->>'direction' IN ('inbound','outbound')").fetchall():
            p = payload
            sheet.append(SheetRow(
                row_no=int(p.get("row_no") or 0),
                serial_no=(int(p["serial_no"]) if str(p.get("serial_no") or "").lstrip("-").isdigit() else None),
                direction=p.get("direction") or "",
                dt=_parse_date(p.get("date")),
                counterparty=p.get("counterparty") or "",
                subject=p.get("subject") or "",
                case_code=(p.get("case_code") or "").upper(),
                problems=list(p.get("problems") or []),
                row_hash=row_hash,
            ))
        for (eid, recv, from_addr, to_addrs, subject, body) in conn.execute(
                "SELECT id::text, received_at, from_addr, coalesce(to_addrs,'{}'), "
                "coalesce(subject,''), coalesce(body_new_text,body_text,'') FROM email_message").fetchall():
            doms = set()
            for a in [from_addr] + list(to_addrs or []):
                a = (a or "").strip().lower()
                if "@" in a:
                    d = a.split("@")[-1].strip("<>")
                    if d and d not in INTERNAL_DOMAINS:
                        doms.add(d)
            emails.append(Email(
                id=eid, dt=(recv.date() if recv else None), domains=doms,
                cases=case_codes(subject + " " + body), subj_root=subject_root(subject), subject=subject,
            ))
    return sheet, emails


# ---------------------------------------------------------------------------
# 獨立對帳：每列對 email 以 日期±1 / 網域 / 主旨相似度（+ case_code 內容鍵）評分
# ---------------------------------------------------------------------------
@dataclass
class Reconciled:
    row: SheetRow
    status: str                      # 'Matched' | 'Weak' | 'Unmatched'
    best_email_id: Optional[str]
    case_hit: bool
    domain_hit: bool
    subj_sim: float
    evidence: str


def reconcile_row(r: SheetRow, emails_by_day: dict) -> Reconciled:
    if r.dt is None:
        return Reconciled(r, "Unmatched", None, False, False, 0.0, "sheet 無可解析日期")
    cp_doms = set(counterparty_domains(r.counterparty))
    r_subj = subject_root(r.subject)
    best = None
    best_key = (0, 0, 0.0)   # (case_hit, domain_hit, subj_sim)
    for delta in (-1, 0, 1):
        for e in emails_by_day.get(r.dt + timedelta(days=delta), ()):
            case_hit = bool(r.case_code and r.case_code in e.cases)
            domain_hit = bool(cp_doms and (cp_doms & e.domains))
            sim = difflib.SequenceMatcher(None, r_subj, e.subj_root).ratio() if r_subj and e.subj_root else 0.0
            key = (int(case_hit), int(domain_hit), round(sim, 4))
            if key > best_key:
                best_key, best = key, (e, case_hit, domain_hit, sim)
    if best is None:
        return Reconciled(r, "Unmatched", None, False, False, 0.0, "日期±1 內無任何信件")
    e, case_hit, domain_hit, sim = best
    # 分級
    strong = (case_hit and (domain_hit or sim >= 0.50)) or (domain_hit and sim >= 0.60)
    weak = case_hit or domain_hit or sim >= 0.45
    status = "Matched" if strong else ("Weak" if weak else "Unmatched")
    ev = []
    if case_hit:
        ev.append(f"case={r.case_code}")
    if domain_hit:
        ev.append("domain✓")
    ev.append(f"subj_sim={sim:.2f}")
    return Reconciled(r, status, e.id, case_hit, domain_hit, round(sim, 4), " ".join(ev))


# ---------------------------------------------------------------------------
# 誠實三欄：真實信 / 占位 / 未回填（取代「0 缺號」）
# ---------------------------------------------------------------------------
GENERIC_CP = {"永祥合作業主", "合作業主", ""}
PLACEHOLDER_SUBJ = {"前案", "重號測試", "格式錯", ""}


def is_placeholder(r: SheetRow) -> bool:
    if r.problems:
        return True
    if "行政登記摘要（待人工複核）" in (r.subject or ""):
        return True
    if (r.counterparty or "").strip() in GENERIC_CP:
        return True
    if (r.subject or "").strip() in PLACEHOLDER_SUBJ:
        return True
    if re.match(r"^業主往來\s*\d+", (r.counterparty or "").strip()):
        return True
    return False


def honest_bucket(rec: Reconciled) -> str:
    if is_placeholder(rec.row):
        return "Placeholder"              # 占位：樣板/泛業主/問題列，非真實往來
    if rec.status in ("Matched", "Weak"):
        return "Real"                     # 真實信：對上了真的匯入信件
    return "Unbackfilled"                 # 未回填：像真往來但語料尚無對應信件


def main() -> int:
    dsn = os.environ.get("PG_DSN") or "postgresql://postgres:postgres@127.0.0.1:5432/yongxiang_plumb_r39_clone"
    sheet, emails = load_data(dsn)
    emails_by_day: dict[date, list[Email]] = {}
    for e in emails:
        if e.dt:
            emails_by_day.setdefault(e.dt, []).append(e)

    recs = [reconcile_row(r, emails_by_day) for r in sheet]
    match_counts = {"Matched": 0, "Weak": 0, "Unmatched": 0}
    honest_counts = {"Real": 0, "Placeholder": 0, "Unbackfilled": 0}
    for rec in recs:
        match_counts[rec.status] += 1
        honest_counts[honest_bucket(rec)] += 1

    OUTDIR.mkdir(exist_ok=True)

    # 3×30 樣本（各狀態抽前 30，確定性：依 row_no 排序）。
    # 誠實註記：若某狀態不足 30 列（例如語料稀疏下 Matched 很少），就抽到有幾列算幾列，不灌水。
    samples: list[tuple[str, Reconciled]] = []
    sample_sizes: dict[str, int] = {}
    for status in ("Matched", "Weak", "Unmatched"):
        picked = sorted((x for x in recs if x.status == status),
                        key=lambda x: (x.row.row_no, x.row.row_hash))[:30]
        sample_sizes[status] = len(picked)
        samples += [(status, x) for x in picked]

    csv_path = OUTDIR / "luowei_review_sample_3x30.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["對帳狀態", "誠實分欄", "row_no", "序號", "方向", "日期", "業主", "主旨",
                    "案號", "對上信件id", "case命中", "網域命中", "主旨相似度", "證據"])
        for status, x in samples:
            r = x.row
            w.writerow([status, honest_bucket(x), r.row_no, r.serial_no or "", r.direction,
                        r.dt.isoformat() if r.dt else "", r.counterparty, r.subject, r.case_code,
                        x.best_email_id or "", "Y" if x.case_hit else "", "Y" if x.domain_hit else "",
                        f"{x.subj_sim:.2f}", x.evidence])

    md_sample = ["# 羅薇目檢清單：獨立對帳 3×30 抽樣（共 90 列）", "",
                 "每個狀態抽 30 列（依 row_no 排序，確定性）。請目檢「對上信件」是否真為同一封往來。", ""]
    for status in ("Matched", "Weak", "Unmatched"):
        md_sample += [f"## {status}", "",
                      "| row_no | 方向 | 日期 | 業主 | 主旨 | 案號 | 信件id | 證據 |",
                      "|---|---|---|---|---|---|---|---|"]
        for s, x in samples:
            if s != status:
                continue
            r = x.row
            subj = (r.subject or "").replace("|", "／")[:40]
            cp = (r.counterparty or "").replace("|", "／")[:16]
            md_sample.append(f"| {r.row_no} | {r.direction} | {r.dt or ''} | {cp} | {subj} | "
                             f"{r.case_code} | {(x.best_email_id or '')[:8]} | {x.evidence} |")
        md_sample.append("")
    (OUTDIR / "luowei_review_sample_3x30.md").write_text("\n".join(md_sample), encoding="utf-8")

    total = len(sheet)
    summary = {
        "generated_for": "R54 Sheet 12,084 列獨立內容對帳",
        "dsn_database": "yongxiang_plumb_r39_clone",
        "sheet_rows_with_direction": total,
        "emails_in_corpus": len(emails),
        "method": {
            "independent_dimensions": ["日期 ±1 天", "網域（counterparty→domain 對照）", "主旨相似度(difflib)"],
            "content_key": "case_code（兩側皆有，非 backfill 連結）",
            "forbidden": "不使用 email_link / client_communication.email_message_id / serial_root 作為答案",
            "thresholds": {"strong": "case&(domain|sim>=.50) 或 (domain&sim>=.60)",
                           "weak": "case 或 domain 或 sim>=.45"},
        },
        "match_counts": match_counts,
        "match_pct": {k: round(v / total * 100, 2) for k, v in match_counts.items()},
        "honest_three_columns_replacing_zero_gap": {
            "note": "原報『0 缺號』不誠實；改報三欄分配（總和 = 12,084）",
            "真實信_Real": honest_counts["Real"],
            "占位_Placeholder": honest_counts["Placeholder"],
            "未回填_Unbackfilled": honest_counts["Unbackfilled"],
        },
        "samples": {"path_csv": str(csv_path.relative_to(ROOT)),
                    "path_md": "r54_reconcile_12084/luowei_review_sample_3x30.md",
                    "target_per_status": 30, "actual_per_status": sample_sizes, "total": len(samples),
                    "note": ("理想各抽 30 列（共 90）；實際 Matched 僅 %d 列（語料稀疏），"
                             "故抽到有幾列算幾列、不灌水。" % sample_sizes["Matched"])},
        "actual_sends": 0,
        "writes": 0,
    }
    assert sum(match_counts.values()) == total
    assert sum(honest_counts.values()) == total
    (OUTDIR / "r54_reconcile_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# R54 Sheet 12,084 列 獨立內容對帳報表", "",
          f"- 來源 DB：`{summary['dsn_database']}`；Sheet 具方向列 **{total:,}**；語料信件 **{len(emails)}** 封",
          f"- 獨立維度：{'、'.join(summary['method']['independent_dimensions'])}；內容鍵：{summary['method']['content_key']}",
          f"- 禁用：{summary['method']['forbidden']}",
          f"- 唯讀：actual_sends = **0**、DB writes = **0**", "",
          "## 三數：對上 / 弱對 / 對不上", "",
          "| 狀態 | 列數 | 佔比 |", "|---|---|---|",
          f"| 對上 Matched | {match_counts['Matched']:,} | {summary['match_pct']['Matched']}% |",
          f"| 弱對 Weak | {match_counts['Weak']:,} | {summary['match_pct']['Weak']}% |",
          f"| 對不上 Unmatched | {match_counts['Unmatched']:,} | {summary['match_pct']['Unmatched']}% |",
          f"| **合計** | **{total:,}** | 100% |", "",
          "## 誠實三欄（取代原本不實的「0 缺號」）", "",
          "原始對外說法「0 缺號」把占位列與未回填列都當成已對帳，並不誠實。改報如下三欄（總和 = 12,084）：", "",
          "| 欄位 | 定義 | 列數 |", "|---|---|---|",
          f"| 真實信 Real | 非占位，且獨立對上一封真實匯入信件 | {honest_counts['Real']:,} |",
          f"| 占位 Placeholder | 樣板「行政登記摘要（待人工複核）」／泛業主／問題列 | {honest_counts['Placeholder']:,} |",
          f"| 未回填 Unbackfilled | 像真實往來，但語料尚無對應信件可對 | {honest_counts['Unbackfilled']:,} |",
          f"| **合計** | | **{total:,}** |", "",
          "## 給羅薇的目檢清單", "",
          f"- CSV：`{summary['samples']['path_csv']}`（目標各狀態 30 列／共 90；"
          f"實際 Matched {sample_sizes['Matched']}、Weak {sample_sizes['Weak']}、"
          f"Unmatched {sample_sizes['Unmatched']}，共 {len(samples)} 列，不灌水）",
          f"- Markdown：`{summary['samples']['path_md']}`", "",
          "> 語料僅 283 封、多數 Sheet 列落在未匯入期間，故「對上」比例低屬預期；",
          "> 重點是把『0 缺號』如實拆成 真實信／占位／未回填，讓未回填的缺口可被追。", ""]
    (OUTDIR / "r54_reconcile_summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\n[written] {OUTDIR}/  (summary.json/.md, luowei_review_sample_3x30.csv/.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
