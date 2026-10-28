#!/usr/bin/env python3
"""沿用現有語料與劇本，產生CAT映射、來源盤點、SQL及真實離線回測。"""
import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

import db
import router

ROOT = db.ROOT
ARCH = ROOT.parent
RAG = router.RAG_ROOT
SHEET_ID = '1943hxNCcVIngRUesLas2t_tMTYmq8H1joKTgBrHKRHQ'
MAP = {'CAT-01':['QUOTE'],'CAT-02':['DELIVERABLE'],'CAT-03':['DELIVERABLE','COMPLIANCE'],
       'CAT-04':['FIELD','COMPLIANCE'],'CAT-05':['CONTRACT'],'CAT-06':['BILLING'],
       'CAT-07':['BILLING','QUOTE'],'CAT-08':['PROCUREMENT_LOGISTICS','QUOTE'],
       'CAT-09':['HR_ADMIN'],'CAT-10':['HR_ADMIN','OTHER']}
TEMPLATES = {
 'CAT-01':'{{client_name}}您好，已收到 {{case_code}} 詢價。報價編號 {{quote_no}}，請確認範圍及規格；核准版 {{approved_version}} 將由經辦查核。\n{{pm_name}}',
 'CAT-02':'{{client_name}}您好，附件提供 {{case_code}} 核准成果 {{approved_version}}。交付清單：{{deliverable_list}}。如需修正請標示圖號、頁次。\n{{pm_name}}',
 'CAT-03':'{{client_name}}您好，關於 {{case_code}}，逐條審查意見回覆如下：\n{{review_rows}}\n修正版 {{approved_version}} 待查核。\n{{pm_name}}',
 'CAT-04':'{{client_name}}您好，關於 {{case_code}} 入廠/作業申請，請查核 {{permit_details}}，進場條件須待核准。\n{{pm_name}}',
 'CAT-05':'{{client_name}}您好，關於 {{case_code}} 合約 {{contract_no}} 工單 {{work_order_no}} 已收悉。待確認事項：{{pending_items}}；範圍與期限請雙方核實。\n{{pm_name}}',
 'CAT-06':'{{client_name}}您好，關於 {{case_code}} 帳務文件 {{invoice_no}}，品名 {{invoice_item}}，請確認收件與處理狀態，核准版 {{approved_version}} 由財務查核。\n{{pm_name}}',
 'CAT-07':'{{client_name}}您好，已收到 {{case_code}} 下包/代墊資料，請協助補齊 {{pending_items}}；交易與金額由財務查核。\n{{pm_name}}',
 'CAT-08':'{{client_name}}您好，關於 {{case_code}} 海事設備與物流，請確認 {{pending_items}}。費用及責任條款待主管核實。\n{{pm_name}}',
 'CAT-09':'[MASKED_HR_PRIVATE]；僅限授權人資人工處理，禁止對外放行。',
 'CAT-10':'系統通知待管理員查核；e-GNSS 驗證碼不對外回覆。',
}
RULES = {
 'CAT-01':['詢價/報價回傳須核實quote與核版文件；基本資料、詢價回覆-修、PM報價回傳回覆僅知範本名稱，未取得Gmail範本原文'],
 'CAT-02':['⛔入帳後再寄出：未核實付款不得交付','台塑/麥電禁止外網連結；核准檔案依業主上限拆檔或紙本/光碟','成果PDF/DWG/照片清單由核版資料確認'],
 'CAT-03':['高鐵逐條意見/回覆/頁碼/圖號；未有複測證據不可宣稱完成','台塑/南亞JSA教育訓練日期不得早於審查完成日並附彩色照片'],
 'CAT-04':['台塑出廠日期原則5工作天內；效期、保險與訓練須查核','高鐵HSROR/作業核准及無人機空域許可須綁案件日期；不自動寫預排'],
 'CAT-05':['高鐵PCDL-25-0376/0089開口合約核對母案、工單、子案、餘額及期限','契約/追加/折扣/變更由PM以上核准，不自動成案或改契約'],
 'CAT-06':['中華工程發票10–20日；品名嚴格為合約編號+合約名稱+第X期計價','估驗單、計價單一式二份；蓋合約計價及領款章（大小章）','台塑依工程編號至電子採購網請款；金額須核報價/發票'],
 'CAT-07':['先區分應收與應付；下包/地政士代墊須核交易與單據，不輸出我方成本'],
 'CAT-08':['海事/離岸/USV/ROV/報關與採購責任、費用人工查核；不採信未核對銀行帳號'],
 'CAT-09':['人資/履歷與薪酬隔離；[MASKED_HR_PRIVATE]，不自動外發'],
 'CAT-10':['e-GNSS/EBCS驗證碼為敏感系統事件；本MVP遮蔽且不推播、不回覆','氣象/行銷/無法分類只入待確認佇列'],
}


def corpus():
    return [json.loads(s) for s in (RAG/'corpus.ndjson').read_text(encoding='utf-8').splitlines() if s.strip()]


def request_from_thread(thread):
    return {'source_key':'rag-thread:'+thread['thread_id'],'thread_id':thread['thread_id'],
            'channel':'email','mailbox':'jekai@yxsurvey.com.tw','evidence_kind':'real_thread',
            'occurred_at':thread['thread_date_end'],'subject':thread['subject'],
            'text':'\n'.join(m.get('current_body_text') or '' for m in thread['messages']),
            'attachments':[], 'provenance':thread['provenance']}


def make_books():
    audit_path = ARCH/'w0_reports/08_email_3to5yr_taxonomy_audit.json'
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    legacy = {b['intent_code']:b for b in json.loads((RAG/'playbooks.json').read_text(encoding='utf-8'))}
    rows = corpus()
    books = []
    for cat in audit['categories']:
        code = cat['category_id']
        examples = [t['thread_id'] for t in rows if router.classify(t['subject'],'\n'.join(m.get('current_body_text') or '' for m in t['messages']))[0]==code]
        books.append({'category_id':code,'name_zh':cat['name'],'reply_template':TEMPLATES[code],
          'keywords':router.KEYWORDS[code],'rules':RULES[code],
          'source_refs':[str(audit_path),str(ARCH/'w0_reports/08_email_3to5yr_taxonomy_audit.md'),str(ARCH/'PLUMB_V2_CLIENT_COMM_HARMONY_SPEC_R28.md')],
          'legacy_playbook_refs':[{'path':str(RAG/'playbooks.json'),'intent_code':key,'reply_template_sha256':__import__('hashlib').sha256(legacy[key]['reply_template'].encode()).hexdigest()} for key in MAP[code]],
          'grounded_thread_ids':examples[:3],'example_status':'GROUNDED' if examples else 'NO_EXAMPLE',
          'sla_hours':min(legacy[k]['sla_hours'] for k in MAP[code]),'requires_human':True,
          'template_origin':'沿用既有playbook需求與用語，依權威CAT及零外發規格調整；非Gmail草稿原文'})
    return books


def discover():
    """只盤點本機；規格提及的ID/主旨不會被展開成試算表列或郵件。"""
    skip = {'.git','node_modules','.venv','venv','__pycache__','chrome-profile','.cache','site-packages'}
    references, workbook_candidates, matching_exports = [], [], []
    scanned, large_skipped = 0, 0
    for parent, dirs, files in os.walk('/workspace'):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            path = Path(parent)/name
            if ROOT in path.parents or 'codex_run' in name or path.suffix in ('.log','.pyc'):
                continue
            if path.suffix.lower() in ('.xlsx','.xlsm','.ods'):
                workbook_candidates.append(str(path))
                try:
                    with zipfile.ZipFile(path) as z:
                        for item in z.infolist():
                            if item.filename.endswith('.xml') and item.file_size<12_000_000:
                                value=z.read(item).decode('utf-8','replace')
                                if SHEET_ID in value or '業主往來紀錄表' in value:
                                    matching_exports.append(str(path)); break
                except (OSError,zipfile.BadZipFile):
                    pass
            elif path.suffix.lower() in ('.json','.jsonl','.ndjson','.csv','.tsv','.txt','.md','.py'):
                try:
                    if path.stat().st_size>20_000_000:
                        large_skipped+=1; continue
                    scanned+=1
                    text=path.read_text(encoding='utf-8',errors='replace')
                    if SHEET_ID in text or '業主往來紀錄表' in text or '詢價回覆-修' in text or '報價回傳回覆(專案' in text:
                        references.append({'path':str(path),'sha256':db.file_hash(path),'kind':'提及規格/名稱，須有原始列才可匯入'})
                        if path.suffix in ('.csv','.tsv','.jsonl','.ndjson'):
                            matching_exports.append(str(path))
                except OSError:
                    pass
    # 原始Gmail草稿8份只有盤點數量與範本名稱；現有兩份DRAFT是Lark草稿。
    reviewed = [{'path':'/workspace/quote-settlement/ref/sheet1.xlsx',
                 'finding':'已檢查工作表名稱與sharedStrings：含業主往來紀錄表的SOP文字；34個工作表中沒有該紀錄表，非指定Sheet匯出。'}] if '/workspace/quote-settlement/ref/sheet1.xlsx' in matching_exports else []
    return {'search_root':'/workspace','text_files_scanned':scanned,'large_files_skipped':large_skipped,
            'excluded_directory_names':sorted(skip),'workbook_paths_checked':workbook_candidates,
            'reference_hits':references,'possible_sheet_exports':sorted(set(matching_exports)),
            'candidate_reviews':reviewed,
            'sheet_id':SHEET_ID,'sheet_available':False,'sheet_rows_loaded':0,
            'gmail_draft_templates_available':False,'gmail_templates_loaded':0,
            'gap':'未找到可核實的指定Google Sheet原始列與Gmail草稿原文；參考報告不是資料匯出。未製造12084列。',
            'search_limit':'略過程式依賴、瀏覽器二進位cache及大於20MB文字；xlsx僅檢查小於12MB的XML項目。'}


def append_book_sql(books):
    path = ROOT/'sql/switchboard.sql'
    base = path.read_text(encoding='utf-8').split('-- GENERATED_PLAYBOOKS',1)[0].rstrip()
    columns = ['category_id','name_zh','reply_template','keywords','rules','source_refs','legacy_playbook_refs','grounded_thread_ids','example_status','sla_hours','requires_human']
    statements = []
    for book in books:
        vals=[]
        for key in columns:
            val=book[key]
            vals.append(db.json_sql(val) if isinstance(val,(dict,list)) else ('true' if val is True else str(val) if isinstance(val,int) else db.literal(val)))
        statements.append('INSERT INTO public.email_playbook_rag('+','.join(columns)+') VALUES('+','.join(vals)+') ON CONFLICT(category_id) DO UPDATE SET '+','.join(c+'=excluded.'+c for c in columns[1:])+';')
    # DDL與劇本同一交易，失敗不留下半套狀態。
    base=base.removesuffix('COMMIT;').rstrip()
    path.write_text(base+'\n-- GENERATED_PLAYBOOKS\n'+'\n'.join(statements)+'\nCOMMIT;\n',encoding='utf-8')


def backtest(rows, now, persist):
    output=[]
    for thread in rows:
        request=request_from_thread(thread)
        result=router.route(request,now=now)
        if persist:
            db.execute('BEGIN;\n'+router.persist_sql(request,result)+'\nCOMMIT;')
        registered=db.query('SELECT jsonb_build_object(\'id\',id,\'serial_label\',serial_label) FROM public.switchboard_intake WHERE source_key='+db.literal(request['source_key']))
        output.append({'thread_id':thread['thread_id'],'source_key':request['source_key'],'evidence_kind':'real_thread',
                       'subject':router.sanitize(thread['subject']),'thread_date_end':thread['thread_date_end'],
                       'has_body':bool(thread['body_message_count']),'provenance':thread['provenance'],
                       'registered':registered[0] if registered else None,**result})
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--discover',action='store_true')
    args=parser.parse_args()
    if not (ROOT/'schema_baseline.json').exists():
        db.dump(ROOT/'schema_baseline.json',db.snapshot())
    books=make_books();db.dump(ROOT/'playbooks.json',books);append_book_sql(books)
    if args.apply:
        db.apply()
    if args.discover or not (ROOT/'source_discovery.json').exists():
        db.dump(ROOT/'source_discovery.json',discover())
    now=datetime.now(router.TZ)
    rows=sorted(corpus(),key=lambda t:(t['thread_date_end'],t['thread_id']),reverse=True)
    latest=rows[:20]
    db.dump(ROOT/'dryrun_20.json',{'generated_at':now.isoformat(),'selection':'本機既有corpus最後訊息日期最新20個真實threads；不過濾不利樣本、不把草稿當已寄送',
                                 'actual_sends':0,'results':backtest(latest,now,args.apply)})
    # 另一組涵蓋優先的20例，仍全部是真實thread，絕不加入規格例句。
    selected=[]
    for cat in ('CAT-01','CAT-02','CAT-03','CAT-04','CAT-06'):
        match=next((t for t in rows if router.classify(t['subject'],'\n'.join(m.get('current_body_text') or '' for m in t['messages']))[0]==cat),None)
        if match and match not in selected:
            selected.append(match)
    selected+=(t for t in rows if t not in selected)
    selected=selected[:20]
    db.dump(ROOT/'backtest_coverage_20.json',{'generated_at':now.isoformat(),'selection':'指定類別優先，再按最近日期補至20個真實threads；無電話原始memo時不補造',
                                          'actual_sends':0,'results':backtest(selected,now,args.apply)})
    refs=[RAG/'corpus.ndjson',RAG/'playbooks.json',RAG/'acceptance.py',RAG/'privacy.py',RAG/'inventory.json',
          ARCH/'w0_reports/08_email_3to5yr_taxonomy_audit.md',ARCH/'w0_reports/08_email_3to5yr_taxonomy_audit.json',
          ARCH/'PLUMB_V2_CLIENT_COMM_HARMONY_SPEC_R28.md']
    db.dump(ROOT/'input_manifest.json',{'generated_at':now.isoformat(),'sources':[{'path':str(p),'sha256':db.file_hash(p)} for p in refs],
              'corpus_threads':len(rows),'newest':rows[0]['thread_date_end'],'oldest':rows[-1]['date'],
              'serial_floor':12084,'serial_floor_basis':'權威稽核已觀察到12084；不是本機已匯入12084列',
              'source_mailbox':'jekai@yxsurvey.com.tw；不是公司Gmail全信箱匯出'})
    print(json.dumps({'message':'完成離線建置','real_threads':len(rows),'dryrun_count':20,'actual_sends':0},ensure_ascii=False))


if __name__=='__main__':
    main()
