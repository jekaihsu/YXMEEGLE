"""
switchboard_engine.py — 永祥 Email AI 總機：確定性解析、分類與守門（純函數，零副作用）

設計契約（R29 / R29-PSTACK）：
- 任何函數都不做 I/O；輸入是字串與已知清單，輸出是 dataclass。
- 外部來信永遠無法成為「指令」：parse_satellite_command 對非衛星寄件人回傳 is_internal_address=False。
- 這裡的正則與 PostgreSQL trigger `outbound_guard()` 共用同一份常數（INTERNAL_PATTERNS / FORBIDDEN_WORDS），
  部署時由 CI 匯出成 SQL 常數，避免兩邊漂移。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional, Sequence

# ----------------------------------------------------------------------------
# 常數（與 DB 側共用）
# ----------------------------------------------------------------------------
SWITCHBOARD_ADDR = "yongxiang.ltd@gmail.com"
SATELLITES = {
    "yonginside@gmail.com": "inside",   # 詠翔內業
    "yong.yx1101@gmail.com": "quote",   # 報價管制
    "yong.yx1103@gmail.com": "admin",   # 行政部門
}
ARCHIVE_BCC = "archive@yongxiang.example"  # 部署時換成存檔信箱
# 內部信箱：衛星可發「代寄指令」；總機只能發「轉寄登記」指令（給恆安，業主往來NNNN）
INTERNAL_MAILBOXES = {**SATELLITES, SWITCHBOARD_ADDR: "switchboard"}

ORG_YX, ORG_SJ, ORG_UNKNOWN = "YX", "SJ", "UNKNOWN"
COMPANY_ENTITIES = (
    {"entity_code": "YX", "org_group": ORG_YX, "canonical_name": "詠翔測量有限公司", "aliases": ("詠翔測量", "詠翔測量有限公司", "詠翔測量工程有限公司", "詠翔", "永祥", "永祥測量"), "tax_ids": ("28725008", "80217508", "54100047"), "domains": ("yx.ltd", "yxsurvey.com.tw")},
    {"entity_code": "SJ", "org_group": ORG_SJ, "canonical_name": "上準環境科技股份有限公司", "aliases": ("上準精密", "上準精密測量", "上準環境", "上準", "尚準", "尚準精密", "尚準工程"), "tax_ids": ("83100099",), "domains": ("sjsurvey", "sjsurvey.com.tw")},
    {"entity_code": "SHENGJIE", "org_group": ORG_SJ, "canonical_name": "勝詰工程有限公司", "aliases": ("勝詰", "勝詰工程", "勝詰工程有限公司", "世健", "世健工程"), "tax_ids": ("53462460", "84208069"), "domains": ("shengjie.com.tw",)},
    {"entity_code": "ZHIHUI", "org_group": ORG_SJ, "canonical_name": "智匯工程顧問有限公司", "aliases": ("智匯", "智匯工程", "智匯顧問"), "tax_ids": ("90123456",), "domains": ("zhihui.com.tw",)},
    {"entity_code": "JINGYU", "org_group": ORG_SJ, "canonical_name": "精羽測繪科技有限公司", "aliases": ("精羽", "精羽測繪", "精羽科技"), "tax_ids": ("90234567",), "domains": ("jingyu.com.tw",)},
)
ORG_MARKERS = {
    ORG_YX: {
        "tax_ids": {"28725008", "80217508", "54100047"},
        "names": {"詠翔測量", "詠翔測量有限公司", "詠翔測量工程有限公司", "詠翔", "永祥", "永祥測量"},
        "accounts": {"yx.ltd", "yxsurvey.com.tw"},
    },
    ORG_SJ: {
        "tax_ids": {"83100099", "53462460", "84208069", "90123456", "90234567"},
        "names": {"上準精密", "上準精密測量", "上準環境", "上準", "尚準", "尚準精密", "尚準工程", "勝詰", "勝詰工程", "勝詰工程有限公司", "世健", "世健工程", "智匯", "智匯工程", "智匯顧問", "精羽", "精羽測繪", "精羽科技"},
        "accounts": {"sjsurvey", "sjsurvey.com.tw", "shengjie.com.tw", "zhihui.com.tw", "jingyu.com.tw"},
    },
}

# OTP 白名單：寄件人完全比對 + 主旨正則 + DKIM 網域必須等於寄件網域
OTP_WHITELIST = (
    {"account": "e-GNSS", "sender": "egnss@mail.nlsc.gov.tw", "subject_re": r"(驗證碼|驗證碼通知|Verification)", "code_re": r"\b(\d{4,8})\b"},
    {"account": "CPC-EBCS", "sender": "ebcsAdmin@cpc.com.tw", "subject_re": r"(驗證碼|登入|OTP)", "code_re": r"\b(\d{4,8})\b"},
)
OTP_FORBIDDEN_RE = re.compile(r"(password|reset|密碼|重設|銀行|轉帳|google|apple|tcb|mufg|accounts\.google)", re.I)

BANK_DOMAINS = ("tcb-bank.com.tw", "mufg.jp", "bk.mufg.jp", "ctbcbank.com")
RESUME_DOMAINS = ("104.com.tw", "1111.com.tw")
INSURANCE_SENDERS = ("bli.gov.tw", "nhi.gov.tw")

# 內部指令／內部編號：對外信件出現任一即違規
INTERNAL_PATTERNS = (
    r"寄件人\s*[:：]", r"收件人\s*[:：]", r"麻煩幫我", r"請寄給", r"收到請登記",
    r"業主往來\s*\d+", r"報編\s*\d+", r"#\d+\s*行政", r"^給[\u4e00-\u9fa5A-Za-z]{1,6}\s*[，,]", r"^給[^，,\n]+[，,]",
)
INTERNAL_RE = re.compile("|".join(f"(?:{p})" for p in INTERNAL_PATTERNS), re.M)
FORBIDDEN_WORDS = ("成本", "毛利", "底價", "A/B/C", "ABC預算", "內部", "點數單價")
FORBIDDEN_RE = re.compile("|".join(re.escape(w) for w in FORBIDDEN_WORDS))

CASE_CODE_PATTERN = r"^[A-MVXZ][0-9]{6}(-[0-9A-Z]{1,3})?$"
CASE_CODE_RE = re.compile(CASE_CODE_PATTERN)
CASE_CODE_EXTRACT_RE = re.compile(r"(?<![A-Za-z0-9-])(" + CASE_CODE_PATTERN[1:-1] + r")(?![A-Za-z0-9-])")
BANK_FEE_TOLERANCE_TWD = 100


def extract_case_code(text: str) -> Optional[str]:
    match = CASE_CODE_EXTRACT_RE.search(text)
    return match.group(1) if match else None

QUOTE_REF_RE = re.compile(r"報編\s*(\d{5,7})")
SERIAL_RE = re.compile(r"業主往來\s*(\d{1,6})")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://|www[.]|href\s*=|[a-z0-9-]+[.][a-z]{2,}([/.:]|\b)", re.I)
SEALED_EXT = (".dwg", ".dxf")

# 轉寄／引用鏈切點
QUOTE_CUT_RE = re.compile(
    r"^(?:-{3,}\s*Original Message\s*-{3,}|-{5,}\s*Forwarded message\s*-{5,}|On .+?wrote:|"
    r"\d{4}年\d{1,2}月\d{1,2}日.*?寫道[:：]|寄件者\s*[:：].*|From\s*:\s.*@.*|---+ 轉寄的郵件 ---+)",
    re.M,
)
QUOTED_LINE_RE = re.compile(r"^\s*>.*$", re.M)

# 類別判定（順序即優先序）
CAT_RULES: Sequence[tuple[str, str, str]] = (
    # (category, sender-domain-regex, subject/body-regex)
    ("CAT-05", r"(bizmail\.docx\.tw|docusign)", r"."),                               # 公文系統／電子簽署：寄件網域即定類
    ("CAT-06", r"(bes\.com\.tw|thsrc\.com\.tw|fpg\.com\.tw|formosa2project\.com|einvoice\.nat\.gov\.tw)", r"(驗收|核決|計價|請款|估驗|電子發票配號)"),
    ("CAT-05", r".", r"(工作指示單|PCDL-\d+-\d+|決標通知|開工會勘|公文待收|出工人數及進度通知|提報開工|開工會議紀錄|工程承攬切結書)"),  # 任何網域的契約指示單／決標
    ("CAT-04", r"(fpg\.com\.tw|thsrc\.com\.tw|caa\.gov\.tw)", r"(憑單|出入廠|作業核准|作業申請已核准|門禁提示|空域|職安|回訓)"),
    ("CAT-04", r".", r"(入廠申請|承攬商門禁|出入廠憑單|HSROR|回訓資訊)"),
    ("CAT-03", r".", r"(退件|重測|補正|審查意見|成果修正|不符合規範|JSA)"),
    ("CAT-02", r".", r"(成果提供|成果提送|成果資料|成果提交|成果照片|成果初稿|監測成果|沉陷監測成果|階段報告|施工日報|\(成果提供\)|\(資料提供\))"),
    ("CAT-01", r"(tradevan|ctci|thsrc|fpg|tccon|ceci)", r"(詢價|招標|議價|報價|業主回傳|回傳單|簽認|發包)"),
    ("CAT-01", r".", r"(詢價|議價|報價回傳|【業主回傳】|業主回傳|報價確認|報價編號|煩請幫忙報價|評估報價|加測|追加|變更設計|服務建議書|電訪紀錄)"),
    ("CAT-07", r".", r"(請款單|代墊|鑑界|建築線|下包|外包報價|小柯)"),
    ("CAT-08", r".", r"(RFQ|ROV|USV|RMA|DHL|DISPUTE|Repair INV|海事|尋船|離岸|報關)"),
    ("CAT-06", r".", r"(計價數量確認|驗收已核決|請發文計價|電子發票配號|匯款入帳)"),
    ("CAT-03", r".", r"(修正)"),
    ("CAT-10", r"(cwa\.gov\.tw|cwb\.gov\.tw|fpg\.com\.tw|fpcc\.com\.tw|gsmma\.gov\.tw)", r"(颱風|警報|豪雨|協議組織會議|入廠前工安|入廠證|通知單)"),
)


# ----------------------------------------------------------------------------
# 資料類別
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class AttachmentMeta:
    filename: str
    sha256: str
    bytes: int = 0
    is_sealed: bool = False       # 官章版（由 deliverable_version 判定後帶入）


@dataclass(frozen=True)
class StrippedCommandResult:
    is_internal_address: bool
    command_kind: str                 # 'send_external' | 'forward_register' | 'none'
    satellite_role: Optional[str]
    requester: Optional[str]          # 指令裡的署名（倢瑛／宜蓁／恆安…），非 mailbox
    target_recipient_query: Optional[str]
    target_email: Optional[str]
    admin_tag: Optional[str]          # '#14行政 蕭小姐'
    template_hint: Optional[str]
    serial_ref: Optional[int]
    quote_ref: Optional[str]
    case_ref: Optional[str]
    instruction_block: str
    clean_body: str
    body_sha256: str
    has_residual_internal_pattern: bool
    attachments: tuple[AttachmentMeta, ...] = ()


@dataclass(frozen=True)
class InboundClassification:
    category: str                     # 'CAT-01'..'CAT-10' | 'INTERNAL-CMD' | 'UNCLASSIFIED'
    org_id: str                       # 'YX' | 'SJ' | 'UNKNOWN'
    is_otp_candidate: bool
    is_otp_whitelisted: bool
    otp_account: Optional[str]
    otp_code: Optional[str]
    injection_suspect: bool
    quarantine_reason: Optional[str]
    case_ref: Optional[str]
    quote_ref: Optional[str]
    serial_ref: Optional[int]
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str


# ----------------------------------------------------------------------------
# 正規化
# ----------------------------------------------------------------------------
_FULLWIDTH = str.maketrans({"：": ":", "，": ",", "（": "(", "）": ")", "　": " ", "＃": "#"})


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return text.translate(_FULLWIDTH).replace("\r\n", "\n").replace("\r", "\n")


def _raw_lines(body: str) -> list[str]:
    """只統一換行，不動標點：寄給業主的正文必須保留全形標點。"""
    return (body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def strip_quoted_chain(body: str) -> str:
    """去除轉寄／回覆引用鏈，只留新內容。偵測用正規化副本，輸出用原文行。"""
    raw = _raw_lines(body)
    kept: list[str] = []
    for ln in raw:
        n = normalize(ln)
        if QUOTE_CUT_RE.match(n.strip()) or QUOTE_CUT_RE.match(n):
            break                      # 之後全是引用鏈
        if QUOTED_LINE_RE.match(n):
            continue                   # 單行引用
        kept.append(ln.rstrip())
    while kept and (not kept[-1].strip() or kept[-1].strip() in ("--", "—")):
        kept.pop()
    while kept and not kept[0].strip():
        kept.pop(0)
    return "\n".join(kept)


def sha256_text(text: str) -> str:
    return hashlib.sha256(normalize(text).strip().encode("utf-8")).hexdigest()


def loose_hash(text: str) -> str:
    """去除所有空白與引用符號後的雜湊：轉寄引用區 vs 原信新內容的縫合鍵。"""
    t = re.sub(r"^\s*>\s?", "", normalize(text), flags=re.M)
    return hashlib.sha256(re.sub(r"\s+", "", t).encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------
# 衛星指令解析
# ----------------------------------------------------------------------------
_CMD_SENDER_RECIP = re.compile(r"^寄件人\s*:\s*(?P<req>[^\s(:]+)(?:\((?P<alias>[^)]*)\))?\s*收件人\s*:\s*(?P<to>.+?)(?:\s+主旨\s*:.*)?$")
_CMD_PLEASE_SEND = re.compile(r"^(?:(?P<op>[\u4e00-\u9fa5]{1,3})\s*,\s*)?(?:這封信)?麻煩幫我寄給\s*(?P<to>.+?)(?:\s*,?\s*(?:謝謝|感謝).*)?$")
_CMD_SEND_TO = re.compile(r"^請寄給\s*(?P<to>.+?)(?:\s*(?P<tag>#\d+\s*行政\s*\S+))?\s*$")
_CMD_FORWARD = re.compile(r"^給(?P<req>[\u4e00-\u9fa5A-Za-z、]{1,10})\s*,\s*業主往來\s*(?P<serial>\d+)")
_CMD_QUOTE_FORWARD = re.compile(r"^報編\s*(?P<quote>\d{5,7})\s*,\s*給(?P<req>[^,]+)\s*,\s*業主往來\s*(?P<serial>\d+)")
_ADMIN_TAG = re.compile(r"(#\d+\s*行政\s*\S+)")
TEMPLATE_HINTS = (
    ("quote_return_reply", r"(報價回傳|回傳單|簽認)"),
    ("inquiry_reply", r"詢價"),
    ("deliverable_submit", r"(成果|提送)"),
    ("billing_reply", r"(計價|請款)"),
    ("review_fix_reply", r"(審查|修正|補正)"),
    ("company_profile", r"基本資料"),
)


def _is_instruction_line(line: str) -> bool:
    return bool(INTERNAL_RE.search(line)) or any(p.match(line) for p in (_CMD_SENDER_RECIP, _CMD_PLEASE_SEND, _CMD_SEND_TO, _CMD_FORWARD, _CMD_QUOTE_FORWARD))


def parse_satellite_command(from_addr: str, subject: str, raw_body: str,
                            attachments: Iterable[AttachmentMeta] = ()) -> StrippedCommandResult:
    from_addr = (from_addr or "").strip().lower()
    role = INTERNAL_MAILBOXES.get(from_addr)
    body = strip_quoted_chain(raw_body)
    lines = body.split("\n")
    norm_lines = [normalize(ln).strip() for ln in lines]

    # 指令區：開頭連續的指令行（最多 6 行），遇空行或非指令行即止；偵測用正規化行，原文行保留
    instr: list[str] = []
    i = 0
    while i < len(lines) and i < 6 and norm_lines[i] and _is_instruction_line(norm_lines[i]):
        instr.append(norm_lines[i])
        i += 1
    clean_lines = lines[i:]
    # 指令區後緊接的空行去掉
    while clean_lines and not clean_lines[0].strip():
        clean_lines.pop(0)
    clean_body = "\n".join(clean_lines).strip()
    instruction_block = "\n".join(instr)

    kind, requester, to_q, tag = "none", None, None, None
    serial = quote = None
    for ln in instr:
        if (m := _CMD_SENDER_RECIP.match(ln)):
            kind, requester, to_q = "send_external", m.group("req"), m.group("to").strip()
        elif (m := _CMD_PLEASE_SEND.match(ln)):
            kind, to_q = "send_external", m.group("to").strip()
        elif (m := _CMD_SEND_TO.match(ln)):
            kind, to_q = "send_external", m.group("to").strip()
            tag = m.group("tag")
        elif (m := _CMD_QUOTE_FORWARD.match(ln)):
            kind, requester, quote, serial = "forward_register", m.group("req").strip(), m.group("quote"), int(m.group("serial"))
        elif (m := _CMD_FORWARD.match(ln)):
            kind, requester, serial = "forward_register", m.group("req").strip(), int(m.group("serial"))
        if (t := _ADMIN_TAG.search(ln)):
            tag = t.group(1)
        if serial is None and (s := SERIAL_RE.search(ln)):
            serial = int(s.group(1))
        if quote is None and (q := QUOTE_REF_RE.search(ln)):
            quote = q.group(1)

    target_email = None
    if to_q:
        if (e := EMAIL_RE.search(to_q)):
            target_email = e.group(0).lower()
        # 收件人查詢字串去掉 admin tag 與 email
        to_q = _ADMIN_TAG.sub("", EMAIL_RE.sub("", to_q)).strip(" ,")

    hint = None
    for name, pat in TEMPLATE_HINTS:
        if re.search(pat, normalize(subject) + " " + instruction_block):
            hint = name
            break
    case_ref = extract_case_code(normalize(subject) + " " + body)
    if quote is None and (q := QUOTE_REF_RE.search(normalize(subject))):
        quote = q.group(1)

    residual = bool(INTERNAL_RE.search(clean_body)) or bool(INTERNAL_RE.search(normalize(subject)))
    if role is None:
        kind = "none"   # 外部來源永遠不是指令，但仍回傳解析結果供標記注入嫌疑
    elif role == "switchboard" and kind == "send_external":
        kind = "none"   # 總機帳號不能自己下「代寄」指令（防止總機被盜後自導自演）
    return StrippedCommandResult(
        is_internal_address=role is not None, command_kind=kind, satellite_role=role,
        requester=requester, target_recipient_query=to_q, target_email=target_email, admin_tag=tag,
        template_hint=hint, serial_ref=serial, quote_ref=quote, case_ref=case_ref,
        instruction_block=instruction_block, clean_body=clean_body, body_sha256=sha256_text(clean_body),
        has_residual_internal_pattern=residual, attachments=tuple(attachments),
    )


# ----------------------------------------------------------------------------
# 進件分類
# ----------------------------------------------------------------------------
def detect_org(to_addrs: Iterable[str], subject: str, body: str) -> str:
    blob = normalize(subject) + "\n" + normalize(body) + "\n" + " ".join(to_addrs or ())
    hits = set()
    for org, mk in ORG_MARKERS.items():
        if any(t and t in blob for t in mk["tax_ids"]) or any(n in blob for n in mk["names"]) or any(a in blob for a in mk["accounts"]):
            hits.add(org)
    if hits == {ORG_YX}:
        return ORG_YX
    if hits == {ORG_SJ}:
        return ORG_SJ
    if len(hits) > 1:
        return ORG_UNKNOWN        # 兩家都出現 → 隔離，人判
    return ORG_YX                 # 無標記時預設詠翔（總機主業）


def _otp_check(from_addr: str, subject: str, body: str, dkim_pass: bool, dkim_domain: Optional[str]) -> tuple[bool, bool, Optional[str], Optional[str]]:
    """回傳 (is_candidate, is_whitelisted, account, code)"""
    sub, bod = normalize(subject), normalize(body)
    looks_like_otp = bool(re.search(r"(驗證碼|OTP|Verification)", sub + bod, re.I))
    for rule in OTP_WHITELIST:
        if from_addr.lower() == rule["sender"].lower() and re.search(rule["subject_re"], sub, re.I):
            sender_domain = rule["sender"].split("@")[1]
            if not dkim_pass or (dkim_domain or "").lower() != sender_domain:
                return True, False, rule["account"], None
            if OTP_FORBIDDEN_RE.search(sub + "\n" + bod):
                return True, False, rule["account"], None
            m = re.search(rule["code_re"], bod)
            return True, True, rule["account"], (m.group(1) if m else None)
    return looks_like_otp, False, None, None


def classify_inbound_email(from_addr: str, to_addrs: Sequence[str], subject: str, clean_body: str,
                           attachment_meta: Sequence[AttachmentMeta] = (), dkim_pass: bool = False,
                           spf_pass: bool = False, dkim_domain: Optional[str] = None) -> InboundClassification:
    raw_from = (from_addr or "").strip()
    m_angle = re.search(r"<\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\s*>", raw_from)
    from_addr = m_angle.group(1).lower() if m_angle else raw_from.lower()
    domain = from_addr.split("@")[-1]
    sub, body = normalize(subject), normalize(clean_body)
    att_names = " ".join(normalize(a.filename) for a in (attachment_meta or ()))
    ref_blob = sub + " " + body + (" " + att_names if att_names else "")
    reasons: list[str] = []
    org = detect_org(to_addrs, sub, body + (" " + att_names if att_names else ""))
    case_ref = extract_case_code(ref_blob)
    quote_ref = (m.group(1) if (m := QUOTE_REF_RE.search(ref_blob)) else None)
    serial_ref = (int(m.group(1)) if (m := SERIAL_RE.search(ref_blob)) else None)

    # 外部信若長得像指令 → 注入嫌疑，且永遠不是 INTERNAL-CMD
    first_line = (body.split("\n") or [""])[0]
    injection = from_addr not in INTERNAL_MAILBOXES and bool(INTERNAL_RE.search(first_line) or INTERNAL_RE.search(sub))
    if injection:
        reasons.append("command-like text from non-internal sender")

    if injection:
        return InboundClassification("UNCLASSIFIED", org, False, False, None, None,
                                     True, "injection suspect", case_ref, quote_ref,
                                     serial_ref, tuple(reasons))

    if from_addr in SATELLITES:
        if not dkim_pass or not spf_pass or not dkim_domain or dkim_domain.strip().lower() != domain:
            reasons.append("spoofed satellite From: dkim_domain mismatch or dkim_pass=False")
            return InboundClassification(
                "UNCLASSIFIED", org, False, False, None, None, True,
                f"spoofed satellite From: dkim_domain={dkim_domain}",
                case_ref, quote_ref, serial_ref, tuple(reasons),
            )
        return InboundClassification("INTERNAL-CMD", org, False, False, None, None, False, None, case_ref, quote_ref, serial_ref, ("satellite sender",))
    if from_addr == SWITCHBOARD_ADDR:
        if not dkim_pass or not spf_pass or not dkim_domain or dkim_domain.strip().lower() != domain:
            reasons.append("spoofed switchboard From: dkim_domain mismatch or dkim_pass=False")
            return InboundClassification(
                "UNCLASSIFIED", org, False, False, None, None, True,
                f"spoofed switchboard From: dkim_domain={dkim_domain}",
                case_ref, quote_ref, serial_ref, tuple(reasons),
            )
        return InboundClassification("INTERNAL-FWD", org, False, False, None, None, False, None, case_ref, quote_ref, serial_ref, ("switchboard forward",))

    cand, wl, acct, code = _otp_check(from_addr, sub, body, dkim_pass, dkim_domain)
    if cand:
        q = None if wl else "otp candidate not whitelisted/dkim-failed/forbidden-term"
        return InboundClassification("CAT-10", org, True, wl, acct, code, injection, q, case_ref, quote_ref, serial_ref, ("otp rule",))

    if any(domain.endswith(d) for d in BANK_DOMAINS):
        return InboundClassification("CAT-06", org, False, False, None, None, injection, None, case_ref, quote_ref, serial_ref, ("bank notice"))
    if any(domain.endswith(d) for d in RESUME_DOMAINS) or re.search(r"(應徵|履歷)", sub):
        return InboundClassification("CAT-09", org, False, False, None, None, injection, None, case_ref, quote_ref, serial_ref, ("resume",))
    if any(domain.endswith(d) for d in INSURANCE_SENDERS) or re.search(r"(勞保|健保|勞退).*(帳單|繳費)", sub):
        q = "insurance bill: org ambiguous" if org == ORG_UNKNOWN else None
        return InboundClassification("CAT-09", org, False, False, None, None, injection, q, case_ref, quote_ref, serial_ref, ("insurance bill",))

    search_blob = sub + "\n" + body[:2000] + ("\n" + att_names if att_names else "")
    for cat, dom_re, kw_re in CAT_RULES:
        if re.search(dom_re, domain) and re.search(kw_re, search_blob, re.I):
            reasons.append(f"{cat}: domain~{dom_re} kw~{kw_re}")
            q = "org ambiguous" if org == ORG_UNKNOWN else None
            return InboundClassification(cat, org, False, False, None, None, injection, q, case_ref, quote_ref, serial_ref, tuple(reasons))
    if attachment_meta and (case_ref or quote_ref):
        reasons.append("CAT-02: attachment with case/quote ref fallback")
        q = "org ambiguous" if org == ORG_UNKNOWN else None
        return InboundClassification("CAT-02", org, False, False, None, None, injection, q, case_ref, quote_ref, serial_ref, tuple(reasons))

    return InboundClassification("UNCLASSIFIED", org, False, False, None, None, injection,
                                 "no rule matched" if not injection else "injection suspect", case_ref, quote_ref, serial_ref, tuple(reasons))


# ----------------------------------------------------------------------------
# 對外守門（與 DB trigger 同義，供 API 預檢與測試）
# ----------------------------------------------------------------------------
def check_outbound_body(subject: str, final_body: str) -> list[Violation]:
    text = normalize(subject) + "\n" + normalize(final_body)
    for kind, code in (("internal", "INTERNAL_TEXT"), ("forbidden", "FORBIDDEN_WORD")):
        hit = guard_hit(kind, text)
        if hit:
            return [Violation(code, hit)]
    return []


def check_delivery_constraints(constraints: dict, final_body: str, attachments: Sequence[AttachmentMeta]) -> list[Violation]:
    v: list[Violation] = []
    c = constraints or {}
    if c.get("no_links") and URL_RE.search(normalize(final_body)):
        v.append(Violation("NO_LINKS", "customer forbids external links"))
    limit = c.get("max_attachment_mb")
    if limit:
        for a in attachments:
            if a.bytes > limit * 1024 * 1024:
                v.append(Violation("ATTACHMENT_TOO_LARGE", f"{a.filename} > {limit}MB; split or ship CD"))
    if c.get("official_doc_number_required") and not re.search(r"\(\d{3}\)詠發字第\d+號", normalize(final_body)):
        v.append(Violation("DOC_NUMBER_REQUIRED", "government recipient requires official document number"))
    return v


def check_sealed_release(attachments: Sequence[AttachmentMeta], hold_until_paid: bool,
                         invoice_unpaid_amount: float, override_valid: bool) -> list[Violation]:
    sealed = [a for a in attachments if a.is_sealed or a.filename.lower().endswith(SEALED_EXT)]
    if sealed and hold_until_paid and invoice_unpaid_amount > 0 and not override_valid:
        return [Violation("HOLD_UNTIL_PAID", ", ".join(a.filename for a in sealed))]
    return []


def validate_bes_invoice(invoice_date: date, item_name: str, contract_no: str, contract_name: str, period: int) -> list[Violation]:
    """中華工程：發票日 10~20 日；品名 = 合約編號+合約名稱+第X期計價"""
    v: list[Violation] = []
    if not 10 <= invoice_date.day <= 20:
        v.append(Violation("BES_INVOICE_DATE", f"day {invoice_date.day} not in 10..20"))
    expected = f"{contract_no}{contract_name}第{period}期計價"
    if normalize(item_name).replace(" ", "") != expected:
        v.append(Violation("BES_ITEM_NAME", f"expected '{expected}'"))
    return v


def thread_fingerprint(subject: str, message_id: Optional[str], references: Sequence[str], serial_ref: Optional[int],
                       body_sha256: str) -> str:
    """縫合鍵：References 根 > 業主往來序號 > 主旨正規化+正文雜湊"""
    if references:
        return "ref:" + references[0]
    if serial_ref:
        return f"serial:{serial_ref}"
    subj = re.sub(r"^(?:(re|fw|fwd|轉寄|回覆)\s*[:：]\s*)+", "", normalize(subject), flags=re.I).strip().lower()
    return "subj:" + hashlib.sha1((subj + "|" + body_sha256[:16]).encode()).hexdigest()


def shared_guard_patterns():
    """The only source of shared regexes, including flags and first-hit ordering."""
    for i, pattern in enumerate(INTERNAL_PATTERNS):
        yield ("internal", f"internal_{i:02d}", pattern, "m")
    for i, word in enumerate(FORBIDDEN_WORDS):
        yield ("forbidden", f"forbidden_{i:02d}", r"\s*".join(re.escape(c) for c in word), "")
    yield ("forbidden", "forbidden_99", r"A[ /-]*B[ /-]*C", "i")
    yield ("case_code", "case_code", CASE_CODE_PATTERN, "full")
    for rule in OTP_WHITELIST:
        yield ("otp_subject", "otp_" + rule["account"], rule["subject_re"], "i")
        yield ("otp_code", "code_" + rule["account"], rule["code_re"], "")
    yield ("otp_forbidden", "otp_forbidden", OTP_FORBIDDEN_RE.pattern, "i")
    yield ("url", "url", URL_RE.pattern, "i")
    yield ("org_sj_marker", "sj_marker_in_yx", r"(上準精密|上準環境|sjsurvey\.com\.tw|\b83100099\b|\b53462460\b)", "i")
    yield ("org_yx_marker", "yx_marker_in_sj", r"(詠翔測量|yxsurvey\.com\.tw|\b28725008\b|\b54100047\b)", "i")


def guard_hit(kind: str, text: str) -> Optional[str]:
    value = text if kind == "case_code" else normalize(text)
    for k, name, pattern, flags in sorted(shared_guard_patterns(), key=lambda row: row[1]):
        if k != kind:
            continue
        matched = re.fullmatch(pattern, value) if flags == "full" else re.search(
            pattern, value, (re.M if "m" in flags else 0) | (re.I if "i" in flags else 0))
        if matched:
            return name
    return None


@dataclass(frozen=True)
class CommandHeaderStrip:
    body_after_strip: str


def strip_command_header(body: str) -> CommandHeaderStrip:
    """Compatibility for the in-progress gates adapter; this grants no sender authority."""
    parsed = parse_satellite_command(next(iter(SATELLITES)), '', body)
    return CommandHeaderStrip(parsed.clean_body)


def check_otp_pull(sender: str, dkim_domain: str, dkim_pass: bool, spf_pass: bool,
                   subject: str = '', body: str = '') -> tuple[bool, str]:
    """Source check only; the caller must also verify the authenticated requester."""
    candidate, allowed, account, code = _otp_check(sender, normalize(subject), normalize(body), dkim_pass, dkim_domain)
    ok = bool(candidate and allowed and spf_pass and code)
    return ok, 'whitelisted source' if ok else 'OTP source/authentication/code rejected'


def sealed_release_message(unpaid_amount):
    """The amount is supplied by invoice_paid_v; tolerance never grants release."""
    if unpaid_amount <= 0:
        return "已完成財務沖帳"
    if unpaid_amount <= BANK_FEE_TOLERANCE_TWD:
        return f"待財務沖帳（差 NT${unpaid_amount:g}，匯費容差內）"
    return f"待財務沖帳（未收 NT${unpaid_amount:g}）"


# ----------------------------------------------------------------------------
# Step 4 黃金反例純函數（與 012_fable_step4_r32_and_recall.sql 語意對齊）
# ----------------------------------------------------------------------------
def resolve_serial_assignment(
    org_id: str,
    fingerprint: str,
    mode: str,
    existing_rows: dict[tuple[str, str, str], int],
    next_live_seq: int = 12085,
    next_dry_seq: int = -12085,
    alias_map: Optional[dict[tuple[str, str], str]] = None,
) -> int:
    """
    Step 4 (1) serial_assignment 保護：
    - 唯一鍵為 (org_id, fingerprint, mode)
    - 先查詢 alias_map (對應 DB public.serial_fingerprint_alias)，將真實信件 ref:/msg:/serial: 指紋映射至 legacy:yezhu:<N>
    - CHECK: (mode='live' AND serial_no>0) OR (mode='dry_run' AND serial_no<=-12085)
    - dry_run 路徑開頭若已存在同 (org_id, fingerprint) 的 live 列（包含 <=12084 舊串），立即 RAISE。
    """
    if mode not in ("live", "dry_run"):
        raise ValueError(f"invalid mode: {mode}")
    if alias_map and (org_id, fingerprint) in alias_map:
        fingerprint = alias_map[(org_id, fingerprint)]
    live_key = (org_id, fingerprint, "live")
    dry_key = (org_id, fingerprint, "dry_run")
    if mode == "dry_run":
        if live_key in existing_rows:
            raise ValueError("R32-SER-DRY-OVER-LIVE: fingerprint already has live serial; dry_run refused")
        if dry_key in existing_rows:
            s = existing_rows[dry_key]
        else:
            s = next_dry_seq
        if not (s <= -12085):
            raise ValueError(f"serial_assignment_mode_sign_chk violated for dry_run: {s}")
        existing_rows[dry_key] = s
        return s
    else:
        if live_key in existing_rows:
            s = existing_rows[live_key]
        else:
            s = next_live_seq
        if not (s > 0):
            raise ValueError(f"serial_assignment_mode_sign_chk violated for live: {s}")
        existing_rows[live_key] = s
        return s


def verify_satellite_sent_copy_header_d(from_addr: str, dkim_pass: bool, dkim_header_d: Optional[str]) -> str:
    """
    Step 4 (2) email_sent_copy.header_d 驗證：
    - header_d 只能來自 ETL 解析 Authentication-Results: dkim=pass header.d=
    - 絕不可由 From 地址直接推導，且不能含 '@' 或與信箱網域不符。
    """
    if not dkim_pass or not dkim_header_d or not dkim_header_d.strip():
        raise ValueError("STEP4-DKIM-HEADER-D: missing observed dkim=pass header.d")
    hd = dkim_header_d.strip().lower()
    if "@" in hd:
        raise ValueError(f"STEP4-DKIM-HEADER-D: header_d {hd!r} looks like an email address, not a DKIM domain")
    addr = (from_addr or "").strip().lower()
    if addr not in SATELLITES:
        raise ValueError(f"R32-SAT-AUTH: sender {addr!r} is not an active satellite mailbox")
    expected_domain = addr.split("@", 1)[1]
    if hd != expected_domain:
        raise ValueError(f"R32-SAT-AUTH: dkim header.d {hd!r} != satellite domain {expected_domain!r}")
    return hd


def evaluate_org_marker_separation(direction: str, org_id: Optional[str], text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Step 4 (3) org_marker 收發分離（涵蓋 6 家公司實體：詠翔、永祥、上準/尚準、勝詰/世健、智匯、精羽）：
    - 收件側（inbound）遇到跨組織標記（例如 YX 信件帶上準統編 83100099 / 勝詰 53462460 / 智匯 / 精羽）：
      不 RAISE、不丟信，改設 (org_id=None, quarantine_reason='R32-ORG-MARKER:...')。
    - 發件側（outbound）遇到跨組織標記：立即 RAISE RuntimeError('R32-ORG-MARKER:...')。
    """
    eff_org = org_id or ORG_YX
    other_org = ORG_SJ if eff_org == ORG_YX else ORG_YX
    hit = guard_hit("org_sj_marker" if eff_org == ORG_YX else "org_yx_marker", text or "")
    if not hit:
        norm = normalize(text or "")
        mk = ORG_MARKERS.get(other_org, {})
        for tid in mk.get("tax_ids", ()):
            if tid and tid in norm:
                hit = f"tax_id:{tid}"
                break
        if not hit:
            for nm in sorted(mk.get("names", ()), key=len, reverse=True):
                if nm and nm in norm:
                    hit = f"name:{nm}"
                    break
        if not hit:
            for acc in mk.get("accounts", ()):
                if acc and acc.lower() in norm.lower():
                    hit = f"domain:{acc}"
                    break
    if not hit:
        return eff_org, None
    reason = f"R32-ORG-MARKER:{other_org}:{hit}"
    if direction == "inbound":
        return None, reason
    raise RuntimeError(f"{reason} forbidden on outbound {eff_org}")


def compute_invoice_paid_after_bounced_check(
    amount_due: int,
    allocations: Sequence[tuple[int, str]],
    reversals: Sequence[tuple[int, str]],
) -> tuple[int, int, bool]:
    """
    Step 4 (4) #11 退票雙算修正：
    - allocations: [(amount, instrument_status), ...]
    - reversals: [(amount, instrument_status), ...]
    - 只有當 instrument_status == 'cleared' 時才計入 allocation 與 reversal，避免退票(bounced)時
      allocation 已排除卻又加上 reversal 造成 unpaid_amount 變成 2 倍。
    回傳 (paid_amount, unpaid_amount, is_paid)。
    """
    cleared_alloc = sum(amt for amt, st in allocations if st == "cleared")
    cleared_rev = sum(amt for amt, st in reversals if st == "cleared")
    net_paid = cleared_alloc - cleared_rev
    unpaid = amount_due - net_paid
    return net_paid, unpaid, (unpaid == 0 and net_paid > 0)
