#!/usr/bin/env python3
"""
Seed & Reset Real PostgreSQL Tables for 詠翔 · 業主往來 (Real Product Upgrade)
Target DB: yongxiang_plumb_r39_clone (Strictly forbidden from touching production yongxiang_plumb)
Uses stdlib + db.py (psql -X -v ON_ERROR_STOP=1 -Atq).
Populates:
  - public.yezhu_workbench_case (10 active workbench cases + 980+ real cases from public.case / V3 853 / Quotes 423)
  - public.yezhu_correspondence_ledger (12,084 historical correspondence serials #1..#12084 + 21 intake shadow serials D-12085..D-12105)
  - public.yezhu_softlock (90s TTL multi-user soft-lock table)
  - public.yezhu_workbench_meta (global workbench state: pins, next_serial, authorized, merged, quarantine, admin_claimed='羅薇')
"""
import json
import os
import re
import sys
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import db

PG_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/yongxiang_plumb_r39_clone"

FORBIDDEN_REPLACEMENTS = [
    ("張羅薇", "羅薇"),
    ("羅薇", "羅薇"),
    ("CAT-", "類別"),
    ("sql_id", "編號"),
    ("uuid", "識別碼"),
    ("RAG", "知識庫"),
    ("Agent", "助理"),
    ("AI", "智慧"),
    ("系統", "平台"),
    ("模型", "模組"),
    ("閘門", "檢查"),
    ("guard", "保護"),
    ("客戶端", "業主端"),
    ("進件", "來信"),
    ("自動學習", "規則整理"),
    ("一鍵學習", "快速整理"),
    ("記憶規則", "既有習慣"),
    ("打字規則", "文字習慣"),
    ("紅燈", "待修正"),
    ("綠燈", "已確認"),
    ("黃燈", "待留意"),
    ("高風險", "需留意"),
    ("攔截", "提醒"),
    ("自動放行", "直接寄出"),
    ("可放行", "可寄出"),
    ("放行綠燈", "檢查完成"),
    ("全綠", "全部完成"),
    ("信賴區間", "估計範圍"),
    ("相似度", "相近程度"),
    ("向量", "索引"),
    ("Token", "權杖"),
    ("Prompt", "指令"),
    ("底價", "標準價"),
    ("成本", "預算"),
    ("毛利", "結餘"),
    ("時薪", "鐘點費"),
    ("PASS", "完成"),
    ("FAIL", "未過"),
    ("INV-", "規則"),
    ("sql:", "查詢"),
]


def clean_text(val: str) -> str:
    if not val:
        return ""
    s = str(val).strip()
    s = re.sub(r"[\r\t\u200b\u200c\u200d\ufeff\u3000]", " ", s)
    for bad, good in FORBIDDEN_REPLACEMENTS:
        pattern = r"(?<![A-Za-z])" + re.escape(bad) + r"(?![A-Za-z])" if bad.isascii() else re.escape(bad)
        s = re.sub(pattern, good, s, flags=re.IGNORECASE if bad.isascii() else 0)
    s = re.sub(r"\b(?:C[1-9]|C1[0-3]|G[1-9]|G10|S[0-7]|R3[0-9])\b", "", s)
    return s.strip()


def identity_text(value) -> str:
    """Names and addresses are source data; display vocabulary rules do not apply."""
    return str(value or '').strip()


def make_short_name(code: str, client: str, title: str) -> str:
    """Ensure len(f'{code} {name}') <= 18 strictly for left sidebar 2-line constraint."""
    max_name_len = max(2, 18 - len(code) - 1)
    c_short = clean_text(client)
    for suffix in [
        "股份有限公司", "有限公司", "工程顧問", "科技服務", "企業", "營造",
        "經濟部水利署", "交通部公路局", "台灣電力", "台灣中油", "台灣塑膠工業",
    ]:
        c_short = c_short.replace(suffix, "")
    c_short = c_short.strip(" -_—()")
    t_short = clean_text(title)
    t_short = re.sub(r"^11[0-6]年度?", "", t_short).strip(" -_—()")
    if c_short and len(c_short) <= 4:
        cand = f"{c_short} {t_short}" if max_name_len >= 7 else f"{c_short}{t_short}"
    elif t_short:
        cand = t_short
    else:
        cand = c_short or "測量專案"
    cand = clean_text(cand)
    return cand[:max_name_len].strip() or "測量案"[:max_name_len]


def get_initial_10_cases():
    """Exact 10 initial workbench cases with 羅薇 -> 羅薇 and rich correspondence threads."""
    return [
        {
            "code": "C114609",
            "name": "中油 儲槽沉陷監測",
            "full_title": "台灣中油大林廠儲槽沉陷監測與期末成果提送",
            "client": "台灣中油股份有限公司",
            "pm": "吳柏頤",
            "admin_owner": "行政羅薇",
            "phase": "overdue",
            "when": "逾期 1 天",
            "next": "待你確認尾款入帳前預覽版",
            "who": "鄭文澤",
            "reminder": "鄭文澤請你寄期末成果給林課長，尾款未入帳已鎖正式圖",
            "facts": ["合約總額 960,000 元", "已收 600,000 元", "未收 360,000 元"],
            "contact": "林課長",
            "addr": "lin.dl@cpc.com.tw",
            "host": "cpc.com.tw",
            "subj": "儲槽沉陷監測｜期末成果提送",
            "text": "林課長您好：\n\n儲槽沉陷監測期末預覽圖請由 https://drive.yx.tw/dalin 下載，並隨信提供封存版 DWG 圖檔，敬請查收。\n\n詠翔測量工程有限公司 敬上",
            "file": "C114609_正式成果圖_官章版.dwg",
            "sum": 960000,
            "received": 600000,
            "allowed": [960000, 600000, 360000],
            "bill": "本案上次請款為 10/01（尾款 360,000 元），截至今天尚未入帳。",
            "message": "林課長：請今天提供儲槽沉陷期末成果圖，正式 DWG 也一併給我們。",
            "internal": "鄭文澤：圖已整理完成，尾款入帳前封存成果先不要放行。",
            "latest": "審查意見修正與補測回覆",
            "serial": 12092,
            "sort_order": 1,
            "is_pinned_default": True,
            "threads": [
                {
                    "serial": "12081",
                    "title": "開工範圍與控制點確認",
                    "count": 3,
                    "date": "10/12",
                    "status": "已結",
                    "messages": [
                        "10/13 09:20 · 林課長：請提供初測成果圖供審閱。",
                        "10/13 15:40 · 永祥：初測成果圖已整理完成。",
                        "10/14 10:10 · 林課長：已收到成果圖，謝謝。",
                    ],
                },
                {
                    "serial": "12089",
                    "title": "北側管線初測圖提送",
                    "count": 2,
                    "date": "10/18",
                    "status": "已回",
                    "messages": [
                        "10/20 09:00 · 林課長：請依工作指示單調整。",
                        "10/20 11:10 · 永祥：已收到，安排核對中。",
                        "10/21 09:20 · 林課長：範圍以附件標示為準。",
                        "10/21 15:30 · 永祥：修正內容已收到，待確認後回覆。",
                    ],
                },
            ],
        },
        {
            "code": "C114109",
            "name": "台塑 北側管線測量",
            "full_title": "台塑麥寮廠區北側管線測量與無人機影像判釋",
            "client": "台灣塑膠工業股份有限公司",
            "pm": "吳柏頤",
            "admin_owner": "行政羅薇",
            "phase": "mine",
            "when": "今天 17:00",
            "next": "待你確認修正圖回信",
            "who": "古恆安",
            "reminder": "古恆安請你寄北側修正圖給吳工程師，對方禁外網已改附 PDF",
            "facts": ["合約總額 480,000 元", "已收 432,000 元", "未收 48,000 元"],
            "contact": "吳工程師",
            "addr": "wu.fp@fpg.com.tw",
            "host": "fpg.com.tw",
            "subj": "北側管線測量｜修正圖提送",
            "text": "吳工程師您好：\n北側管線修正圖已完成，隨信附上對外版 PDF，敬請查收。\n如有需補充之處，歡迎回覆告知，謝謝。\n詠翔測量工程有限公司 敬上",
            "file": "C114109_北側管線修正圖_對外版.pdf",
            "sum": 480000,
            "received": 432000,
            "allowed": [480000, 432000, 48000],
            "bill": "本案上次請款為 10/05（第二期款 240,000 元，已於 10/16 入帳）。",
            "message": "吳工程師：麻煩協助提供北側修正圖，我們收到後就安排後續作業，謝謝。",
            "internal": "古恆安：請幫我把北側管線修正圖寄給台塑吳工程師，記得台塑信箱會擋雲端連結。",
            "latest": "審查意見修正與補測回覆",
            "serial": 12092,
            "cross": "C114110",
            "sort_order": 2,
            "is_pinned_default": True,
            "threads": [
                {
                    "serial": "12081",
                    "title": "開工範圍與控制點確認",
                    "count": 3,
                    "date": "10/12",
                    "status": "已結",
                    "messages": [
                        "10/13 09:20 · 吳工程師：請提供初測成果圖供審閱。",
                        "10/13 15:40 · 永祥：初測成果圖已整理完成。",
                        "10/14 10:10 · 吳工程師：已收到成果圖，謝謝。",
                    ],
                },
                {
                    "serial": "12089",
                    "title": "北側管線初測圖提送",
                    "count": 2,
                    "date": "10/18",
                    "status": "已回",
                    "messages": [
                        "10/20 09:00 · 吳工程師：請依工作指示單調整。",
                        "10/20 11:10 · 永祥：已收到，安排核對中。",
                        "10/21 09:20 · 吳工程師：範圍以附件標示為準。",
                        "10/21 15:30 · 永祥：修正內容已收到，待確認後回覆。",
                    ],
                },
            ],
        },
        {
            "code": "C115042",
            "name": "高鐵 邊坡加密監測",
            "full_title": "台灣高鐵苗栗段邊坡加密監測與北段加測工程",
            "client": "台灣高速鐵路股份有限公司",
            "pm": "吳柏頤",
            "admin_owner": "行政羅薇",
            "phase": "mine",
            "when": "14:00",
            "next": "待你寄出口頭加測確認信",
            "who": "吳柏頤",
            "reminder": "吳柏頤記下陳工程師口頭加測兩百公尺，請寄信書面確認",
            "facts": ["合約總額 1,250,000 元", "加測預估 85,000 元"],
            "contact": "陳工程師",
            "addr": "chen@thsrc.com.tw",
            "host": "thsrc.com.tw",
            "subj": "邊坡加密監測｜北段加測內容確認",
            "text": "陳工程師您好：\n\n依 10/24 電話討論，北段邊坡擬加測 200m，預估 85,000 元，預計下週三前提送高程表。\n敬請回信確認範圍、金額與交件時間，收到書面確認後安排辦理。\n\n詠翔測量工程有限公司 敬上",
            "file": "C115042_北段加測範圍確認.pdf",
            "sum": 1250000,
            "received": None,
            "allowed": [1250000, 85000],
            "bill": "查無資料：本案尚無可核對的請款日期，請洽行政羅薇確認。",
            "message": "陳工程師：北段邊坡加測範圍先照電話討論，麻煩寄一封確認信給我。",
            "verbal": "🗣 10/24 16:20 通話口述：高鐵陳工程師口頭請託北段邊坡加測 200m，下週三前提送高程表",
            "latest": "北段加測口頭確認",
            "serial": 12092,
            "sort_order": 3,
            "is_pinned_default": True,
        },
        {
            "code": "Q-202610-07",
            "name": "南亞詢價",
            "full_title": "南亞塑膠廠區測量詢價與範圍評估",
            "client": "南亞塑膠工業股份有限公司",
            "pm": "吳柏頤",
            "admin_owner": "行政羅薇",
            "phase": "mine",
            "when": "今天 18:00",
            "next": "待你確認新詢價報價草稿",
            "who": "行政羅薇",
            "reminder": "南亞張專員來信詢價廠區測量，新聯絡人尚未確認有權",
            "facts": ["初步估價 320,000 元"],
            "contact": "張專員",
            "addr": "chang.ny@npc.com.tw",
            "host": "npc.com.tw",
            "subj": "南亞廠區測量｜詢價內容確認",
            "text": "張專員您好：\n\n已收到廠區測量需求，初步估價為 320,000 元，正式報價待範圍確認後提供。\n煩請提供測量範圍與貴公司授權窗口，謝謝。\n\n詠翔測量工程有限公司 敬上",
            "file": "南亞_廠區測量範圍示意.pdf",
            "sum": 320000,
            "received": None,
            "allowed": [320000],
            "bill": "查無資料：目前為詢價階段，尚無請款紀錄。",
            "message": "張專員：您好，想詢問南亞廠區測量的報價，附件是預計施作的範圍。",
            "internal": "行政羅薇：這是新窗口，請先確認授權再討論付款與發票條件。",
            "latest": "廠區測量詢價",
            "serial": 12092,
            "inquiry": True,
            "sort_order": 4,
            "is_pinned_default": True,
        },
        {
            "code": "C115094",
            "name": "中鼎 廠區控制點測量",
            "full_title": "中鼎工程廠區控制點測量與高屏溪斷面聯測",
            "client": "中鼎工程股份有限公司",
            "pm": "鍾智偉",
            "admin_owner": "行政羅薇",
            "phase": "mine",
            "when": "昨天",
            "next": "待你登記收件通知不用回",
            "who": "行政羅薇",
            "reminder": "卓工程師來信通知下週二進場會勘時間，不用回信請登記",
            "facts": ["合約總額 520,000 元", "已收 260,000 元"],
            "contact": "卓工程師",
            "addr": "cho@ctci.com",
            "host": "ctci.com",
            "subj": "廠區控制點測量｜會勘通知收訖",
            "text": "卓工程師您好：\n\n已收到下週二進場會勘通知，我們將準時出席，謝謝。\n\n詠翔測量工程有限公司 敬上",
            "file": "C115094_會勘範圍圖.pdf",
            "sum": 520000,
            "received": 260000,
            "allowed": [520000, 260000],
            "bill": "本案上次請款為 09/28（第一期款 260,000 元，已於 10/10 入帳）。",
            "message": "卓工程師：下週二上午十點於北門集合會勘，請準時出席。",
            "internal": "行政羅薇：這封是單純通知，可按不用回直接登記拿號。",
            "latest": "會勘時間通知",
            "serial": 12092,
            "sort_order": 5,
            "is_pinned_default": True,
        },
        {
            "code": "C115031",
            "name": "中工 道路高程複測",
            "full_title": "中華工程道路高程複測與橫斷面檢核",
            "client": "中華工程股份有限公司",
            "pm": "吳柏頤",
            "admin_owner": "行政羅薇",
            "phase": "analyzing",
            "when": "剛剛",
            "next": "整理中",
            "who": "吳柏頤",
            "reminder": "吳柏頤請你確認道路高程複測的圖面回覆",
            "facts": ["合約總額 640,000 元"],
            "contact": "李工程師",
            "addr": "lee@bes.com.tw",
            "host": "bes.com.tw",
            "subj": "道路高程複測｜圖面回覆",
            "text": "李工程師您好：\n\n道路高程複測圖面已核對完成，隨信附上對外版 PDF，敬請查收。\n\n詠翔測量工程有限公司 敬上",
            "file": "C115031_道路高程複測圖面.pdf",
            "sum": 640000,
            "received": None,
            "allowed": [640000],
            "bill": "查無資料：請款紀錄仍在核對，請稍後再查。",
            "message": "李工程師：請協助確認道路高程複測圖面的修正內容。",
            "internal": "吳柏頤：請先核對圖面，再準備回覆。",
            "latest": "道路高程複測圖面核對",
            "serial": 12090,
            "sort_order": 6,
            "is_pinned_default": True,
        },
        {
            "code": "C115018",
            "name": "台電 彰濱變電所測量",
            "full_title": "台灣電力彰濱變電所地形與沉陷測量",
            "client": "台灣電力股份有限公司",
            "pm": "吳柏頤",
            "admin_owner": "行政羅薇",
            "phase": "pending",
            "when": "10/22",
            "next": "#12088 期末成果已寄出",
            "who": "你",
            "reminder": "你已寄出彰濱變電所期末成果，等王工程師確認驗收",
            "facts": ["報價總額 580,000 元"],
            "contact": "王工程師",
            "addr": "wang@tpc.com.tw",
            "host": "tpc.com.tw",
            "sum": 580000,
            "received": None,
            "allowed": [580000],
            "bill": "查無資料：報價尚待確認，目前無請款紀錄。",
            "message": "王工程師：期末成果已收到，我們確認驗收範圍後回覆。",
            "latest": "期末成果已寄出",
            "serial": 12088,
            "sort_order": 7,
            "is_pinned_default": True,
        },
        {
            "code": "C114512",
            "name": "亞東 廠區控制點測量",
            "full_title": "亞東石化廠區控制點測量與成果歸檔",
            "client": "遠東新世紀／亞東石化股份有限公司",
            "pm": "吳柏頤",
            "admin_owner": "行政羅薇",
            "phase": "quiet",
            "when": "10/18",
            "next": "#12079 成果圖已結案歸檔",
            "who": "行政羅薇",
            "reminder": "你已完成成果圖歸檔，本案暫無待辦",
            "facts": ["合約總額 360,000 元", "已收 360,000 元"],
            "contact": "周工程師",
            "addr": "chou@fenc.com",
            "host": "fenc.com",
            "sum": 360000,
            "received": 360000,
            "allowed": [360000],
            "bill": "本案上次請款為 10/08（尾款 180,000 元，已於 10/18 入帳）。",
            "message": "周工程師：成果圖已收到，謝謝協助，本案可結案。",
            "latest": "成果圖已結案歸檔",
            "serial": 12079,
            "sort_order": 8,
            "is_pinned_default": True,
        },
        {
            "code": "C114110",
            "name": "台塑 南側管線測量",
            "full_title": "公路局中彰大橋3D多音束河床細部掃描與南側管線測量",
            "client": "台灣塑膠工業股份有限公司",
            "pm": "吳柏頤",
            "admin_owner": "行政羅薇",
            "phase": "quiet",
            "when": "昨天",
            "next": "#12086 修正範圍已確認",
            "who": "古恆安",
            "reminder": "吳工程師已確認南側修正範圍，等待下次排程",
            "facts": ["合約總額 420,000 元"],
            "contact": "吳工程師",
            "addr": "wu.fp@fpg.com.tw",
            "host": "fpg.com.tw",
            "sum": 420000,
            "received": None,
            "allowed": [420000],
            "bill": "查無資料：本案目前無可核對的請款紀錄。",
            "message": "吳工程師：南側範圍已確認，照原排程辦理即可。",
            "latest": "修正範圍已確認",
            "serial": 12086,
            "group": True,
            "sort_order": 9,
            "is_pinned_default": True,
        },
        {
            "code": "C114488",
            "name": "華新 楊梅廠界測量",
            "full_title": "華新麗華楊梅廠界測量與樁位成果確認",
            "client": "華新麗華股份有限公司",
            "pm": "吳柏頤",
            "admin_owner": "行政羅薇",
            "phase": "quiet",
            "when": "10/20",
            "next": "#12083 廠界成果已收訖",
            "who": "行政羅薇",
            "reminder": "許專員已確認廠界成果，本案暫無待辦",
            "facts": ["合約總額 280,000 元", "已收 280,000 元"],
            "contact": "許專員",
            "addr": "hsu@walsin.com",
            "host": "walsin.com",
            "sum": 280000,
            "received": 280000,
            "allowed": [280000],
            "bill": "本案上次請款為 10/15（尾款 140,000 元，已於 10/20 入帳）。",
            "message": "許專員：廠界成果已收訖，謝謝。",
            "latest": "廠界成果已收訖",
            "serial": 12083,
            "group": True,
            "sort_order": 10,
            "is_pinned_default": True,
        },
    ]


def get_featured_real_cases():
    """Featured real cases from PostgreSQL / Bitable / Sheet 2 explicitly highlighted for search & inspection."""
    return {
        "C115094-4": {
            "code": "C115094-4",
            "name": "七河斷面二期",
            "full_title": "115年度高屏溪水系上游河段及東港溪水系主、支流河段大斷面測量計畫-第二期驗收",
            "client": "經濟部水利署第七河川分署",
            "pm": "鍾智偉",
            "admin_owner": "行政羅薇",
            "phase": "mine",
            "when": "10/23",
            "next": "待確認第二期驗收斷面圖冊回信",
            "who": "鍾智偉",
            "reminder": "水利署七河分署楊志雲副工程司來信確認高屏溪水系大斷面第二期驗收成果",
            "facts": ["合約總額 1,450,400 元", "已收 1,015,280 元", "未收 435,120 元"],
            "contact": "楊志雲",
            "addr": "cy.yang@wra07.gov.tw",
            "host": "wra07.gov.tw",
            "subj": "高屏溪水系大斷面測量｜第二期驗收成果圖冊提送",
            "text": "楊志雲副工程司您好：\n\n115年度高屏溪水系上游河段及東港溪水系主、支流河段大斷面測量計畫（第二期驗收）修正圖冊已核對完成，隨信附上對外版 PDF 供審閱。\n如有需補充之處，歡迎隨時告知，謝謝。\n\n詠翔測量工程有限公司 敬上",
            "file": "C115094-4_高屏溪大斷面第二期驗收圖冊.pdf",
            "sum": 1450400,
            "received": 1015280,
            "allowed": [1450400, 1015280, 435120, 1740150],
            "bill": "本案第一期款 1,015,280 元已入帳，第二期驗收款 435,120 元待驗收後請款。",
            "message": "楊志雲：請提供高屏溪水系大斷面第二期驗收修正對照表與斷面圖 PDF。",
            "internal": "鍾智偉：水深與大斷面二期驗收資料已整理妥當，請確認後寄給七河分署楊志雲。",
            "latest": "第二期驗收成果與修正對照表提送",
            "serial": 12062,
            "threads": [
                {
                    "serial": "11420",
                    "title": "高屏溪上游大斷面測量第二期開工與控制點提送",
                    "count": 3,
                    "date": "07/08",
                    "status": "已結",
                    "messages": [
                        "07/08 09:30 · 楊志雲：第二期工作指示單已核發，請提送施測進度表。",
                        "07/08 16:10 · 永祥（鍾智偉）：施測進度表與控制點檢測成果已隨信附上。",
                        "07/09 10:05 · 楊志雲：已收悉，請依期程進場施測。",
                    ],
                },
                {
                    "serial": "11895",
                    "title": "東港溪主支流斷面測量成果圖初審回覆",
                    "count": 4,
                    "date": "09/18",
                    "status": "已回",
                    "messages": [
                        "09/18 11:00 · 楊志雲：初審意見如附件，請修正斷面樁號標示。",
                        "09/19 15:20 · 永祥（鍾智偉）：已完成斷面樁號與高程對照修正。",
                    ],
                },
            ],
        },
        "C115025": {
            "code": "C115025",
            "name": "凱達 東石南橋改建",
            "full_title": "台17線東石南橋改建工程（控制測量與橋墩地形監測）",
            "client": "凱達營造股份有限公司",
            "pm": "吳柏頤",
            "admin_owner": "行政羅薇",
            "phase": "mine",
            "when": "10/21",
            "next": "待確認東石南橋測量報告與計價回覆",
            "who": "吳柏頤",
            "reminder": "凱達營造陳主任來信確認台17線東石南橋改建工程成果報告與本期計價金額",
            "facts": ["合約總額 398,360 元", "已收 199,180 元", "未收 199,180 元"],
            "contact": "陳主任",
            "addr": "chen.kd@kaida-const.com.tw",
            "host": "kaida-const.com.tw",
            "subj": "台17線東石南橋改建工程｜測量成果報告提送",
            "text": "陳主任您好：\n\n台17線東石南橋改建工程測量成果報告已整理完成，合約總額 398,360 元（本期應計價 199,180 元），隨信附上對外版 PDF 敬請查收。\n\n詠翔測量工程有限公司 敬上",
            "file": "C115025_台17線東石南橋測量報告.pdf",
            "sum": 398360,
            "received": 199180,
            "allowed": [398360, 199180],
            "bill": "本案第一期計價 199,180 元已入帳，第二期 199,180 元成果報告已提送待請款。",
            "message": "陳主任：東石南橋改建工程的測量報告請於本週提供，以便辦理本期計價。",
            "internal": "吳柏頤：報價編號 115032 確認單金額 398,360 元，報告已完成可提送。",
            "latest": "東石南橋測量成果報告與計價核對",
            "serial": 12041,
            "threads": [
                {
                    "serial": "10812",
                    "title": "台17線東石南橋改建工程報價與確認單回傳",
                    "count": 3,
                    "date": "01/22",
                    "status": "已結",
                    "messages": [
                        "01/13 10:15 · 陳主任：請提供台17線東石南橋改建工程測量報價單。",
                        "01/22 14:30 · 永祥（吳柏頤）：已回傳確認單（報編 115032，金額 398,360 元）。",
                    ],
                },
                {
                    "serial": "11540",
                    "title": "橋墩基礎控制點檢測與點工加測確認",
                    "count": 3,
                    "date": "06/08",
                    "status": "已回",
                    "messages": [
                        "06/08 09:00 · 陳主任：橋墩點工複測範圍請協助安排。",
                        "06/08 17:10 · 永祥（吳柏頤）：點工複測成果已整理完畢並附上。",
                    ],
                },
            ],
        },
        "C115168": {
            "code": "C115168",
            "name": "凱煬 麥寮六輕測量",
            "full_title": "雲林縣麥寮鄉六輕段15地號地形測量",
            "client": "凱煬太陽能股份有限公司",
            "pm": "吳柏頤",
            "admin_owner": "行政羅薇",
            "phase": "mine",
            "when": "10/19",
            "next": "待確認六輕段15地號地形圖交付",
            "who": "古恆安",
            "reminder": "凱煬太陽能林經理來信確認雲林麥寮六輕段15地號地形測量成果圖",
            "facts": ["合約總額 194,900 元", "已收 194,900 元", "未收 0 元"],
            "contact": "林經理",
            "addr": "lin@kaiyang-solar.com.tw",
            "host": "kaiyang-solar.com.tw",
            "subj": "雲林縣麥寮鄉六輕段15地號地形測量｜成果圖提送",
            "text": "林經理您好：\n\n雲林縣麥寮鄉六輕段15地號地形測量成果圖已核對完成，本案款項 194,900 元已全數結清，隨信附上最終成果圖 PDF，敬請查收。\n\n詠翔測量工程有限公司 敬上",
            "file": "C115168_麥寮六輕段15地號地形圖.pdf",
            "sum": 194900,
            "received": 194900,
            "allowed": [194900],
            "bill": "本案合約總額 194,900 元已於 08/15 全數入帳結清。",
            "message": "林經理：請提供雲林縣麥寮鄉六輕段15地號地形測量最終成果圖。",
            "internal": "古恆安：外業與內業製圖均已完成，款項已入帳，可直接提供成果圖。",
            "latest": "六輕段15地號地形測量成果交付",
            "serial": 12018,
            "threads": [
                {
                    "serial": "11388",
                    "title": "雲林麥寮六輕段15地號地形測量詢價與確認單",
                    "count": 3,
                    "date": "06/11",
                    "status": "已結",
                    "messages": [
                        "05/18 11:20 · 林經理：請提供麥寮六輕段15地號地形測量報價。",
                        "06/11 16:00 · 永祥：報價編號 115337（194,900 元）確認單已回傳。",
                    ],
                },
                {
                    "serial": "11602",
                    "title": "六輕段15地號外業施測進場與圖面初稿提送",
                    "count": 2,
                    "date": "07/09",
                    "status": "已回",
                    "messages": [
                        "06/29 08:30 · 永祥：今日外業進場施測。",
                        "07/09 17:00 · 永祥：地形圖初稿已提送審閱。",
                    ],
                },
            ],
        },
        "C115211-01A": {
            "code": "C115211-01A",
            "name": "緯穎美國建模",
            "full_title": "廠區掃描與數位建模(美國) - 緯穎科技服務",
            "client": "緯穎科技服務股份有限公司",
            "pm": "吳柏頤",
            "admin_owner": "行政羅薇",
            "phase": "mine",
            "when": "10/22",
            "next": "待確認美國廠區數位建模交付期程",
            "who": "吳柏頤",
            "reminder": "緯穎科技黃政廷來信確認美國廠區 3D 掃描與數位建模第一階段成果與追加範圍",
            "facts": ["合約總額 1,680,000 元", "已收 840,000 元", "未收 840,000 元"],
            "contact": "黃政廷",
            "addr": "ct.huang@wiwynn.com",
            "host": "wiwynn.com",
            "subj": "廠區掃描與數位建模(美國)｜第一階段模型成果提送",
            "text": "黃政廷先生您好：\n\n美國廠區掃描與數位建模第一階段點雲與 BIM 模型已核對完成，隨信附上成果檢核表 PDF，敬請查收。\n\n詠翔測量工程有限公司 敬上",
            "file": "C115211-01A_美國廠區數位建模檢核表.pdf",
            "sum": 1680000,
            "received": 840000,
            "allowed": [1680000, 840000],
            "bill": "本案第一期款 840,000 元已入帳，尾款 840,000 元待模型驗收後請款。",
            "message": "黃政廷：請協助確認美國廠區掃描數位建模第一階段成果與追加管線建模時程。",
            "internal": "吳柏頤：報編 115471-01A 由我負責，第一階段檢核表可直接寄給緯穎黃政廷。",
            "latest": "美國廠區數位建模成果與追加確認",
            "serial": 12075,
            "threads": [
                {
                    "serial": "11720",
                    "title": "美國廠區 3D 掃描與數位建模規格確認",
                    "count": 4,
                    "date": "07/28",
                    "status": "已結",
                    "messages": [
                        "06/30 14:00 · 黃政廷：請提供美國廠區 3D 雷射掃描與建模報價。",
                        "07/17 16:20 · 永祥（吳柏頤）：報編 115471-01 確認單已回傳。",
                    ],
                },
                {
                    "serial": "11910",
                    "title": "第一階段廠區點雲與數位模型初稿提送",
                    "count": 3,
                    "date": "08/17",
                    "status": "已回",
                    "messages": [
                        "08/05 10:30 · 永祥（吳柏頤）：外業掃描點雲資料已完成拼接。",
                        "08/17 15:00 · 黃政廷：收到初稿，請補充機電管線圖層標示。",
                    ],
                },
            ],
        },
    }


def load_merged_real_cases():
    """Merge public.case (555 codes), V3 cases (853), and Quotes (423)."""
    cases_by_code = {}

    rows = db.query(
        """
        SELECT jsonb_build_object(
            'case_code', c.case_code,
            'title', COALESCE(to_jsonb(c)->>'title', ''),
            'client_name', COALESCE(NULLIF(to_jsonb(c)->>'client',''), cu.name, ''),
            'pm_name', COALESCE(e_pm.full_name, ''),
            'status', COALESCE(to_jsonb(c)->>'status', ''),
            'quoted_total', COALESCE(to_jsonb(c)->>'quoted_total', '0'),
            'contract_total', COALESCE(to_jsonb(c)->>'contract_total', '0'),
            'received_total', COALESCE(to_jsonb(c)->>'received_total', '0')
        )
        FROM public.case c
        LEFT JOIN public.customer cu ON cu.id = c.customer_id
        LEFT JOIN public.employee e_pm ON e_pm.id = c.pm_employee_id
        WHERE c.case_code IS NOT NULL AND btrim(c.case_code) <> ''
        ORDER BY c.case_code DESC
        """
    )
    formal_pm = {r["case_code"]: identity_text(r.get("pm_name")) or "待指派" for r in rows}
    for r in rows:
        raw_code = clean_text(r.get("case_code") or "")
        m_c = re.match(r"^([A-Za-z]?\d{4,7}(?:-[0-9A-Za-z]+)?)", raw_code)
        if not m_c or len(m_c.group(1)) > 13:
            continue
        code = m_c.group(1)
        cases_by_code[code] = {
            "code": code,
            "full_title": clean_text(r.get("title") or "") or f"{code} 測量工程",
            "client": clean_text(r.get("client_name") or "") or "永祥合作業主",
            "pm": identity_text(r.get("pm_name")) or "待指派",
            "contact": "工程窗口",
            "addr": "contact@client.com.tw",
            "sum": int(float(r.get("contract_total") or r.get("quoted_total") or 0)) or 350000,
            "received": int(float(r.get("received_total") or 0)),
        }

    v3_path = Path("/workspace/quote-settlement/daily/work/rec_tblWsSaOcy4nKuGI.json")
    if not v3_path.exists():
        v3_path = ROOT / "rec_tblWsSaOcy4nKuGI.json"
    if v3_path.exists():
        v3_rows = json.loads(v3_path.read_text(encoding="utf-8"))
        for r in v3_rows:
            raw_code = clean_text(r.get("案件編號") or r.get("工程編號") or "")
            m_c = re.match(r"^([A-Za-z]?\d{4,7}(?:-[0-9A-Za-z]+)?)", raw_code)
            if not m_c or len(m_c.group(1)) > 13:
                continue
            code = m_c.group(1)
            title = clean_text(r.get("案件名稱") or r.get("工程名稱") or "")
            client = clean_text(r.get("業主") or r.get("行號單位") or "")
            amt_raw = str(r.get("實際合約金額") or r.get("合約金額") or "0")
            amt = int(float(re.sub(r"[^\d.]", "", amt_raw) or 0))
            if amt > 500_000_000:
                amt = 680000
            rec_raw = str(r.get("累計已入帳") or r.get("案件已入帳") or "0")
            rec = int(float(re.sub(r"[^\d.]", "", rec_raw) or 0))
            cur = cases_by_code.get(code, {"code": code, "pm": "待指派", "contact": "專案窗口", "addr": "window@client.com.tw"})
            if title:
                cur["full_title"] = title
            if client:
                cur["client"] = client
            if amt > 0:
                cur["sum"] = amt
            if rec > 0:
                cur["received"] = min(rec, cur.get("sum", rec))
            cases_by_code[code] = cur

    q423_path = Path("/workspace/quote-settlement/daily/work/rec_tblENZvYAya93Twa.json")
    if not q423_path.exists():
        q423_path = ROOT / "rec_tblENZvYAya93Twa.json"
    if q423_path.exists():
        q423_rows = json.loads(q423_path.read_text(encoding="utf-8"))
        for r in q423_rows:
            raw_code = clean_text(r.get("工程編號") or r.get("案件編號") or r.get("報價編號") or "")
            m_c = re.match(r"^([A-Za-z]?\d{4,7}(?:-[0-9A-Za-z]+)?)", raw_code)
            if not m_c or len(m_c.group(1)) > 13:
                continue
            code = m_c.group(1)
            title = clean_text(r.get("工程名稱") or r.get("案件名稱") or r.get("工程簡稱") or "")
            client = clean_text(r.get("行號單位") or r.get("業主") or "")
            contact = identity_text(r.get("連絡人"))
            email = identity_text(r.get("E-mail"))
            pm_val = r.get("案件負責人") or r.get("報價負責人")
            pm_name = ""
            if isinstance(pm_val, list) and pm_val and isinstance(pm_val[0], dict):
                pm_name = identity_text(pm_val[0].get("name"))
            amt_raw = str(r.get("實際合約金額") or r.get("契約價格(未稅)") or r.get("工程明細預算") or "0")
            amt = int(float(re.sub(r"[^\d.]", "", amt_raw) or 0))
            cur = cases_by_code.get(code, {"code": code, "pm": "待指派", "contact": "工程窗口", "addr": "contact@client.com.tw"})
            if title:
                cur["full_title"] = title
            if client:
                cur["client"] = client
            if contact:
                cur["contact"] = contact
            if email and "@" in email:
                cur["addr"] = email.split()[0].strip(";,")
            if pm_name:
                cur["pm"] = pm_name
            if amt > 0:
                cur["sum"] = amt
            cases_by_code[code] = cur

    for code, pm in formal_pm.items():
        if code in cases_by_code:
            cases_by_code[code]["pm"] = pm
    return cases_by_code


def build_case_record(code: str, raw: dict, idx: int) -> dict:
    full_title = clean_text(raw.get("full_title") or f"{code} 測量專案")
    client = clean_text(raw.get("client") or "合作業主")
    pm = identity_text(raw.get("pm")) or "待指派"
    contact = identity_text(raw.get("contact")) or "工程窗口"
    addr = identity_text(raw.get("addr")) or "service@client.com.tw"
    if "@" not in addr:
        addr = "service@client.com.tw"
    host = addr.split("@")[-1]
    sum_amt = int(raw.get("sum") or 450000)
    rec_amt = int(raw.get("received") or 0)
    unrec_amt = max(0, sum_amt - rec_amt)
    short_name = raw.get("name") or make_short_name(code, client, full_title)
    max_len = max(2, 18 - len(code) - 1)
    if len(short_name) > max_len:
        short_name = short_name[:max_len].strip()

    serial_base = 10500 + (idx % 1550)
    s1 = serial_base - 120
    s2 = serial_base - 45
    s3 = serial_base

    facts = [
        f"合約總額 {sum_amt:,} 元",
        f"已收 {rec_amt:,} 元",
        f"未收 {unrec_amt:,} 元",
    ]
    allowed = list({sum_amt, rec_amt, unrec_amt})
    bill = (
        f"本案合約總額 {sum_amt:,} 元，已入帳 {rec_amt:,} 元，未收款 {unrec_amt:,} 元（行政羅薇核對）。"
        if rec_amt > 0
        else f"本案合約總額 {sum_amt:,} 元，目前尚無入帳紀錄，請洽行政羅薇確認。"
    )
    threads = raw.get("threads") or [
        {
            "serial": str(s1),
            "title": f"{short_name}開工範圍與控制點確認",
            "count": 3,
            "date": "08/15",
            "status": "已結",
            "messages": [
                f"08/15 09:20 · {contact}：請提供「{full_title}」施測進度與控制點座標表。",
                f"08/15 15:40 · 永祥（{pm}）：控制點座標表與進場計畫已整理完成並隨信附上。",
                f"08/16 10:10 · {contact}：已收到，請依排程辦理。",
            ],
        },
        {
            "serial": str(s2),
            "title": f"{short_name}初測成果圖提送與審查回覆",
            "count": 2,
            "date": "09/20",
            "status": "已回",
            "messages": [
                f"09/20 09:00 · {contact}：請提供本階段測量成果圖 PDF 供內部審查。",
                f"09/20 14:30 · 永祥（{pm}）：初測成果圖 PDF 已隨信附上，敬請審閱。",
            ],
        },
    ]

    return {
        "code": code,
        "name": short_name,
        "full_title": full_title,
        "client": client,
        "pm": pm,
        "admin_owner": "行政羅薇",
        "phase": raw.get("phase") or "mine",
        "when": raw.get("when") or "10/20",
        "next": clean_text(raw.get("next") or f"#{s3} 待確認成果回覆"),
        "who": clean_text(raw.get("who") or pm),
        "reminder": clean_text(raw.get("reminder") or f"{client}（{contact}）來信確認「{full_title}」成果與計價進度"),
        "facts": facts,
        "contact": contact,
        "addr": addr,
        "host": host,
        "subj": clean_text(raw.get("subj") or f"{short_name}｜測量成果提送與進度確認"),
        "text": clean_text(
            raw.get("text")
            or f"{contact}您好：\n\n有關「{full_title}」（工編 {code}）之測量成果圖冊已核對完成，隨信附上對外版 PDF 供貴單位審閱。\n如有需補充說明之處，歡迎隨時回覆告知，謝謝。\n\n詠翔測量工程有限公司 敬上"
        ),
        "file": clean_text(raw.get("file") or f"{code}_測量成果圖_對外版.pdf"),
        "sum": sum_amt,
        "received": rec_amt,
        "allowed": allowed,
        "bill": clean_text(raw.get("bill") or bill),
        "message": clean_text(raw.get("message") or f"{contact}：請協助提供「{full_title}」最新測量成果圖與進度說明，謝謝。"),
        "internal": clean_text(raw.get("internal") or f"{pm}：本案由{pm}負責、行政羅薇協辦，圖面已核對完成可寄出。"),
        "latest": clean_text(raw.get("latest") or "測量成果與驗收進度確認"),
        "serial": int(raw.get("serial") or s3),
        "sort_order": int(raw.get("sort_order") or (100 + idx)),
        "is_pinned_default": bool(raw.get("is_pinned_default", False)),
        "group": bool(raw.get("group", False)),
        "inquiry": bool(raw.get("inquiry", False)),
        "threads": threads,
    }


def seed_database():
    cur_db = db.assert_not_prod_db()
    assert cur_db != "yongxiang_plumb", f"FATAL: Forbidden from connecting to production DB (got {cur_db})"

    initial_10 = get_initial_10_cases()
    featured_map = get_featured_real_cases()
    merged_raw = load_merged_real_cases()

    all_cases = []
    seen_codes = set()

    for c in initial_10:
        code = c["code"]
        seen_codes.add(code)
        if "threads" not in c:
            c["threads"] = [
                {
                    "serial": "12081",
                    "title": "開工範圍與控制點確認",
                    "count": 3,
                    "date": "10/12",
                    "status": "已結",
                    "messages": [
                        f"10/13 09:20 · {c['contact']}：請提供初測成果圖供審閱。",
                        "10/13 15:40 · 永祥：初測成果圖已整理完成。",
                        f"10/14 10:10 · {c['contact']}：已收到成果圖，謝謝。",
                    ],
                },
                {
                    "serial": "12089",
                    "title": "北側管線初測圖提送",
                    "count": 2,
                    "date": "10/18",
                    "status": "已回",
                    "messages": [
                        f"10/20 09:00 · {c['contact']}：請依工作指示單調整。",
                        "10/20 11:10 · 永祥：已收到，安排核對中。",
                        f"10/21 09:20 · {c['contact']}：範圍以附件標示為準。",
                        "10/21 15:30 · 永祥：修正內容已收到，待確認後回覆。",
                    ],
                },
            ]
        all_cases.append(c)

    idx = 11
    for fcode, fc in featured_map.items():
        if fcode in seen_codes:
            continue
        seen_codes.add(fcode)
        fc["sort_order"] = idx
        fc["is_pinned_default"] = False
        all_cases.append(fc)
        idx += 1

    for code, raw in sorted(merged_raw.items()):
        if code in seen_codes:
            continue
        seen_codes.add(code)
        all_cases.append(build_case_record(code, raw, idx))
        idx += 1

    for item in all_cases:
        formal = merged_raw.get(item["code"])
        if formal:
            item["pm"] = formal["pm"]

    sql_parts = [
        """
        BEGIN;
        DELETE FROM public.serial_assignment WHERE fingerprint LIKE 'yezhu-ui:%';
        UPDATE public.serial_allocator SET shadow_next_serial = -12105 WHERE org_id = 'YX';

        DROP TABLE IF EXISTS public.yezhu_workbench_case CASCADE;
        CREATE TABLE public.yezhu_workbench_case (
            code text PRIMARY KEY,
            org_id text NOT NULL DEFAULT 'YX',
            name text NOT NULL,
            full_title text NOT NULL,
            client text NOT NULL,
            contact text NOT NULL,
            addr text NOT NULL,
            host text NOT NULL,
            pm text NOT NULL,
            admin_owner text NOT NULL DEFAULT '行政羅薇',
            phase text NOT NULL DEFAULT 'mine',
            when_label text NOT NULL DEFAULT '今天',
            next_label text NOT NULL DEFAULT '',
            who text NOT NULL DEFAULT '吳柏頤',
            reminder text NOT NULL DEFAULT '',
            sum_amount bigint,
            received_amount bigint,
            serial integer NOT NULL DEFAULT 12084,
            sort_order integer NOT NULL DEFAULT 1000,
            is_pinned_default boolean NOT NULL DEFAULT false,
            initial_pinned boolean NOT NULL DEFAULT false,
            case_data jsonb NOT NULL,
            initial_case_data jsonb NOT NULL,
            letter_state jsonb,
            initial_letter_state jsonb,
            fix_card jsonb,
            handoffs jsonb NOT NULL DEFAULT '[]'::jsonb,
            verbals jsonb NOT NULL DEFAULT '[]'::jsonb,
            notes jsonb,
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS yezhu_wb_case_pinned_idx
            ON public.yezhu_workbench_case (is_pinned_default, sort_order);
        CREATE INDEX IF NOT EXISTS yezhu_wb_case_client_idx
            ON public.yezhu_workbench_case (client);

        CREATE TABLE IF NOT EXISTS public.yezhu_correspondence_ledger (
            serial_no integer PRIMARY KEY,
            org_id text NOT NULL DEFAULT 'YX',
            serial_label text NOT NULL,
            case_code text NOT NULL,
            client text NOT NULL,
            contact text NOT NULL,
            pm text NOT NULL,
            direction text NOT NULL DEFAULT 'inbound',
            channel text NOT NULL DEFAULT 'email',
            occurred_date text NOT NULL,
            subject text NOT NULL,
            summary text NOT NULL,
            status_label text NOT NULL DEFAULT '已結',
            messages_json jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS yezhu_corr_case_code_idx
            ON public.yezhu_correspondence_ledger (case_code, serial_no DESC);
        CREATE INDEX IF NOT EXISTS yezhu_corr_label_idx
            ON public.yezhu_correspondence_ledger (serial_label);

        CREATE TABLE IF NOT EXISTS public.yezhu_softlock (
            case_code text PRIMARY KEY,
            org_id text NOT NULL DEFAULT 'YX',
            holder text NOT NULL,
            role_key text NOT NULL DEFAULT 'pm',
            locked_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL DEFAULT (now() + interval '90 seconds'),
            active boolean NOT NULL DEFAULT false,
            takeover_by text,
            takeover_note text,
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        DROP TABLE IF EXISTS public.yezhu_workbench_meta CASCADE;
        CREATE TABLE public.yezhu_workbench_meta (
            key text PRIMARY KEY,
            org_id text NOT NULL DEFAULT 'YX',
            pins jsonb NOT NULL DEFAULT '["C114109"]'::jsonb,
            next_serial integer NOT NULL DEFAULT 12106,
            authorized boolean NOT NULL DEFAULT false,
            merged text NOT NULL DEFAULT '',
            quarantine text NOT NULL DEFAULT '',
            admin_claimed text NOT NULL DEFAULT '羅薇',
            roster_mode text NOT NULL DEFAULT 'multi',
            field_mode boolean NOT NULL DEFAULT false,
            followup_dismissed boolean NOT NULL DEFAULT false,
            analyzed boolean NOT NULL DEFAULT false,
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        DROP TABLE IF EXISTS public.switchboard_agent_roster CASCADE;
        CREATE TABLE public.switchboard_agent_roster (
            item_id text PRIMARY KEY,
            org_id text NOT NULL DEFAULT 'YX',
            kind text NOT NULL CHECK (kind IN ('agent', 'connector')),
            title text NOT NULL,
            subtitle text NOT NULL,
            enabled boolean NOT NULL DEFAULT true,
            initial_enabled boolean NOT NULL DEFAULT true,
            is_core boolean NOT NULL DEFAULT false,
            sort_order integer NOT NULL DEFAULT 10,
            assigned_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        TRUNCATE public.yezhu_workbench_case, public.yezhu_correspondence_ledger, public.yezhu_softlock, public.yezhu_workbench_meta, public.switchboard_agent_roster;
        """
    ]

    values_sql = []
    for c in all_cases:
        letter_state = (
            {
                "text": c["text"],
                "subj": c["subj"],
                "stage": "open",
                "serial": None,
                "retries": 0,
                "version": 1,
            }
            if c.get("text")
            else None
        )
        values_sql.append(
            "("
            + ", ".join(
                [
                    db.literal(c["code"]),
                    "'YX'",
                    db.literal(c["name"]),
                    db.literal(c.get("full_title", c["name"])),
                    db.literal(c.get("client", "合作業主")),
                    db.literal(c["contact"]),
                    db.literal(c["addr"]),
                    db.literal(c["host"]),
                    db.literal(c.get("pm", "待指派")),
                    "'行政羅薇'",
                    db.literal(c["phase"]),
                    db.literal(c["when"]),
                    db.literal(c["next"]),
                    db.literal(c["who"]),
                    db.literal(c["reminder"]),
                    db.literal(c.get("sum")),
                    db.literal(c.get("received")),
                    str(int(c.get("serial") or 12084)),
                    str(int(c.get("sort_order") or 1000)),
                    "true" if c.get("is_pinned_default") else "false",
                    "true" if c.get("is_pinned_default") else "false",
                    db.json_sql(c),
                    db.json_sql(c),
                    db.json_sql(letter_state) if letter_state else "NULL",
                    db.json_sql(letter_state) if letter_state else "NULL",
                ]
            )
            + ")"
        )

    sql_parts.append(
        """
        INSERT INTO public.yezhu_workbench_case (
            code, org_id, name, full_title, client, contact, addr, host, pm, admin_owner,
            phase, when_label, next_label, who, reminder, sum_amount, received_amount,
            serial, sort_order, is_pinned_default, initial_pinned, case_data, initial_case_data, letter_state, initial_letter_state
        ) VALUES
        """
        + ",\n".join(values_sql)
        + ";"
    )

    anchored_serials = [
        (12084, "業主往來12084", "C114609", "台灣中油股份有限公司", "林課長", "吳柏頤", "inbound", "email", "10/24", "儲槽沉陷監測期末成果圖催辦", "林課長來信催辦儲槽沉陷期末成果圖與正式圖檔", "待回"),
        (12083, "業主往來12083", "C114488", "華新麗華股份有限公司", "許專員", "吳柏頤", "inbound", "email", "10/20", "楊梅廠界測量成果收訖確認", "許專員確認廠界成果已收訖，本案結案", "已結"),
        (12081, "業主往來12081", "C114109", "台灣塑膠工業股份有限公司", "吳工程師", "吳柏頤", "outbound", "email", "10/12", "北側管線測量開工範圍與控制點確認", "初測成果圖與控制點確認完畢", "已結"),
        (12079, "業主往來12079", "C114512", "遠東新世紀／亞東石化股份有限公司", "周工程師", "吳柏頤", "inbound", "email", "10/18", "亞東廠區控制點測量成果歸檔", "周工程師確認成果圖已收到可結案", "已結"),
        (12075, "業主往來12075", "C115211-01A", "緯穎科技服務股份有限公司", "黃政廷", "吳柏頤", "inbound", "email", "10/18", "美國廠區掃描與數位建模追加管線範圍確認", "黃政廷來信確認第一階段成果與追加管線建模時程", "待回"),
        (12062, "業主往來12062", "C115094-4", "經濟部水利署第七河川分署", "楊志雲", "鍾智偉", "inbound", "email", "10/15", "高屏溪水系大斷面測量第二期驗收修正對照表", "楊志雲副工程司請提送第二期驗收修正對照表與斷面圖冊", "待回"),
        (12041, "業主往來12041", "C115025", "凱達營造股份有限公司", "陳主任", "吳柏頤", "inbound", "email", "10/12", "台17線東石南橋改建工程測量成果報告計價核對", "陳主任請於本週提供東石南橋測量報告以利計價", "待回"),
        (12018, "業主往來12018", "C115168", "凱煬太陽能股份有限公司", "林經理", "吳柏頤", "outbound", "email", "10/05", "雲林縣麥寮鄉六輕段15地號地形測量最終成果交付", "地形測量最終成果圖交付與結案確認", "已結"),
        (11910, "業主往來11910", "C115211-01A", "緯穎科技服務股份有限公司", "黃政廷", "吳柏頤", "outbound", "email", "08/17", "第一階段廠區點雲與數位模型初稿提送", "外業掃描點雲資料拼接完成並提送初稿", "已回"),
        (11895, "業主往來11895", "C115094-4", "經濟部水利署第七河川分署", "楊志雲", "鍾智偉", "outbound", "email", "09/18", "東港溪主支流斷面測量成果圖初審回覆", "完成斷面樁號與高程對照修正", "已回"),
        (11720, "業主往來11720", "C115211-01A", "緯穎科技服務股份有限公司", "黃政廷", "吳柏頤", "outbound", "email", "07/28", "美國廠區 3D 掃描與數位建模規格確認", "報編 115471-01 確認單回傳與規格確認", "已結"),
        (11602, "業主往來11602", "C115168", "凱煬太陽能股份有限公司", "林經理", "吳柏頤", "outbound", "email", "07/09", "六輕段15地號外業施測進場與圖面初稿提送", "外業進場施測與地形圖初稿提送審閱", "已回"),
        (11540, "業主往來11540", "C115025", "凱達營造股份有限公司", "陳主任", "吳柏頤", "outbound", "email", "06/08", "橋墩基礎控制點檢測與點工加測確認", "東石南橋橋墩點工複測成果整理與提送", "已回"),
        (11420, "業主往來11420", "C115094-4", "經濟部水利署第七河川分署", "楊志雲", "鍾智偉", "outbound", "email", "07/08", "高屏溪上游大斷面測量第二期開工與控制點提送", "第二期施測進度表與控制點檢測成果提送", "已結"),
        (11388, "業主往來11388", "C115168", "凱煬太陽能股份有限公司", "林經理", "吳柏頤", "outbound", "email", "06/11", "雲林麥寮六輕段15地號地形測量詢價與確認單", "報價編號 115337（194,900 元）確認單回傳", "已結"),
        (10812, "業主往來10812", "C115025", "凱達營造股份有限公司", "陳主任", "吳柏頤", "outbound", "email", "01/22", "台17線東石南橋改建工程報價與確認單回傳", "報編 115032（398,360 元）確認單回傳", "已結"),
    ]
    anchor_sql = []
    for row in anchored_serials:
        anchor_sql.append(
            "("
            + ", ".join(
                [
                    str(row[0]),
                    "'YX'",
                    db.literal(row[1]),
                    db.literal(row[2]),
                    db.literal(row[3]),
                    db.literal(row[4]),
                    db.literal(row[5]),
                    db.literal(row[6]),
                    db.literal(row[7]),
                    db.literal(row[8]),
                    db.literal(row[9]),
                    db.literal(row[10]),
                    db.literal(row[11]),
                    "'[]'::jsonb",
                ]
            )
            + ")"
        )
    sql_parts.append(
        """
        INSERT INTO public.yezhu_correspondence_ledger (
            serial_no, org_id, serial_label, case_code, client, contact, pm,
            direction, channel, occurred_date, subject, summary, status_label, messages_json
        ) VALUES
        """
        + ",\n".join(anchor_sql)
        + " ON CONFLICT (serial_no) DO NOTHING;"
    )

    sql_parts.append(
        """
        WITH numbered_cases AS (
            SELECT code, full_title, client, contact, pm,
                   row_number() OVER (ORDER BY sort_order, code) - 1 AS rn,
                   count(*) OVER () AS total_c
            FROM public.yezhu_workbench_case
        )
        INSERT INTO public.yezhu_correspondence_ledger (
            serial_no, org_id, serial_label, case_code, client, contact, pm,
            direction, channel, occurred_date, subject, summary, status_label, messages_json
        )
        SELECT
            gs AS serial_no,
            'YX' AS org_id,
            '業主往來' || lpad(gs::text, 4, '0') AS serial_label,
            nc.code AS case_code,
            nc.client,
            nc.contact,
            nc.pm,
            CASE WHEN gs % 2 = 0 THEN 'outbound' ELSE 'inbound' END AS direction,
            CASE WHEN gs % 5 = 0 THEN 'phone_memo' ELSE 'email' END AS channel,
            lpad(((gs % 10) + 1)::text, 2, '0') || '/' || lpad(((gs % 28) + 1)::text, 2, '0') AS occurred_date,
            nc.code || ' ' || left(nc.full_title, 24) || '｜往來紀錄 #' || gs::text AS subject,
            nc.client || '（' || nc.contact || '）與永祥（' || nc.pm || '）就「' || left(nc.full_title, 28) || '」辦理測量圖資與進度確認（#' || gs::text || '）' AS summary,
            CASE WHEN gs > 12000 THEN '已回' ELSE '已結' END AS status_label,
            jsonb_build_array(
                '09:20 · ' || nc.contact || '：請協助確認本階段測量成果與圖面細節。',
                '15:10 · 永祥（' || nc.pm || '）：已核對完成並隨信附上對外版 PDF 紀錄。'
            ) AS messages_json
        FROM generate_series(1, 12084) AS gs
        JOIN numbered_cases nc ON nc.rn = (gs % nc.total_c)
        ON CONFLICT (serial_no) DO NOTHING;

        INSERT INTO public.yezhu_correspondence_ledger (
            serial_no, org_id, serial_label, case_code, client, contact, pm,
            direction, channel, occurred_date, subject, summary, status_label, messages_json
        )
        SELECT
            si.serial_no,
            'YX',
            si.serial_label,
            'C114109',
            '外部來信窗口',
            coalesce(nullif(si.mailbox, ''), '收件信箱'),
            '吳柏頤',
            'inbound',
            si.channel,
            to_char(si.occurred_at AT TIME ZONE 'Asia/Taipei', 'MM/DD'),
            coalesce(nullif(si.payload->>'subject', ''), '來信收件紀錄 ' || si.serial_label),
            '收件信箱自動歸檔紀錄（' || si.serial_label || '）',
            '待回',
            '[]'::jsonb
        FROM public.switchboard_intake si
        WHERE si.serial_no BETWEEN -12105 AND -12085
        ON CONFLICT (serial_no) DO NOTHING;

        INSERT INTO public.yezhu_workbench_meta (
            key, org_id, pins, next_serial, authorized, merged, quarantine, admin_claimed, roster_mode
        ) VALUES (
            'global_state', 'YX', '["C114109"]'::jsonb, 12106, false, '', '', '羅薇', 'multi'
        );
        
        """
    )

    roster_vals = []
    for item in get_initial_agent_roster():
        roster_vals.append(
            "(" + ", ".join([
                db.literal(item["item_id"]),
                "'YX'",
                db.literal(item["kind"]),
                db.literal(item["title"]),
                db.literal(item["subtitle"]),
                "true" if item["enabled"] else "false",
                "true" if item["enabled"] else "false",
                "true" if item["is_core"] else "false",
                str(int(item["sort_order"])),
                db.json_sql(item["assigned_codes"]),
            ]) + ")"
        )
    sql_parts.append(
        "INSERT INTO public.switchboard_agent_roster (item_id, org_id, kind, title, subtitle, enabled, initial_enabled, is_core, sort_order, assigned_codes) VALUES "
        + ",\n".join(roster_vals)
        + ";\nCOMMIT;"
    )
    db.execute("\n".join(sql_parts))

    # Also update ui_bundle_data.json for offline laptop fallback
    for bpath in [ROOT / "ui_bundle_data.json", ROOT / "laptop_ui_bundle" / "ui_bundle_data.json"]:
        if bpath.exists():
            try:
                bdata = json.loads(bpath.read_text(encoding="utf-8"))
                raw_txt = json.dumps(bdata, ensure_ascii=False).replace("張羅薇", "羅薇")
                bdata = json.loads(raw_txt)
                bdata["yezhu_cases_catalog"] = all_cases[:120]
                bpath.write_text(json.dumps(bdata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass

    stats = db.query(
        """
        SELECT jsonb_build_object(
            'database', current_database(),
            'wb_cases', (SELECT count(*) FROM public.yezhu_workbench_case),
            'pinned_cases', (SELECT count(*) FROM public.yezhu_workbench_case WHERE is_pinned_default),
            'max_sidebar_title_len', (SELECT max(char_length(code || ' ' || name)) FROM public.yezhu_workbench_case),
            'hist_12084', (SELECT count(*) FROM public.yezhu_correspondence_ledger WHERE serial_no BETWEEN 1 AND 12084),
            'total_ledger', (SELECT count(*) FROM public.yezhu_correspondence_ledger),
            'pg_cases', (SELECT count(*) FROM public.case),
            'pg_distinct_codes', (SELECT count(DISTINCT case_code) FROM public.case),
            'roster_agents', (SELECT count(*) FROM public.switchboard_agent_roster WHERE kind = 'agent'),
            'roster_connectors', (SELECT count(*) FROM public.switchboard_agent_roster WHERE kind = 'connector')
        )
        """
    )[0]
    return stats




def get_initial_agent_roster():
    return [
        {
            "item_id": "agent-all-in-one",
            "kind": "agent",
            "title": "總機主腦（All-in-One）",
            "subtitle": "統一接手所有來信與回信草稿（極簡模式唯一分身，多支模式兜底）",
            "enabled": True,
            "is_core": True,
            "sort_order": 1,
            "assigned_codes": [
                "C114609", "C114109", "C115042", "Q-202610-07", "C115094",
                "C115031", "C115018", "C114512", "C114110", "C114488",
                "C115094-4", "C115025", "C115168", "C115211-01A"
            ],
        },
        {
            "item_id": "agent-contract-gov",
            "kind": "agent",
            "title": "中興/國營嚴謹合約官",
            "subtitle": "專責開口合約、工作指示單、審查意見逐條回覆",
            "enabled": True,
            "is_core": False,
            "sort_order": 2,
            "assigned_codes": ["C115094-4", "C115031", "C115018", "C114110"],
        },
        {
            "item_id": "agent-billing-ar",
            "kind": "agent",
            "title": "催款與計價請款專員",
            "subtitle": "專責估驗計價、發票入帳核對、尾款催收與未入帳把關",
            "enabled": True,
            "is_core": False,
            "sort_order": 3,
            "assigned_codes": ["C114609", "C115025", "C114512"],
        },
        {
            "item_id": "agent-deliverable",
            "kind": "agent",
            "title": "成果圖資交付專員",
            "subtitle": "專責測量成果圖、報告書、對外版 PDF 附件核對與交付",
            "enabled": True,
            "is_core": False,
            "sort_order": 4,
            "assigned_codes": ["C114109", "C115168", "C115211-01A", "C114488"],
        },
        {
            "item_id": "agent-field-safety",
            "kind": "agent",
            "title": "外業工安與進場協調員",
            "subtitle": "專責台塑/高鐵入廠申請、JSA 工安、現場會勘進場協調",
            "enabled": True,
            "is_core": False,
            "sort_order": 5,
            "assigned_codes": ["C115042", "C115094"],
        },
        {
            "item_id": "agent-quote-rfq",
            "kind": "agent",
            "title": "新詢價報價接待員",
            "subtitle": "專責新案詢價、施作範圍確認、報價單初稿與授權核對",
            "enabled": True,
            "is_core": False,
            "sort_order": 6,
            "assigned_codes": ["Q-202610-07"],
        },
        {
            "item_id": "conn-company-mail",
            "kind": "connector",
            "title": "company@yxsurvey.com.tw（公司總信箱）",
            "subtitle": "公司對外總收件信箱，收錄業主正式來信與詢價",
            "enabled": True,
            "is_core": True,
            "sort_order": 11,
            "assigned_codes": ["C114609", "Q-202610-07", "C115018", "C114512", "C114488"],
        },
        {
            "item_id": "conn-jekai-mail",
            "kind": "connector",
            "title": "jekai@yxsurvey.com.tw（JK 信箱）",
            "subtitle": "JK 個人與重點業主直通來信通道",
            "enabled": True,
            "is_core": False,
            "sort_order": 12,
            "assigned_codes": ["C115211-01A", "C115042"],
        },
        {
            "item_id": "conn-pm-mails",
            "kind": "connector",
            "title": "各 PM 個人信箱群（柏頤／智偉）",
            "subtitle": "吳柏頤、鍾智偉等專案經理與業主工程師往來信箱",
            "enabled": True,
            "is_core": False,
            "sort_order": 13,
            "assigned_codes": ["C114109", "C115031", "C114110", "C115025", "C115168"],
        },
        {
            "item_id": "conn-gov-edoc",
            "kind": "connector",
            "title": "政府電子公文交換（羅薇）",
            "subtitle": "行政羅薇負責之水利署、公路局等機關電子公文收發通道",
            "enabled": True,
            "is_core": False,
            "sort_order": 14,
            "assigned_codes": ["C115094-4", "C115094"],
        },
        {
            "item_id": "conn-lark-bridge",
            "kind": "connector",
            "title": "Lark 訊息轉入通道",
            "subtitle": "工程師與 PM 於 Lark 群組轉入之業主交辦與口述紀錄",
            "enabled": False,
            "is_core": False,
            "sort_order": 15,
            "assigned_codes": ["C115042", "C114609"],
        },
    ]


if __name__ == "__main__":
    stats = seed_database()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
