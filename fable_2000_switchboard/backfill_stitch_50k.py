#!/usr/bin/env python3
"""
backfill_stitch_50k.py — 50,578 封 .eml/MIME ＋ 12,084 列《業主往來紀錄表》→ email_message / email_thread /
email_link / client_communication 的歷史縫合批次。

原則（R29 / R29-PSTACK）：
  * 純解析在 switchboard_engine（零副作用）；本檔只負責讀檔、讀 Sheet CSV、寫 DB。
  * 原文 append-only；重跑冪等（以 message_id、sheet_row_hash、(message_id, original_message_id) 為鍵）。
  * 任何對不上的東西進 `backfill_quarantine`，不丟、不猜、不自動配新號；新序號只由 serial_allocator 發（本腳本從不發號）。
  * 三條縫合規則依序：references → serial_no → 72h 內引用區雜湊；信心寫在列上。

用法：
  python -I backfill_stitch_50k.py --eml-dir /data/eml --sheet-csv /data/sheet.csv --dsn "$PG_DSN" --org YX --dry-run
  python -I backfill_stitch_50k.py ... --apply --batch-size 500
前置 DDL：R29 §4（email_mailbox/email_message/email_thread/email_link/email_attachment/client_communication/org）。
"""
from __future__ import annotations

import argparse
import csv
import email
import email.policy
import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional

# 解析器：純函數模組，與線上同一份
sys.path.insert(0, str(Path(__file__).resolve().parent))
from switchboard_engine import (  # noqa: E402
    SATELLITES, SWITCHBOARD_ADDR, INTERNAL_MAILBOXES, normalize, sha256_text, loose_hash, strip_quoted_chain,
    parse_satellite_command, classify_inbound_email, EMAIL_RE,
)

TZ = timezone(timedelta(hours=8))
SHEET_SERIAL_RE = re.compile(r"(?:業主往來)?\s*0*(\d{1,6})")
QUOTED_BLOCK_RE = re.compile(r"(?:-{3,}\s*Original Message\s*-{3,}|-{5,}\s*Forwarded message\s*-{5,}|On .+?wrote:|寄件者\s*[:：])", re.M)


# ---------------------------------------------------------------------------
# 資料結構
# ---------------------------------------------------------------------------
@dataclass
class ParsedMail:
    message_id: str
    in_reply_to: Optional[str]
    references: list[str]
    from_addr: str
    to_addrs: list[str]
    cc_addrs: list[str]
    subject: str
    sent_at: datetime
    raw_path: str
    body_new_text: str              # 去引用鏈後的新內容（原文標點）
    body_hash: str                  # 新內容雜湊（正規化後）
    body_loose_hash: str            # 新內容去空白雜湊（縫合用）
    quoted_hash: Optional[str]      # 引用區去空白雜湊（縫合用）
    labels: list[str]
    attachments: list[dict]
    is_internal_command: bool
    serial_ref: Optional[int]
    category: str
    org_id: str
    injection_suspect: bool
    quarantine_reason: Optional[str]


@dataclass
class SheetRow:
    row_no: int
    serial_no: Optional[int]
    raw_serial: str
    date: Optional[datetime]
    counterparty: str
    subject: str
    handler: str
    note: str
    row_hash: str
    problems: list[str]


# ---------------------------------------------------------------------------
# .eml 解析（I/O 在此層；內容判斷呼叫 engine）
# ---------------------------------------------------------------------------
def _addrs(msg, header: str) -> list[str]:
    vals = msg.get_all(header, []) or []
    out: list[str] = []
    for v in vals:
        out += [a.lower() for a in EMAIL_RE.findall(str(v))]
    return out


def _body_text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and not part.get_filename():
                try:
                    return part.get_content()
                except Exception:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html" and not part.get_filename():
                html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                return re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", "", html))
        return ""
    try:
        return msg.get_content()
    except Exception:
        return (msg.get_payload(decode=True) or b"").decode(msg.get_content_charset() or "utf-8", "replace")


def _attachments(msg) -> list[dict]:
    out = []
    for part in msg.walk():
        fn = part.get_filename()
        if not fn:
            continue
        data = part.get_payload(decode=True) or b""
        out.append({"filename": fn, "mime": part.get_content_type(), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    return out


def _quoted_hash(raw_text: str) -> Optional[str]:
    """引用區（第一個切點之後）的去空白雜湊：用來把『總機轉寄給衛星』縫回原信。"""
    n = normalize(raw_text)
    m = QUOTED_BLOCK_RE.search(n)
    if not m:
        return None
    quoted = n[m.end():]
    # 去掉引用區開頭的標頭行（From:/To:/Subject:/Date: 或中文對應），只留正文
    quoted = re.sub(r"^\s*(From|To|Cc|Subject|Date|Sent|寄件者|收件者|主旨|日期|寄件日期)\s*[:：].*$", "", quoted, flags=re.M | re.I)
    body_only = re.sub(r"\s+", "", re.sub(r"^\s*>\s?", "", quoted, flags=re.M))
    return loose_hash(quoted) if len(body_only) > 20 else None


def parse_eml(path: Path, labels_index: dict[str, list[str]]) -> ParsedMail:
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=email.policy.default)
    mid = (msg.get("Message-ID") or "").strip() or f"<synthetic-{hashlib.sha1(path.read_bytes()).hexdigest()}@backfill>"
    refs = [r.strip() for r in re.findall(r"<[^>]+>", msg.get("References", "") or "")]
    irt = (msg.get("In-Reply-To") or "").strip() or None
    from_addr = (_addrs(msg, "From") or [""])[0]
    try:
        sent_at = parsedate_to_datetime(msg.get("Date")).astimezone(TZ)
    except Exception:
        sent_at = datetime.fromtimestamp(path.stat().st_mtime, TZ)
    raw_text = _body_text(msg)
    subject = str(msg.get("Subject") or "")
    new_text = strip_quoted_chain(raw_text)
    cmd = parse_satellite_command(from_addr, subject, raw_text)
    cls = classify_inbound_email(from_addr, _addrs(msg, "To"), subject, new_text,
                                 dkim_pass=_auth_results(msg, "dkim"), spf_pass=_auth_results(msg, "spf"),
                                 dkim_domain=_dkim_domain(msg))
    serial = cmd.serial_ref or cls.serial_ref
    return ParsedMail(
        message_id=mid, in_reply_to=irt, references=refs, from_addr=from_addr,
        to_addrs=_addrs(msg, "To"), cc_addrs=_addrs(msg, "Cc"), subject=subject, sent_at=sent_at, raw_path=str(path),
        body_new_text=cmd.clean_body if cmd.is_internal_address else new_text,
        body_hash=sha256_text(cmd.clean_body if cmd.is_internal_address else new_text),
        body_loose_hash=loose_hash(cmd.clean_body if cmd.is_internal_address else new_text),
        quoted_hash=_quoted_hash(raw_text), labels=labels_index.get(mid, []), attachments=_attachments(msg),
        is_internal_command=from_addr in SATELLITES and cmd.command_kind != "none",
        serial_ref=serial, category=cls.category, org_id=cls.org_id,
        injection_suspect=cls.injection_suspect, quarantine_reason=cls.quarantine_reason,
    )


def _auth_results(msg, mech: str) -> bool:
    ar = " ".join(msg.get_all("Authentication-Results", []) or [])
    return bool(re.search(rf"{mech}=pass", ar, re.I))


def _dkim_domain(msg) -> Optional[str]:
    ar = " ".join(msg.get_all("Authentication-Results", []) or [])
    m = re.search(r"dkim=pass[^;]*header\.(?:d|i)=@?([\w.-]+)", ar, re.I)
    return m.group(1).lower() if m else None


def iter_eml(root: Path) -> Iterator[Path]:
    for p in sorted(root.rglob("*.eml")):
        yield p


def load_labels_index(path: Optional[Path]) -> dict[str, list[str]]:
    """Gmail 標籤匯出（JSON: {message_id: [labels]}），可選。"""
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Sheet 解析：重號、空號、格式錯全部標記，不修
# ---------------------------------------------------------------------------
SHEET_COLS = {"serial": ("業主往來編號", "編號", "序號"), "date": ("日期",), "counterparty": ("業主", "對象", "單位"),
              "subject": ("主旨", "事項"), "handler": ("承辦", "負責", "PM"), "note": ("備註", "說明")}


def _col(row: dict, keys: tuple[str, ...]) -> str:
    for k in row:
        if any(key in k for key in keys):
            return (row[k] or "").strip()
    return ""


def load_sheet(path: Path) -> list[SheetRow]:
    rows: list[SheetRow] = []
    seen: dict[int, int] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            raw_serial = _col(r, SHEET_COLS["serial"])
            m = SHEET_SERIAL_RE.fullmatch(raw_serial.strip()) if raw_serial else None
            serial = int(m.group(1)) if m else None
            probs: list[str] = []
            if serial is None:
                probs.append("serial_unparseable")
            elif serial in seen:
                probs.append(f"duplicate_serial_of_row_{seen[serial]}")
            else:
                seen[serial] = i
            d_raw = _col(r, SHEET_COLS["date"])
            d = None
            for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%m/%d/%Y"):
                try:
                    d = datetime.strptime(d_raw, fmt).replace(tzinfo=TZ)
                    break
                except ValueError:
                    continue
            if d is None:
                probs.append("date_unparseable")
            payload = "|".join([raw_serial, d_raw, _col(r, SHEET_COLS["counterparty"]), _col(r, SHEET_COLS["subject"])])
            rows.append(SheetRow(i, serial, raw_serial, d, _col(r, SHEET_COLS["counterparty"]), _col(r, SHEET_COLS["subject"]),
                                 _col(r, SHEET_COLS["handler"]), _col(r, SHEET_COLS["note"]),
                                 hashlib.sha256(payload.encode()).hexdigest(), probs))
    # 空號：序號連續性
    serials = sorted(seen)
    if serials:
        missing = sorted(set(range(serials[0], serials[-1] + 1)) - set(serials))
        for s in missing:
            rows.append(SheetRow(-1, s, str(s), None, "", "", "", "", hashlib.sha256(f"gap:{s}".encode()).hexdigest(), ["serial_gap"]))
    return rows


# ---------------------------------------------------------------------------
# 縫合（純邏輯；輸入是已解析的清單，輸出是連結與隔離清單）
# ---------------------------------------------------------------------------
@dataclass
class Link:
    message_id: str
    original_message_id: str
    rule: str
    confidence: float


def _stitch_one_org(mails: list[ParsedMail], sheet: list[SheetRow]) -> tuple[list[Link], dict[int, list[str]], dict[int, str], list[dict]]:
    """回傳 (links, serial_members, serial_root, quarantine)；serial_root[serial] = 該序號的業主原信 message_id。"""
    by_mid = {m.message_id: m for m in mails}
    by_hash: dict[str, list[ParsedMail]] = {}
    for m in mails:
        by_hash.setdefault(m.body_loose_hash, []).append(m)
    by_serial_mail: dict[int, list[ParsedMail]] = {}
    for m in mails:
        if m.serial_ref and m.from_addr in INTERNAL_MAILBOXES:          # 序號只信內部信箱寫的
            by_serial_mail.setdefault(m.serial_ref, []).append(m)
    duplicate_serials = {r.serial_no for r in sheet if any(p.startswith("duplicate") for p in r.problems)}
    sheet_by_serial = {r.serial_no: r for r in sheet if r.serial_no is not None and not r.problems and r.serial_no not in duplicate_serials}

    links: list[Link] = []
    serial_members: dict[int, list[str]] = {}
    serial_root: dict[int, str] = {}
    quarantine: list[dict] = []

    for m in mails:
        # 規則 1：References / In-Reply-To
        root = None
        for ref in m.references:
            if ref in by_mid and by_mid[ref].org_id == m.org_id:
                root = ref
                break
        if root is None and m.in_reply_to in by_mid and by_mid[m.in_reply_to].org_id == m.org_id:
            root = m.in_reply_to
        if root and root != m.message_id:
            links.append(Link(m.message_id, root, "references", 1.0))
        # 規則 2：業主往來序號（總機轉寄首行／主旨）——只信內部信箱；外部信自稱序號＝注入嫌疑，進隔離
        if m.serial_ref and m.from_addr in INTERNAL_MAILBOXES:
            serial_members.setdefault(m.serial_ref, []).append(m.message_id)
            if m.serial_ref not in sheet_by_serial:
                quarantine.append({"kind": "serial_not_in_sheet", "message_id": m.message_id, "serial": m.serial_ref})
        elif m.serial_ref:
            quarantine.append({"kind": "external_serial_claim", "message_id": m.message_id, "serial": m.serial_ref, "from": m.from_addr})
        # 規則 3：72h 內引用區雜湊 ＝ 某封原信的新內容雜湊
        if m.quoted_hash and m.quoted_hash in by_hash:
            cands = [o for o in by_hash[m.quoted_hash] if o.message_id != m.message_id and o.org_id == m.org_id and 0 <= (m.sent_at - o.sent_at).total_seconds() and abs((m.sent_at - o.sent_at).total_seconds()) <= 72 * 3600]
            if len(cands) == 1:
                links.append(Link(m.message_id, cands[0].message_id, "quoted_hash", 0.9))
            elif len(cands) > 1:
                quarantine.append({"kind": "quoted_hash_ambiguous", "message_id": m.message_id, "candidates": [c.message_id for c in cands]})

    # 規則 2b：同序號的轉寄／回覆都連到該序號最早的業主原信；多封原信（CC 多人、重複轉寄）進隔離，絕不配第二個號
    linked = {(l.message_id, l.original_message_id) for l in links}
    for serial, mids in serial_members.items():
        originals = sorted((by_mid[mid] for mid in mids if by_mid[mid].from_addr not in INTERNAL_MAILBOXES), key=lambda x: x.sent_at)
        if len(originals) > 1:
            quarantine.append({"kind": "serial_multiple_originals", "serial": serial, "message_ids": [o.message_id for o in originals]})
        if not originals:
            # 序號只出現在轉寄信（常態：總機轉寄時才寫序號）：原信＝轉寄信經規則 1/3 連到的目標
            targets = [l.original_message_id for l in links if l.message_id in mids]
            if targets:
                roots = set(targets)
                # Follow reference/hash links transitively; ambiguous roots stay quarantined.
                for _ in range(len(mails)):
                    expanded={l.original_message_id for l in links if l.message_id in roots}
                    new=(roots-{l.message_id for l in links if l.message_id in roots})|expanded
                    if new==roots: break
                    roots=new
                if len(roots)!=1:
                    quarantine.append({"kind":"serial_multiple_originals","serial":serial,"message_ids":sorted(roots)})
                    continue
                serial_root[serial] = next(iter(roots))
                for mid in mids:
                    pair=(mid,serial_root[serial])
                    if mid != serial_root[serial] and pair not in linked:
                        links.append(Link(*pair,"serial_no",0.95)); linked.add(pair)
            else:
                quarantine.append({"kind": "serial_without_original", "serial": serial, "message_ids": mids})
            continue
        root = originals[0].message_id
        serial_root[serial] = root
        for mid in mids:
            if mid != root and (mid, root) not in linked:
                links.append(Link(mid, root, "serial_no", 0.95))
                linked.add((mid, root))
    # Sheet 側問題
    for r in sheet:
        for p in r.problems:
            quarantine.append({"kind": f"sheet_{p}", "row_no": r.row_no, "serial": r.serial_no})
        if r.serial_no and r.serial_no not in by_serial_mail and "serial_gap" not in r.problems:
            quarantine.append({"kind": "sheet_serial_without_mail", "row_no": r.row_no, "serial": r.serial_no})
    return links, serial_members, serial_root, quarantine


def stitch(mails, sheet, org_id='YX'):
    """Serial numbers are scoped to an organization, never shared across organizations."""
    links=[];members={};roots={};quarantine=[]
    organizations=sorted({m.org_id for m in mails}|{org_id})
    for org in organizations:
        result=_stitch_one_org([m for m in mails if m.org_id==org],sheet if org==org_id else [])
        links.extend(result[0])
        if org==org_id:members.update(result[1]);roots.update(result[2])
        quarantine.extend({**q,'org_id':org} for q in result[3])
    return links,members,roots,quarantine


# ---------------------------------------------------------------------------
# DB 寫入（唯一的副作用層；全部 ON CONFLICT 冪等）
# ---------------------------------------------------------------------------
DDL_QUARANTINE = """
CREATE TABLE IF NOT EXISTS backfill_quarantine (
  id bigserial PRIMARY KEY, run_id uuid NOT NULL, kind text NOT NULL, payload jsonb NOT NULL,
  resolved_by uuid, resolved_at timestamptz, UNIQUE (kind, payload));
CREATE TABLE IF NOT EXISTS backfill_run (
  id uuid PRIMARY KEY, started_at timestamptz DEFAULT now(), finished_at timestamptz, args jsonb,
  mails_seen int, mails_inserted int, links_inserted int, comms_inserted int, quarantined int);
CREATE TABLE IF NOT EXISTS backfill_sheet_row (
 org_id text NOT NULL REFERENCES org(id),row_hash text NOT NULL,payload jsonb NOT NULL,PRIMARY KEY(org_id,row_hash));
"""


def write_db(dsn, org_id, mails, sheet, links, serial_members, serial_root, quarantine, batch_size, apply):
    run_id = uuid.uuid4()
    stats = {"run_id":str(run_id),"mails_seen":len(mails),"mails_inserted":0,"links_inserted":0,"comms_inserted":0,"quarantined":len(quarantine)}
    if not apply:
        return stats
    import psycopg
    from psycopg.types.json import Jsonb
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(1943,12090)")
        conn.execute(DDL_QUARANTINE)
        if not conn.execute("SELECT 1 FROM org WHERE id=%s",(org_id,)).fetchone():
            raise ValueError('unknown org')
        conn.execute("INSERT INTO backfill_run(id,args,mails_seen) VALUES(%s,%s,%s)",(run_id,Jsonb({"apply":True,"org":org_id}),len(mails)))
        mailbox=conn.execute("SELECT id FROM email_mailbox WHERE address=%s",(SWITCHBOARD_ADDR,)).fetchone()[0]
        ids={}
        # Plan thread IDs before append-only message insertion.
        parent={m.message_id:m.message_id for m in mails}
        def find(mid):
            while parent[mid]!=mid:
                parent[mid]=parent[parent[mid]];mid=parent[mid]
            return mid
        for link in links: parent[find(link.message_id)]=find(link.original_message_id)
        by_mid={m.message_id:m for m in mails};groups={}
        for mid in parent: groups.setdefault(find(mid),[]).append(mid)
        planned_threads={}; thread_roots={}
        for members in groups.values():
            root=min(members,key=lambda mid:(by_mid[mid].sent_at,mid)); org=by_mid[root].org_id
            existing=conn.execute('SELECT t.id FROM email_thread t JOIN email_message m ON m.id=t.root_message_id WHERE t.org_id=%s AND m.message_id=%s',(org,root)).fetchone()
            tid=existing[0] if existing else uuid.uuid5(uuid.NAMESPACE_URL,org+':email-thread:'+root)
            thread_roots[root]=tid
            for mid in members: planned_threads[mid]=tid
        for m in mails:
            if m.org_id not in ('YX','SJ'):
                raise ValueError('ambiguous organization requires manual quarantine before apply')
            row=conn.execute('INSERT INTO email_message(mailbox_id,message_id,in_reply_to,"references",from_addr,to_addrs,cc_addrs,subject,sent_at,raw_mime_path,body_new_text,body_hash,labels,is_internal_command,category,org_id,thread_id)\n              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(message_id) DO NOTHING RETURNING id',
              (mailbox,m.message_id,m.in_reply_to,m.references,m.from_addr,m.to_addrs,m.cc_addrs,m.subject,m.sent_at,m.raw_path,m.body_new_text,m.body_hash,m.labels,m.is_internal_command,m.category if m.category.startswith('CAT-') else None,m.org_id,planned_threads[m.message_id])).fetchone()
            stats['mails_inserted']+=int(row is not None)
            existing=conn.execute('SELECT id,org_id,body_hash FROM email_message WHERE message_id=%s',(m.message_id,)).fetchone()
            if existing[1]!=m.org_id or existing[2]!=m.body_hash:
                raise ValueError('message-id collision with different org or content')
            ids[m.message_id]=existing[0]
            for a in m.attachments:
                conn.execute('INSERT INTO email_attachment(message_id,filename,mime,sha256,bytes,org_id) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(existing[0],a['filename'],a['mime'],a['sha256'],a['bytes'],m.org_id))
        for link in links:
            if link.message_id not in ids or link.original_message_id not in ids:
                raise ValueError('link points outside imported messages')
            cur=conn.execute('INSERT INTO email_link(message_id,original_message_id,link_rule,confidence) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',
              (ids[link.message_id],ids[link.original_message_id],link.rule,link.confidence))
            stats['links_inserted']+=cur.rowcount
        for root,tid in thread_roots.items():
            conn.execute('INSERT INTO email_thread(id,root_message_id,org_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(tid,ids[root],by_mid[root].org_id))
        duplicates={r.serial_no for r in sheet if any(p.startswith('duplicate') for p in r.problems)}
        for r in sheet:
            payload=asdict(r);payload['date']=r.date.isoformat() if r.date else None
            conn.execute('INSERT INTO backfill_sheet_row(org_id,row_hash,payload) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(org_id,r.row_hash,Jsonb(payload)))
            if r.serial_no is None or r.problems or r.serial_no in duplicates:
                continue
            root=serial_root.get(r.serial_no)
            if root and by_mid[root].org_id!=org_id:
                quarantine.append({'kind':'sheet_org_mismatch','serial':r.serial_no,'message_id':root})
                continue
            cust=conn.execute('SELECT id FROM customer WHERE org_id=%s AND (norm_name=%s OR name=%s)',(org_id,normalize(r.counterparty),r.counterparty)).fetchall()
            customer=cust[0][0] if len(cust)==1 else None
            if customer is None:
                quarantine.append({'kind':'sheet_customer_unresolved','serial':r.serial_no,'sheet_row_hash':r.row_hash})
                continue
            # Historical author unknown: leave unresolved rather than inventing an employee.
            if not r.handler:
                quarantine.append({'kind':'sheet_employee_unresolved','serial':r.serial_no,'sheet_row_hash':r.row_hash})
                continue
            handlers=conn.execute('SELECT employee_id FROM employee_alias WHERE org_id=%s AND alias=%s',(org_id,normalize(r.handler))).fetchall()
            if len(handlers)!=1:
                quarantine.append({'kind':'sheet_employee_unresolved','serial':r.serial_no,'sheet_row_hash':r.row_hash})
                continue
            cur=conn.execute("INSERT INTO client_communication(direction,channel,occurred_at,customer_id,our_employee_id,body_text,summary_120,extracted_by,org_id,serial_no,thread_fingerprint,email_message_id) VALUES('inbound','email',%s,%s,%s,%s,%s,'human',%s,%s,%s,%s) ON CONFLICT DO NOTHING",
              (r.date,customer,handlers[0][0],r.subject or '(sheet row)',(r.note or r.subject)[:120],org_id,r.serial_no,'serial:'+str(r.serial_no),ids.get(root)))
            stats['comms_inserted']+=cur.rowcount
            if cur.rowcount==0:
                existing=conn.execute('SELECT thread_fingerprint,email_message_id FROM client_communication WHERE org_id=%s AND serial_no=%s',(org_id,r.serial_no)).fetchone()
                if not existing or existing[0]!='serial:'+str(r.serial_no) or (existing[1] is not None and existing[1]!=ids.get(root)):
                    quarantine.append({'kind':'serial_database_conflict','serial':r.serial_no,'sheet_row_hash':r.row_hash})
        for q in quarantine:
            conn.execute('INSERT INTO backfill_quarantine(run_id,kind,payload) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(run_id,q['kind'],Jsonb(q)))
        stats['quarantined']=len(quarantine)
        conn.execute('UPDATE backfill_run SET finished_at=now(),mails_inserted=%s,links_inserted=%s,comms_inserted=%s,quarantined=%s WHERE id=%s',
           (stats['mails_inserted'],stats['links_inserted'],stats['comms_inserted'],stats['quarantined'],run_id))
    return stats


# ---------------------------------------------------------------------------
# 驗收斷言（apply 後跑；任何一條不過就不算完成）
# ---------------------------------------------------------------------------
ASSERTIONS = [
    ("mails_in_db_eq_files", "SELECT count(*) FROM email_message WHERE raw_mime_path LIKE %s || '%%'", "eq_param"),
    ("no_message_id_dup", "SELECT count(*) FROM (SELECT message_id FROM email_message GROUP BY 1 HAVING count(*)>1) d", 0),
    ("every_link_targets_existing", "SELECT count(*) FROM email_link l LEFT JOIN email_message m ON m.id=l.original_message_id WHERE m.id IS NULL", 0),
    ("serial_unique_per_org", "SELECT count(*) FROM (SELECT org_id, serial_no FROM client_communication WHERE serial_no IS NOT NULL GROUP BY 1,2 HAVING count(*)>1) d", 0),
    ("internal_cmd_never_external_sender", "SELECT count(*) FROM email_message WHERE is_internal_command AND from_addr NOT IN ('yonginside@gmail.com','yong.yx1101@gmail.com','yong.yx1103@gmail.com')", 0),
    ("quarantine_all_have_kind", "SELECT count(*) FROM backfill_quarantine WHERE kind IS NULL OR kind=''", 0),
]


def run_assertions(dsn: str, eml_root: str) -> bool:
    import psycopg
    ok = True
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for name, sql, expected in ASSERTIONS:
            if expected == "eq_param":
                cur.execute(sql, (eml_root,))
                actual = cur.fetchone()[0]
                expected = sum(1 for _ in Path(eml_root).rglob("*.eml"))
            else:
                cur.execute(sql)
                actual = cur.fetchone()[0]
            passed = actual == expected
            ok &= passed
            print(f"{'PASS' if passed else 'FAIL'}  {name:40s} expected={expected} actual={actual}")
    return ok


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eml-dir", required=True)
    ap.add_argument("--sheet-csv", required=True)
    ap.add_argument("--labels-json")
    ap.add_argument("--dsn", default=os.environ.get("PG_DSN"))
    ap.add_argument("--org", default="YX")
    ap.add_argument("--org-uuid", help="Deprecated: existing org.id is text; use --org")
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default="backfill_report.json")
    a = ap.parse_args(argv)
    if a.apply == a.dry_run:
        ap.error("choose exactly one of --apply / --dry-run")

    if a.batch_size < 1: ap.error('--batch-size must be positive')
    if not Path(a.eml_dir).is_dir(): ap.error('eml directory does not exist')
    if not list(iter_eml(Path(a.eml_dir))): ap.error('eml directory is empty; zero inputs cannot pass')
    if a.apply and not a.dsn: ap.error('--apply requires --dsn')
    labels = load_labels_index(Path(a.labels_json) if a.labels_json else None)
    mails: list[ParsedMail] = []
    bad_files: list[dict] = []
    for p in iter_eml(Path(a.eml_dir)):
        try:
            mails.append(parse_eml(p, labels))
        except Exception as e:  # 壞檔不中斷，進隔離
            bad_files.append({"kind": "eml_parse_error", "path": str(p), "error": repr(e)[:300]})
    sheet = load_sheet(Path(a.sheet_csv))
    links, serial_members, serial_root, quarantine = stitch(mails, sheet, a.org)
    quarantine += bad_files

    summary = {
        "mails": len(mails), "bad_files": len(bad_files), "sheet_rows": len([r for r in sheet if r.row_no > 0]),
        "sheet_gaps": len([r for r in sheet if "serial_gap" in r.problems]),
        "sheet_duplicates": len([r for r in sheet if any(p.startswith("duplicate") for p in r.problems)]),
        "links_by_rule": {k: sum(1 for l in links if l.rule == k) for k in ("references", "serial_no", "quoted_hash")},
        "serials_with_mail": len(serial_members),
        "serials_with_resolved_original": len(serial_root),
        "internal_commands": sum(1 for m in mails if m.is_internal_command),
        "injection_suspects": sum(1 for m in mails if m.injection_suspect),
        "category_counts": {},
        "org_counts": {},
        "quarantine_by_kind": {},
    }
    for m in mails:
        summary["category_counts"][m.category] = summary["category_counts"].get(m.category, 0) + 1
        summary["org_counts"][m.org_id] = summary["org_counts"].get(m.org_id, 0) + 1
    for q in quarantine:
        summary["quarantine_by_kind"][q["kind"]] = summary["quarantine_by_kind"].get(q["kind"], 0) + 1

    stats = write_db(a.dsn, a.org, mails, sheet, links, serial_members, serial_root, quarantine, a.batch_size, a.apply)
    summary['quarantine_by_kind']={}
    for q in quarantine:
        summary['quarantine_by_kind'][q['kind']]=summary['quarantine_by_kind'].get(q['kind'],0)+1
    summary["db"] = stats
    Path(a.report).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if a.apply:
        return 0 if run_assertions(a.dsn, a.eml_dir) else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
