# SOP 真實契約與剩餘實作對照

本次僅讀來源、整理證據；没有修改遠端流程、工作台執行規則或匯入舊案。

## 本體與欄位核實

已從正常 Meegle UI 取得 334662 v137、566082 v2 本體。依節點流轉面板開啟 Configure Node Form，再 Cancel；334662 的 Save 仍 disabled。真 UI 抽查：334662/state_14 必填 Due time、Node owner，表單空白；566082/state_0 表單空白、Single Complete。其餘節點的契約來自同次 UI 載入的整份結構，不宣稱逐一點過 69 個面板。

重要修正：`exclude_form_conf=true` 沒有移除 `workflow_conf.nodes[].form_conf`。先前萃取器漏列該欄，不能再以參數名稱斷言所有節點表單未知。兩個模板的所有 node form schema 都是空陣列；真正交付需求主要位於 **task.deliverable／task.plan_info.union_delivery_list、required_node_fields、node_pass_required**，不是空白表單本身。

- 334662：62 節點、52 子任務，其中 29 個子任務的 `node_pass_required.value` 明示 true（仍需尊重其 usage_mode／條件）；71 條連線。
- 566082：7 節點、0 子任務、6 條線性連線。末節點未命名，不猜業務語意。
- 正常 CLI meta-fields 完整兩頁：50＋26＝76 欄，第 2 頁 has_more=false；節點／子任務／條件共引用 28 個自訂欄位，全數對回名稱、型別及可用選項。
- 某欄位出現在 visibility 條件中，不代表它是該節點必交資料；交付與條件需分開解析。
- 精確角色、條件、表單、52 子任務 stable keys、交付欄位及連線保存在 `SOP_TEMPLATE_CONTRACTS_20260929.json`；由 `scripts/extract_sop_contracts_20260929.py` 重建。這是來源契約，`runtime_enabled` 尚未實作。

## 證據優先序

最新對話核定（訓練／能力暫停、薪資 Base 不回寫、正式業務統一審批、設計變更 PM＋該組主管共同核准、舊案 Meegle 完成）優先於早期文件。以下證據縮寫：

- D4：`SOP_MAPPING_DECISIONS.md` 第四批續，內業追蹤、成果補正、PM 五日聯絡。
- D5：同文件第五批，下包需求／報價／出工／成果／付款分工。
- D6：同文件第六批，PM＋行政兩方確認及滿意度例外，並受最新「統一審批」決策約束。
- P：四 PDF 的已盤點 `SOP_CANONICAL_SOURCE_CATALOG_20260928.json`；每項 `document/page/id/inputs/outputs/source_roles` 可追溯。教育訓練 PDF 保留來源但依最新決策停用。
- T：本次 334662 v137 精確 node key、task、condition、connections。

## 28 個未引用節點逐項處置

「現有功能」代表可掛接的候選，**不代表已證明等價或已串好**。分支屬於現有功能的適用條件，不能新增假待辦供使用者按完成。

| T key／名稱 | 應落地位置與類型 | 證據與不可省略條件 |
|---|---|---|
| state_29 是否有下包需求 | 預設子任務：需求判定、下包資訊；PM 彙整、組主管確認 | D5；P intake.subcontract_decision；T 下包需求／資訊欄位。核定後分支適用性留版本 |
| state_34 無 | 現有功能條件：無下包適用性分支 | D5；T 連線＋下包需求條件；標不適用，不造完成 |
| state_33 有 | 現有功能條件：啟用下包報價 | D5；T 条件與連線，不做獨立打勾任務 |
| state_35 下包提出報價 | 預設子任務：行政收件、PM／組主管確認範圍 | D5；P intake.subcontract_quote；金額核准不借由上傳完成 |
| state_30 追蹤報價 | 現有 quote_review／追蹤流程的顯式映射 | T 子任務「是否回傳報價單」；每份報價獨立狀態，不能直接完結整案 |
| state_31 未得標／報價期限到期 | 預設子任務／報價結果：未得標原因、結果佐證 | T 未得標原因與回傳狀態；期限到期不推定工程結案 |
| state_32 本報價工作結束 | 現有功能：關閉該報價工作 | T state_31 下游；只影響報價版本，保留其他報價及工程 |
| state_37 是 | 現有功能條件：報價回簽分支 | T 報價單是否回傳值與連線，不新增假子任務 |
| state_36 無 | 現有功能條件：未回簽追蹤分支 | T；不得把無回簽當成核准合約 |
| state_27 建立案件編號／回傳本 | 預設子任務：核對來源工程編號、製作／引用案件回傳本 | P intake.case_identity；使用者工程命名規則＋V4/總表來源，不能再任意新開案 |
| state_81 展延 | 現有原生 extension＋預設展延會議／佐證交付 | T「展延會議」；已核定原生審批，核准前不能改期限 |
| state_82 下包出工 | 預設子任務：對應組安排、PM 協調追蹤 | D5；不能把安排出工當成驗收／付款 |
| state_50 執行中業主聯繫 | 現有 recurring client_contact＋聯繫紀錄交付 | D4；P execution.client_contact；保留五日聯絡與佐證，不自動冒充已聯絡 |
| state_51 節點檢討與紀錄 | 現有 weekly_review＋檢討紀錄子任務 | P execution.weekly_field；T 每周檢討；非考評薪資計算 |
| state_52 考評與結算計算 | 停用 | 最新訓練／能力／薪資相關停用；P execution.assessment_field 僅來源留存 |
| state_45 內業作業開始 | 現有 workflow_rules 啟動 gate 的顯式映射 | P execution.indoor_work；前置成果與工項適用性成功才啟動各組，不能所有內業串行 |
| state_46 內業節點追蹤 | 現有各組進度／PM 追蹤＋日報對應 | D4；P execution.indoor_tracking；真日報匹配不等於成果審核通過 |
| state_49 成果是否需補充修改 | 現有 correction 週期＋補正版本／必要 change、extension | D4；P execution.correction；每五日檢查，影響核准範圍或期限要原生審批 |
| state_54 否 | 現有功能條件：不需补正分支 | T 前後連線與條件；不是省略交付核准 |
| state_63 否 | 現有功能條件：未入帳→追蹤 | T 是否入帳分支；不能自動造付款狀態 |
| state_64 請款情況追蹤 | 現有 recurring receivable，以款項批次為單位 | T 每五日追蹤入帳；D6；operations 已有候選流程，仍要來源鍵與範圍測試 |
| state_65 計價條件變動回圈 | 現有 financial／計價版本重開規則 | T 名稱與回到計價連線；不得沿用過期核准，歷史收付款及成果不抹除 |
| state_62 是 | 現有功能條件：有效入帳佐證後續結算 | T；D6；不能只有一個 bool 即放行 |
| state_61 是否有下包 | 預設子任務：對應組成果驗收／下包報告，行政引用 | D5；P execution.subcontract_decision；不能以需求勾選代替成果驗收 |
| state_67 無 | 現有功能條件：無下包→略過下包結算支線 | D5；T 精確條件；不能標成付款完成 |
| state_66 有 | 現有功能條件：有下包→驗收／請款／入帳支線 | D5；T；保留與主案不同的款項／成果範圍 |
| state_57 節點檢討與紀錄 | 現有 weekly_review 的計價階段範圍＋紀錄 | P execution.weekly_pricing；不可與外業檢討共用完成狀態 |
| state_58 考評與結算計算 | 停用 | 最新訓練／能力／薪資停用；P execution.assessment_pricing 留存但不執行 |

## 可以直接實作的下一批

1. 來源鍵改成 template ID＋version＋node key＋task key；把 52 子任務原始身份、實際交付欄位及 29 個 required 標記帶入可追溯規格。最新已核定的負責人繼承與可改派、全動作 log 保留。先顯示來源契約，不能在未驗證條件前一律設必填。
2. D4/D5 已核定的聯繫、追蹤、下包範圍及成果工作可補顯式 task 定義與 source mapping，不需重問使用者。核准仍引用既有原生審批，不另外做本地「通過」假成功。
3. `state_52/state_58` 明確 disabled＋原因，不能在 UI 隱藏後仍由 worker 產生薪資／能力工作。
4. 將 71 條連線、各節點 start/pass mode、visibility/transition rule 編譯為可驗證的分支與並行規則；測試回圈新輪次、分批成果、工項範圍與重送冪等。**不能把 Meegle condition 當字串 eval，不能把循環 DAG 化後靜默丟邊。**
5. 驗證版本升級保存原成果、人工改派、已核准審批和付款歷史；新規則不回溯偽造舊節點完成，也不改 Meegle 舊案。

## 最少仍須業務決定／啟用前阻擋

- **全公司切換基準**：目前 `case_cutover.initialize_execution_system` 對每個新發現的正式案件一律 pending，只有逐案 assign，沒有 cutoff/versioned baseline/readiness。它提供安全攔截，尚未達成「切換後新案自動工作台」。必須核定一份旧案身份基準（來源 Base/table/record＋業務編號別名與 Meegle 舊案範圍）及生效時點／來源新案認定欄位。先 dry-run 分類和衝突清單，管理員一次發布有版本的接管規則；之後匹配舊案仍 Meegle、確定新案 workbench、資料不明才 pending。不得用首次同步時間或猜測建立時間代替核定基準。
- **566082 未命名末節點**：沒有必要為了套用完整版而問；保持未套用。只有公司要求精簡模板也成為可執行選項，才需確認其業務意義及是否保留，不能推定財務結案。
- 可見設定還包含舊模板「Anyone 可完成」與 single-user模式；這與最新工作台核准規則不同，直接採最新核定規則，不再要求使用者重複裁決。

此文件是有來源的實作清單，不是宣告 SOP 引擎完成，也不是授權立刻按某個日期把全部待確認案件啟用。
