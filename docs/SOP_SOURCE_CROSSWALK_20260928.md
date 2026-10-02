# 四份 PDF 與 Meegle SOP 來源對照（2026-09-28）

後續證據更新：已從既存原檔擷取 334662 v137 真範本的 62 節點／52 子任務／71 連線，詳見 `MEEGLE_TEMPLATE_REVIEW_20260928.md`。下方單案盤點是較早 crosswalk 依據；第二範本 566082 及完整執行映射仍未完成。

已逐張閱讀原圖與文字：4 份、各 1 頁。下列 65 個有語意的作業／判斷／里程碑給予穩定來源 ID，69 條可辨識關係另存 JSON。圖例、表單清單、指標不冒充任務。
**這是核對資料，不是已發布的完整替代 SOP。** 不自動匯入 Meegle 舊案，不把原圖箭頭排列硬套成九部門線性完成，也不啟用薪資／訓練／考評。

## 可重現原始證據

`python -X utf8 scripts/extract_sop_evidence.py` 保存逐頁文字、PNG 及 SHA256；`python -X utf8 scripts/build_sop_source_catalog.py` 產生本表與 `SOP_CANONICAL_SOURCE_CATALOG_20260928.json`。
渲染與文字位於 `.runtime/sop-audit-20260928/`。原始 PDF 檔不變。

## 已確認的關鍵邊界

- 報價結束只結束該報價。回簽後建立案號、確認單；多報價可對同確認單，不能把每張報價算成正式案件。
- 外業圖明寫「階段性通知」，成果與計價需以批次為單位；新增下一批不推翻前批已核准交付，修訂前批則明確指定被取代版本。
- 「是否入帳」與下包「未入帳／入帳」是實收付判斷；Lark 核准是核准證明，不等於銀行入帳或帳务結清。
- 案件結算表与月考評／阿米巴表用途不同。案件財務結算保留，後兩者依最新裁示停用。
- 各組進度、工作預排、檢討、業主聯繫可平行或週期執行；部門／角色不是流程階段，不能以行政角色合併公務、請款、結案。
- 原圖「通知業主報價成立」在正式提出報價之前；保留原名與位置，不以同名推論回簽後事件。
- 工期 0／1／2／3／5／10 日取原圖事件錨點；工作日計算與正常班表下班採後續核定政策，不聲稱 PDF 本身已定義工作日。

## Meegle 兩範本可驗範圍

| 範本 | 目前证據 | 尚缺 |
| --- | --- | --- |
| 334662 詠翔接案 SOP | 先前保存案件 24602542 三頁，52 節點、51 子任務 | 範本本體、完整拓樸、必填 Input、角色及附件 gate；個案追加不能自動當範本 |
| 566082 詠翔 SOP 精簡版 | 先前可見範本 ID／名稱 | 尚無範本本體及任務清單，不能聲稱讀完 |

本次 CLI auth status：project.larksuite.com 無 local token；預設瀏覽器 callback 不適用目前終端，已由官方 CLI device flow 開獨立 `sopaudit20260928` 登入頁。仍待使用者登入；不使用新應用密鑰，也沒有碰既有 Lark 管理分頁。

## 財務來源與可執行契約

四 PDF 指定的是「案件結算表」「實際入帳」「下包入帳」及對應交付證明，没有指定唯一 Base/table/field。已核實保存的 schema 可供唯讀來源投影：

| 來源 | 已存在欄位 | 能證明／不能推論 |
| --- | --- | --- |
| 報價總表 | 案件已入帳、累計已入帳、累計已請款、案件可請款總額、可請款未請、入帳資料檢核、入帳日期、付款條件 | 可建立來源收款核對摘要；需保留每報價原始識別、金額範圍／稅基，不重複加總；無法單憑勾選證明下包已付 |
| V4 工程確認單 | 案件已入帳、入帳日期、合約總額、預估總成本、實際總成本 | 原始來源宣告與成本摘要；實際成本不等於已付成本 |
| 合約明細工項 | 合約項次、工作項目、單位、數量、原始／報出金額、關聯填報工項 | 建獨立合約工項識別，跨組指派引用同實體；不重複計合約金額，也不回寫薪資配點 |

完整欄位 ID/type 僅採已保存 schema，列於 JSON `finance_schema_candidates`。已通知來源 owner 納入唯讀 normalized projection。現阶段未取得付款台帳／下包結清權威欄位，不以本地空 payment_batches 或零差額當結清。

正式 gate 接入順序：唯一來源鏈與範圍→有效收付證據／結算表→目前版本 PM＋行政原生財務核准→全部適用交付及前置完成→工作台結案。未對齊來源時回報具體缺項，不設不存在的本地帳務要求來假稱整合完成。

## 穩定來源 ID 對照

### 專案經理接案SOP20250826(1).pdf

| 穩定 ID（前綴 pdf20250826） | 原圖工作 | 原角色 | 完成範圍 | 原 Meegle 對照 |
| --- | --- | --- | --- | --- |
| intake.demand | 業主提出報價需求 | 業主 | quotation | state_14 |
| intake.number | 建立報價編號 | 報價組 | quotation | state_26 |
| intake.contact | 通知業主報價成立 | 專案經理 | quotation | state_28 |
| intake.subcontract_decision | 是否有下包需求 | 專案經理 | quotation | state_29 |
| intake.subcontract_quote | 下包提出報價 | 下包廠商 | subcontract_quote | state_35 |
| intake.offer | 提出報價，同時通知業主已提供報價 | 報價組 | quotation | state_15 |
| intake.returned | 報價單是否回傳 | 報價組 | quotation | state_16 |
| intake.followup | 追蹤報價狀況 | 報價組 | quotation |  |
| intake.lost_or_expired | 業主告知未得標／報價單有效期限到期 |  | quotation |  |
| intake.quote_end | 本報價工作結束 |  | quotation |  |
| intake.signed | 收到回傳單，合約成立 | 報價組 | quotation | state_25 |
| intake.case_identity | 建立案件編號、製作案件回傳本 | 行政 | case | state_27 |
| intake.award_contact | 得標後聯絡業主 | 專案經理 | case | state_17 |
| intake.confirmation | 確認單製作並將確認單傳遞至各單位 | 專案經理、報價組 | confirmation_version | state_4、state_83 |
| intake.permits | 執行工務確認單 | 行政、工務行政 | dispatch | state_2 |

### 專案經理案件執行SOP20250826(1).pdf

| 穩定 ID（前綴 pdf20250826） | 原圖工作 | 原角色 | 完成範圍 | 原 Meegle 對照 |
| --- | --- | --- | --- | --- |
| execution.confirmation | 確認單製作並將確認單傳遞至各單位 | 專案經理、報價組 | confirmation_version | state_4、state_83 |
| execution.permits | 執行工務確認單 | 行政、工務行政 | dispatch | state_2 |
| execution.field_accept | 外業確認單確認 | 外業經理 | confirmation_version | state_39 |
| execution.field_contact | 外業派工前聯繫 | 專案經理、外業組長 | dispatch | state_40 |
| execution.revision | 確認單修正 |  | confirmation_version | state_41 |
| execution.field_work | 外業作業 | 外業組 | dispatch | state_78、state_42 |
| execution.field_tracking | 外業節點追蹤 | 行政、外業經理 | dispatch | state_43 |
| execution.field_delivery | 外業完工或階段性通知 | 專案經理 | delivery_batch | state_44 |
| execution.indoor_work | 內業作業 | 內業組 | contract_item_assignment | state_45 |
| execution.indoor_tracking | 內業節點追蹤 | 行政、內業經理 | contract_item_assignment | state_46 |
| execution.indoor_accept | 內業確認單確認 | 內業經理 | confirmation_version | state_38 |
| execution.delivery | 提交成果及計價數量 | 工務助理 | delivery_batch | state_47 |
| execution.client_accept | 通知業主成果已繳交、業主確認計價單內容 | 工務助理 | delivery_batch | state_48 |
| execution.correction | 成果是否需補充修改 | 工務助理 | delivery_batch | state_49 |
| execution.billing_condition | 是否達成請款條件 | 專案經理 | payment_batch | state_56、state_74 |
| execution.pricing | 繳交計價單 | 專案經理 | payment_batch | state_55 |
| execution.invoice | 案件請款、進行客戶滿意度調查 | 行政 | payment_batch | state_59 |
| execution.received | 是否入帳 | 行政 | payment_batch | state_60、state_72 |
| execution.receivable_tracking | 請款情況追蹤 | 行政 | payment_batch |  |
| execution.subcontract_decision | 是否有下包 | 行政 | case | state_61 |
| execution.subcontract_payment | 通知下包廠商請款及撥款 | 行政 | subcontract_payment_batch | state_68 |
| execution.subcontract_tracking | 下包入帳追蹤 | 行政 | subcontract_payment_batch | state_71 |
| execution.settlement | 案件結算表製作 | 副總、專案經理、工務助理 | case_closure | state_69 |
| execution.close | 案件結束 |  | case_closure | state_70 |
| execution.client_contact | 執行中業主聯繫 | 專案經理 | recurring | state_50 |
| execution.weekly_field | 節點檢討與紀錄（工程） | 行政 | recurring | state_51 |
| execution.weekly_pricing | 節點檢討與紀錄（計價） | 行政 | recurring | state_57 |
| execution.assessment_field | 考評與結算計算（工程） | 行政 | assessment | state_52 |
| execution.assessment_pricing | 考評與結算計算（計價） | 行政 | assessment | state_58 |

### 內外業經理案件執行SOP20250826.pdf

| 穩定 ID（前綴 pdf20250826） | 原圖工作 | 原角色 | 完成範圍 | 原 Meegle 對照 |
| --- | --- | --- | --- | --- |
| team.confirmation | 確認單 | 專案經理 | confirmation_version |  |
| team.worklist | 建立工作總表 | 內業經理、外業經理 | confirmation_version |  |
| team.dispatch | 工作分派後傳遞給各組長 | 內業經理、外業經理 | dispatch |  |
| team.schedule | 工作預排總表 | 組長 | schedule_week |  |
| team.progress | 工作進度管控 | 內業經理、外業經理 | recurring |  |
| team.review | 檢討目前工進及工作情況 | 內業經理、外業經理 | dispatch |  |
| team.reschedule | 工作預排需調整 | 專案經理 | schedule_version |  |
| team.done | 工作完成 | 組長 | delivery_batch |  |
| team.signoff | 簽核確認單 | 組長、專案經理 | delivery_batch |  |
| team.group_settlement | 進行各組案件結算表／阿米巴計算表 | 內業經理、外業經理 | salary_assessment |  |
| team.node_review | 節點檢討與紀錄 | 行政 | recurring |  |
| team.monthly_assessment | 考評與結算計算 | 行政 | assessment |  |

### 內外業經理教育訓練SOP20250826.pdf

| 穩定 ID（前綴 pdf20250826） | 原圖工作 | 原角色 | 完成範圍 | 原 Meegle 對照 |
| --- | --- | --- | --- | --- |
| training.demand | 教育訓練需求表 | 專案經理 | disabled_learning |  |
| training.plan | 教育訓練計畫總表 |  | disabled_learning |  |
| training.capacity | 能力地圖 |  | disabled_learning |  |
| training.progress | 檢討目前工進及工作情況 |  | disabled_learning |  |
| training.delegate | 代理人設定 |  | disabled_learning |  |
| training.training | 安排教育訓練 |  | disabled_learning |  |
| training.outcome | 檢討教育訓練成果及生存線狀況 |  | disabled_learning |  |
| training.qualified | 檢視代理人能力是否合乎要求 |  | disabled_learning |  |
| training.accepted | 合格代理人 |  | disabled_learning |  |

## 尚未解決而不猜的項目

1. 兩個原生 Meegle 範本、第二範本特有工項、條件必填欄位及附件仍需真正登入讀取。
2. 圖中無箭頭接點標示的交叉線，僅保存可辨識分支；不把全部視圖順序當依賴 DAG，也不假定所有技術組一律串行。
3. 新來源 catalog 尚未發布到既有案件；既有已核准或已填成果的 SOP 升版須保留原 key、修訂版本與確認歷史。
4. 財務下包結清／稅基／重複報價範圍需明確權威欄位與真資料比對；原 PDF 沒有提供欄位映射，不能發明。
