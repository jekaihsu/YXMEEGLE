#!/usr/bin/env python3
"""由實際產物生成繁體中文報告，保留已附加的guard輸出。"""
from collections import Counter
from datetime import datetime
import json

import db
import router

REPORT=db.ROOT.parent/'w0_reports/11_ai_switchboard_mvp.md'
MARKER='\n## Preflight guard 實際執行輸出\n'


def phase2_report(root):
    path=root/'formal/result.json'
    if not path.exists():
        return ''
    model=json.loads(path.read_text(encoding='utf-8'))
    implementation=json.loads((root/'formal/implementation_result.json').read_text(encoding='utf-8'))
    corr09=json.loads((root/'formal/corr09_result.json').read_text(encoding='utf-8'))
    previous=json.loads((root/'preflight_result.json').read_text(encoding='utf-8'))
    backup=json.loads((root/'formal/preflight_backup.json').read_text(encoding='utf-8'))
    production=model['production']
    rows=[]
    for mutant in model['mutants']:
        trace=mutant['counterexample_trace']
        rows.append(f"| Mutant-{mutant['mutant']} | {mutant['violated_invariant']} | {len(trace)-1} | "+
                    ' → '.join(step['action'] for step in trace)+' |')
    tlc=model['tlc']
    tlc_text=(f"Java 與 TLC 均存在，已實際執行正式模型及四個突變。正式模型探索 **{tlc['runs'][0]['distinct_states']:,}** 個不同狀態，退出碼0；四個突變皆由對應不變量捕捉，退出碼12為預期的反例結果。Python 與 TLC 正式模型的狀態數完全一致。" if tlc['status']=='passed' else tlc['note'])
    return f'''
## Phase 2：形式模型與狀態守衛

沿用既有檔案擴充，未重建專案。`formal/ClientSwitchboardStatechart.tla` 與 `.cfg` 定義 `outbound_message`、`client_commitment` 的交錯轉移；`formal/model_check.py` 由所有初始狀態進行完整 BFS，沒有深度上限、抽樣或隨機截斷。正式模型探索 **{production['states_explored']:,}** 個狀態、**{production['transitions_explored']:,}** 個轉移，佇列清空，**0 違規**。`SENT` 與 `CLOSED` 均有可達狀態，非以封鎖所有流程取得空泛通過。

| 不變量 | 驗證條件與實作連接 |
| --- | --- |
| INV-01 | SENT 必須同時具備81人名冊內的 approved_by 與全部十閘門通過；`gates.send_authorized` 與 router 實際連接。 |
| INV-02 | CAT-02 設定 hold_until_paid 且未入帳時，不得 APPROVED／SENT；`payment_release_allowed` 驗證四組旗標，其他類別不受誤擋。 |
| INV-03 | 草稿命中底價／成本／毛利／A-B-C預算／底薪時，立即為 BLOCKED_SENSITIVE；包含預算分隔變體與夜間排程。既有薪資遮蔽仍保留。 |
| INV-04 | 範圍變更／追加的 CLOSED 前必須有非空 settlement_card_id 與非空書面確認草稿；`router.close_commitment` 缺任一項即拒絕。 |

名冊證據為 `formal/authorized_roster.json`，只封存81個實際身分識別與在職狀態，不載入姓名或薪資。81個識別逐一枚舉，另有未核准與名冊外識別；與本機 `public.employee` 核對一致。實際在職71人的限制仍保留，81人身分名冊不等於81人全可核准。十閘門的全部 **1,024** 組布林輸入均驗證後，模型依合取結果做精確等價化；敏感詞命中與結算卡空／非空亦採等價類。

模型範圍：固定一份草稿與一筆承諾，列舉所有交錯；付款只增不撤，同一版本內不修改草稿與核准證據。修改草稿、撤銷核准、撤回付款及任意多筆資料的並行不在本模型範圍。書面確認只要求先有草稿，沒有發送書面訊息。`CLOSED` 是新增的本機承諾生命週期守衛；不是宣稱已替既有所有資料庫結案入口建立相同限制。資料庫與 CLI 仍維持 DRY_RUN／0寄送，模型中的 SENT 只是模擬狀態。

### 四個移除守衛的突變

每次只停用一個共用守衛定義，其餘轉移與不變量保持相同。BFS 保留父節點，以下為包含 Init 的最短反例；完整狀態保存在 `formal/result.json` 與 `result.json`。

| 突變 | 被違反不變量 | 轉移步數 | 最短反例 |
| --- | --- | --- | --- |
{chr(10).join(rows)}

### TLC 與驗收結果

{tlc_text} 原始輸出為 `formal/tlc_mutant_0.log` 至 `formal/tlc_mutant_4.log`。`formal/implementation_check.py` 的 **{len(implementation['checks'])}** 項靜態與實際行為檢查均為 `{implementation['passed']}`，包含81人名冊、十閘門1,024組輸入、付款旗標、敏感詞日夜行為與結算證據組合。

驗收另發現既有組織隔離遷移已加入複合外鍵；已讓本機寫入的 `org_id` 取自實際案件，並將結算視圖的 `k.*` 改為原有欄位明列，避免新增欄位破壞 CREATE OR REPLACE VIEW 的欄序。既有組織外鍵未刪除或放寬。`acceptance.py` 已納入 BFS、四個突變、TLC、實作連接與 CORR-09，並重新產出 `result.json`。四項真實樣本覆蓋缺口仍保留，不能因形式模型通過而宣稱整體驗收通過。

### CORR-09 與既有 CORR-01～08

修改前備份：`{backup['path']}`，SHA-256：`{backup['sha256']}`。新增 CORR-09 會實際執行 `formal/model_check.py` 及 `formal/implementation_check.py`，解析完整探索結果、四個反例，並檢查實際 gates／router 的 AST 連接及行為；探索數量由實際結果取得。CORR-01～08 原判斷逐字比對一致，讀取與 ledger 函式 AST 亦一致，沒有降低條件。

本次 `--switchboard-only` 的 CORR-09 結果：**{'通過' if corr09['passed'] else '未通過'}**，原始輸出在 `formal/corr09_output.txt`。此選項明示只執行本機 CORR-09，不能當作全域通過。CORR-01～08 保留先前實際執行的退出碼 **{previous['returncode']}**，時間 **{previous.get('finished_at','未記錄')}**；本次未重新呼叫 Lark API。為遵守「No network sends」，本次沒有發出網路請求，也沒有 Gmail／Lark 寫入；若需本次全域 CORR-01～09 同輪通過證據，仍須先確認可執行 Lark 唯讀 API 查詢。

離線重現命令：

```bash
python3 formal/model_check.py --tlc --output formal/result.json
python3 formal/implementation_check.py
python3 /workspace/pstack_verify/preflight_guard.py --switchboard-only
python3 acceptance.py
python3 make_report.py
```
'''


def main():
    root=db.ROOT
    result=json.loads((root/'result.json').read_text(encoding='utf-8'))
    latest=json.loads((root/'dryrun_20.json').read_text(encoding='utf-8'))
    coverage=json.loads((root/'backtest_coverage_20.json').read_text(encoding='utf-8'))
    discovery=json.loads((root/'source_discovery.json').read_text(encoding='utf-8'))
    manifest=json.loads((root/'input_manifest.json').read_text(encoding='utf-8'))
    stats=db.query("""SELECT jsonb_build_object('intakes',(SELECT count(*) FROM public.switchboard_intake),
      'communications',(SELECT count(*) FROM public.client_communication),'commitments',(SELECT count(*) FROM public.client_commitment),
      'outbound',(SELECT count(*) FROM public.outbound_message),'books',(SELECT count(*) FROM public.email_playbook_rag),
      'first_serial',(SELECT min(serial_no) FROM public.switchboard_intake),'last_serial',(SELECT max(serial_no) FROM public.switchboard_intake),
      'contacts',(SELECT count(*) FROM public.customer_contact),'invoices',(SELECT count(*) FROM public.invoice),
      'sent',(SELECT count(*) FROM public.outbound_message WHERE sent_at IS NOT NULL OR status<>'DRY_RUN' OR actual_sends<>0))""")[0]
    failed=[c for c in result['checks'] if not c['passed']]
    rows=[]
    for row in latest['results']:
        rows.append('| '+str(len(rows)+1)+' | '+row['thread_date_end']+' | '+row['registered']['serial_label']+' | '+row['category_id']+' | '+('有' if row['has_body'] else '無')+' | '+row['action_card']['disposition']+' | '+row['subject'].replace('|','／').replace('\n',' ')+' |')
    baseline_check=next(c for c in result['checks'] if c['name'].startswith('dim/fact恰好'))
    baseline_note='本次與原基準完全一致，各5個視圖。' if baseline_check['passed'] else '本次與原基準有差異；基準未覆寫。請見失敗項與 formal/database_drift.json；各維持5個視圖。'
    text=f'''# 詠翔 AI 業主往來總機 MVP：建置與實際驗收報告

產出：{datetime.now(router.TZ).isoformat()}；文字與 JSON 均為繁體中文／UTF-8。

**建置已完成並執行離線驗收，但完整驗收未通過。** `result.json` 的 `passed={str(result['passed']).lower()}`、`failed_count={result['failed_count']}`；共 {len(result['checks'])} 項檢查。實作檢查 `implementation_passed={str(result['implementation_passed']).lower()}`。未取得的真實情境不得以合成測試補充宣稱通過。實際外發 **{stats['sent']}**，Gmail／Lark 寫入 **0**。

## 實際交付

- 工作目錄：`{root}`。
- `sql/switchboard.sql`：沿用 PostgreSQL `yongxiang_plumb` 既有建置，交易內建表、函式、觸發器、三視圖及十劇本 upsert；本次兩次重跑結果依 `result.json` 如實列出。
- `router.py`：分類→抽取→既有 RAG 映射→十閘門→Action Card JSON 與確認草稿。CLI 僅本機檔案與 PostgreSQL，無寄送實作。
- `build.py`：沿用 `{router.RAG_ROOT}/corpus.ndjson`、`playbooks.json`、`privacy.py`；不重建舊專案；`acceptance.py` 實際重跑既有驗收。
- `dryrun_20.json`：本機最新20個真實 threads；`backtest_coverage_20.json`：指定類別優先、再依日期補足20個真實 threads。每筆有原始路徑／索引／message_id、分類證據、抽取欄位、RAG引用、十閘門、草稿與卡片。
- `acceptance.py`／`result.json`：防呆正反例、DB 約束、流水號、來源雜湊、舊專案回歸、真實回測與覆蓋缺口。合成資料僅在交易內建立並 `ROLLBACK`。
- `schema_baseline.json`：套用前封存 `dim`、`fact` 定義、欄位、ACL、owner、筆數及資料集合雜湊；{baseline_note}

## 資料實況與限制

本機沿用語料為 **{manifest['corpus_threads']} threads／76 messages**，只有5則正文、3個有正文的thread；另有2則Lark草稿，不能稱為公司Gmail的8份標準草稿。日期為 {manifest['oldest']} 至 {manifest['newest']}；來源是 `jekai@yxsurvey.com.tw` 的本機快取，並非 `yongxiang.ltd@gmail.com` 全信箱匯出。權威盤點提到的50,578封信、24,679 threads及12,084筆流水號，皆不擴增成原始資料。

已搜尋 `/workspace` 的 {discovery['text_files_scanned']} 份文字檔，並檢查 {len(discovery['workbook_paths_checked'])} 份工作簿。指定 Sheet ID：`{discovery['sheet_id']}`。**未取得指定試算表可核實原始列，載入0列；未取得Gmail標準草稿原文，載入0份。** `source_discovery.json` 保存命中與範圍限制。`/workspace/quote-settlement/ref/sheet1.xlsx` 命中的是SOP中提及「業主往來紀錄表」的文字；已檢查34個工作表名稱，不是該表匯出，因此未匯入其列。其他命中為規格／計畫引用。

搜尋略過依賴目錄、瀏覽器二進位cache、大於20MB文字與單一大於12MB的工作簿XML。結論限於已檢查範圍，不宣稱整台主機或雲端沒有資料。

既有資料庫有 {stats['contacts']} 筆 `customer_contact`、{stats['invoices']} 筆 `invoice`；`quote_version`、`deliverable` 缺可驗證的核准狀態。故本MVP不能從信件顯示名或任意本機檔案推定收件人／核版附件；無權威資料時阻擋。未接通真實核准身分驗證服務，CLI提供的人員識別僅作本機查核，所有結果始終不可外發。

## 資料表與流水號

本MVP SQL建立的物件在 `public`：四張指定表 `client_communication`、`client_commitment`、`outbound_message`、`email_playbook_rag`，另有 `switchboard_intake`、`switchboard_serial` 暫存與計號表。本次程式未對 `dim.*`、`fact.*` 進行DDL或ACL修改；共同資料庫的最新差異仍由原驗收條件檢出，不以重設基準排除。

流水號下限12084引用權威稽核的最後觀察值；不是聲稱已匯入12084列。`switchboard_register` 用交易 advisory lock 及計數列鎖，取既有最大值續編；相同 `source_key` 不重編、不重複建事件。目前共同資料庫合計 **{stats['intakes']} 筆暫存、{stats['outbound']} 份DRY_RUN草稿、{stats['books']} 份劇本**，編號 `業主往來{stats['first_serial']}` 至 `業主往來{stats['last_serial']}`；合計包含其他流程的合成資料，不能全數視為真實匯入。兩組20例有交集，資料庫不重複計數。

未知客戶、案件、承辦或電話抽取未確認時進 `switchboard_intake`；不虛構客戶／聯絡人，所以正式 `client_communication` **{stats['communications']}** 筆、`client_commitment` **{stats['commitments']}** 筆是如實結果。已核實客戶及承辦的事件才寫正式表；電話還需 `human_confirmed_by`。更正正式事件須追加新事件，觸發器拒絕 UPDATE／DELETE。

支援公司總機Gmail進件與內部一句話。`把 C115301 報價寄給中興` 能抽出案件／客戶候選，但此本機DB沒有C115301，不會硬配別案。`剛才黎明張技師電話說北側加測200m` 產生內部承諾卡、對外書面確認稿及待核實欄位；案件與人員已核實且抽取有人確認後，會新增 `scope_add` 承諾，確認稿含「如有誤請回覆更正」。已於本次合成交易中驗證200m、承諾列與結算投影；本次測試均ROLLBACK，資料庫中其他流程的合成列另外由原驗收檢出。普通郵件簽名中的「電話」不會被誤算成電話承諾。

`customer_behavior_v` 計算折扣次數／平均折幅、已完成圖資延遲、追加未簽回率、未付款逾期及已足額收款的平均延遲；無資料為NULL而非虛構數值。`case_timeline_v` 合併往來與承諾事件。`settlement_commitment_v` 列出非撤回的業主追加／變更，區分實際書面往來與待擬草稿，並標記48小時追問及待建立預備合約明細；**未自動改既有contract_item**。

## 十閘門與專屬劇本

| 閘門 | 實際檢查 |
|---|---|
| no_send_mode | 程式無傳輸；DB僅DRY_RUN、sent_at必NULL、actual_sends必0；所有對外都要求在職人員approved_by |
| recipient_known_client | 正式聯絡人、有效單一Email、contact/customer/case一致；不接受任意to/cc/bcc |
| case_code_resolved | 唯一案件核實、報價及客戶一致；多案／未知編號阻擋 |
| amount_requires_human | 金額與核版quote/invoice一致、幣別一致且人工查核；沒有權威數值即阻擋 |
| contract_requires_human | 合約、追加、交期與電話確認由案件PM核准；電話抽取另需人確認 |
| no_hr_private | 薪酬段落[MASKED_HR_PRIVATE]；禁底價／成本／毛利／A-B-C及A/B/C預算／內部／點數單價；OTP禁止外發 |
| no_raw_phone_id | 台灣、國際／中國電話及身分證遮蔽；原稿有裸個資仍阻擋 |
| attachment_present_if_promised | 承諾有附件就必須有；逐項核對交付清單、核定版與SHA-256；付款及業主專屬規則 |
| sla_deadline_check | 22:00–07:00排程至07:00且仍不送；SLA、逾期／相對／衝突期限與權威日期核對 |
| template_variables_all_filled | 所有變數都有證據才可通過；未知業務與HR/系統噪音不放行 |

十個CAT劇本全部已入庫，每個都有權威來源、既有playbook引用與同類真實thread或 `NO_EXAMPLE`。範本是既有劇本依規格調整的本機草稿，不冒充Gmail原始範本。

- CAT-02「⛔入帳後再寄出」未核實付款阻擋；付款由invoice及payment_receipt核實，不能採信來信自述。
- 中華工程：10／20日邊界通過，9／21日拒絕；發票品名嚴格核對 `合約編號+合約名稱+第X期計價`，劇本保留估驗／計價單兩份及用印要求。
- 台塑／南亞／麥電：禁止外網連結；附件須符合業主核定上限拆檔。規格沒有固定MB數，程式不杜撰；缺上限設定就阻擋。入廠劇本保存5工作天、訓練效期與核准資料待查事項。
- 高鐵：開口合約須核實母案、工單、餘額與子案；審查稿須逐條意見／回覆／頁碼／圖號，不無據宣稱複測完成。
- e-GNSS／EBCS：敏感驗證碼遮蔽並禁止外發；本MVP不做群組推播。人資與系統通知只分流人工。

`outbound_message` 的 `approved_by` 可為NULL的只有待審DRY_RUN草稿；未核准不能有定稿，任何人都不能改成sent。夜間queue存在 `scheduled_for` 與卡片狀態；沒有自動發送worker，07:00仍需人處理。

## 最近20個真實thread的端到端dry-run

挑選規則：最後訊息日期倒序，同時刻依thread_id倒序，直接取20個；保留語料中的草稿狀態，不把草稿當外寄事實。{sum(r['has_body'] for r in latest['results'])} 個有正文，其餘只有中繼資料，不得推測附件或承諾。原始thread/message_id與完整來源索引見JSON，以下主旨已遮蔽敏感資料。

| # | 最後日期 | 流水號 | CAT | 正文 | 卡片狀態 | 遮蔽主旨 |
|---|---|---|---|---|---|---|
'''+ '\n'.join(rows)+f'''

涵蓋優先20例分布：`{dict(Counter(r['category_id'] for r in coverage['results']))}`。雖然這20個全是真實來源、流程可重現並已持久化草稿，**仍缺CAT-02、CAT-03、CAT-04及電話口頭承諾的真實原始資料**，因此不符合完整指定覆蓋驗收。

## 驗收結果

`result.json`：`passed={str(result['passed']).lower()}`，`failed_count={result['failed_count']}`；{sum(c['passed'] for c in result['checks'])}/{len(result['checks'])} 項通過。未通過項目：

'''+ '\n'.join('- '+c['name']+'。' for c in failed)+'''

其他已測項目包含：十閘門正反例、跨客戶收件人、金額／幣別、禁詞、薪資與電話遮蔽、附件漏附及偽造核版、交付清單、付款、各業主規則、夜間五個邊界、未填變數、期限、DB硬拒sent／sent_at／非零寄送／未核准定稿、事件不可修改、流水號重跑與公司Gmail/內部輸入、合成電話承諾寫入後ROLLBACK，以及既有RAG驗收與dim/fact不變。

## 重跑與本機使用

```bash
cd /workspace/yongxiang_arch/ai_switchboard_mvp
python3 build.py --apply --discover
python3 acceptance.py
python3 make_report.py
python3 run_preflight.py
python3 acceptance.py
python3 make_report.py
```

`acceptance.py` 在真實覆蓋不足時退出碼1為預期結果，不能把它改成假通過。若來源或程式有修改才需重跑；`schema_baseline.json` 為修改前基準，不覆寫。

本機一句話請求可用UTF-8 JSON：`source_key`穩定唯一、`occurred_at`含時區、`channel=staff_request`或`phone_memo`、`text`、已核實的`our_employee_id`及必要時`human_confirmed_by`。Email改為`channel=email`與`mailbox=yongxiang.ltd@gmail.com`。執行：

```bash
python3 router.py --input request.json --output action_card.json --persist
```

尚待資料補齊：指定Sheet逐列匯出、公司Gmail原始thread與8份範本、CAT-02/03/04及電話原始memo、客戶聯絡人與在職狀態、核版附件清單／上限、核准quote/invoice及付款證據、正式人工核准服務。取得後才能完成真實情境覆蓋；目前所有產物只供人工審稿，無實際外發。
'''
    existing=REPORT.read_text(encoding='utf-8') if REPORT.exists() else ''
    appendix=MARKER+existing.split(MARKER,1)[1] if MARKER in existing else ''
    REPORT.write_text(text+phase2_report(root)+appendix,encoding='utf-8')
    print(str(REPORT))


if __name__=='__main__':
    main()
