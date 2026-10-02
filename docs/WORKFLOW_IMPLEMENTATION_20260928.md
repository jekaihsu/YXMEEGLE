# 正式流程實作紀錄（2026-09-28）

此文件記錄程式與本機驗收，不代表正式部署、Lark 真送審或真通知已完成。

## 已實作

| 功能 | 實際行為 |
| --- | --- |
| 統一指派 | 個別改派、參與人員及案件角色改派共用 helper。新子任務／新來源工項／SOP 新增任務繼承節點 owner；override 及已完成／封存任務保留。逐項保存前後值、來源、操作者及規則版本 |
| 正式人員資格 | 正式新指派與排程啟用共用 `production_access.admitted`；依名冊同應用、在職及有效狀態，指定初始化管理員依核定例外；未同步名冊不靠姓名猜人 |
| 自動啟用 | worker 到排程日且 owner、前置成果、外業公務證明等條件齊備時，將 pending 改為 in_progress，保存 activated_at／activation_source。**不填 started_at、不代表工時**；缺件、來源異動、暫停、核准跳過、已結案不自動啟用 |
| 本人一次確認 | `task_batch_complete` 選 1–50 個本人項目。每項包含 project_id、node_id、task_id、revision、confirmation_hash、output；整批先驗再寫。任一非本人、失效版本、未啟用或缺成果，全批不變。每項獨立 confirmation 與 audit；外層 request_id 沿用 API 冪等回執 |
| 任務開始語意 | 自動啟用後仍可明確按開始作業，才記 started_at；本人交付可保留 started_at 空值，不捏造開始時間 |
| 雙席隔離 | 所有多席節點不能同一人兼任；代理人不能同時投兩席。既有重複實際操作者亦不算有效共同核准 |
| 節點審核範圍 | review_hash 改取節點自身任務、成果、佐證、文件及適用規則，不再取全案 revision；不相關展延不讓全案已完成節點重作。財務既有合法職責交接保留另一方票與歷史 |
| 結案前置 | 結算不能略過報價、派工、確認單及計價；前段退回即撤銷結算完成。工程成果、雙方收付款及既有結清 gate 保留 |
| 正式帳務保護 | 正式 `finance_*`、`payment_*` 直接帳務操作 403；demo/test 可演練。財務證明使用獨立 native financial request，不冒充金額入帳或結清 |
| 人員管理 | 非管理員不得更改管理員；部分更新不自動恢復停權、不清除部門／預設工作區；正式不能手填任意 ID 新造人員 |
| 原生審批接點 | 正式 change/extension execute 與 node skip apply 必須有綁定目前範圍、目前核准人及五分鐘內的已核實回執；模擬布林不可代替真票。已生效 waiver 不因時間經過直接抹掉；查回撤回／失效會還原節點狀態，保留歷史 |
| 設計變更凍結 | 原生送出第一次 durable attempt 才凍結影響任務，prepare 不凍結；保存原狀態及逐項事件，重送不重複。拒絕、撤回或確定性失效仍須填理由明確恢復 |
| @ Lark 通知 | 留言保存後按 comment_id＋recipient 去重排入持久工作。正式送出前重验同應用在職身分；訊息含案件／任務／留言深鏈。demo/test 僅 simulated。每個 comment.notifications 顯示 queued／succeeded／simulated／blocked／outcome_unknown |
| 通知不確定結果 | timeout、不完整回應、遠端成功後本地 checkpoint 衝突皆不能盲重送；已保存回執沿用。HTTP boundary 使用穩定 UUID；真正投遞仍需公司正式連線及訊息權限 |
| 考評停用 | 停止新建 monthly 考評；舊 monthly 保留歷史並 disabled，舊待送考評摘要 blocked。財務結算不借此機制執行。訓練／能力功能與薪資 Base 回寫封鎖保持 |
| SOP 識別 | 新範本 2026-09-28.1 提供已核定任務穩定 key。版本套用按 key，不以同名合併；舊無 key 唯一同名可遷移，歧義則停止。新加任務沿父 owner，既有成果保留 |

普通成果仍在工作台操作與依 SOP 確認；**結構資料存 Lark Base、檔案存 Drive 的既定權威未變**。暫存檔未取得 Drive 核實回執仍不視為正式交付存妥。file_link 已支援獨立文件分類 category_id 與 file_key，不把工作節點當文件類別。

## API 與前端契約

`POST /api/actions`：`action=task_batch_complete`，`payload.items=[{project_id,node_id,task_id,revision,confirmation_hash,output}]`，外層照常帶 version／request_id。成功回完整 workspace；失敗無部分完成。任務回應提供 confirmation_hash、activation_blockers，動作仍由後端再驗。

`comment.notifications[]` 每筆含 recipient_id、status、job_id（未能排入者可無）、message_id／simulated／error。只有 succeeded 且非 simulated 可顯示 Lark 已送達；outcome_unknown 不提供一般重試。

原生 prepare／submit／poll 路由及回執驗證由來源 agent 實作；此組負責 apply／execute gate 與凍結恢復。暫時查回失敗需顯示待核對，不延長最後成功回執時間；確定性內容／核准人不符清除可信核准。

## 可重現驗收

- `backend/test_workflow_automation.py`：指派繼承、override、到日／缺件啟用、實際開始時間分離、全批原子性、正式身分、SoD、前置結清、穩定 SOP ID、考評停用及變更凍結。
- `backend/test_batch_confirmation_api.py`：完整 FastAPI＋隔離 SQLite 驗批次成功、request_id 重送不重複、整批回滾。
- `backend/test_mention_notifications.py`：mock 遠端邊界，真實持久 worker 驗去重、深鏈、模擬隔離、停權／跨應用、timeout、回執後保存衝突及無效回應。**没有實際發送公司訊息。**
- 既有 operations、workflow_completion、node_skip、sop_deadlines、worker_reliability、learning_disabled 一併回歸。
- 第一輪八檔 248 項通過；追加通知錯誤、SOP 識別、原生撤回修正後專項 97 項及後續 83 項通過。完整新組合結果以最後本輪回報為準，不將重複執行次數相加。
- 最新十一檔整合 **301 passed, 1 deselected in 31.77s**。排除項僅 `test_backup_restore_normalized_rows_and_file_hash`：測試寫未登錄附件 `sample`，新版備份排除後還原找不到該檔，已交備份 owner 核查；不是將失敗算作通過。
- 正式 pricing／settlement 的本地確認，另須同 project／node 的原生財務共同核准有效回執。新完成需 5 分鐘內查回；既成成果用非時效有效性，確定撤回／範圍變更重新待處理，暫時網路失敗不假造撤回。原必備成果與結清門檻仍保留。此門檻與缺回執不能靠本地雙票通過已測試。

## 尚未可宣稱完成

1. **Meegle 全範本尚未完成盤點**：後續獨立審查已找到並擷取真正 334662 v137 範本本體，62 節點（含 Start）／52 子任務／71 連線，不再只有早期單案 52／51 的證據。詳見 `MEEGLE_TEMPLATE_REVIEW_20260928.md` 與同目錄 JSON 清單。566082 本體仍未取得；334662 的條件圖執行等價、完整 Input／附件必填映射及既有成果遷移仍未完成。新範本明示 `coverage_status=partial_inventory`；不匯入 Meegle 舊案，也不以 grouped tasks 冒稱全 SOP。
2. **正式財務結清來源契約**：現來源只有合約／預估成本／實際成本摘要，不能由零差額猜已結清。直接帳務關閉後，正式結算 gate 尚需接上經核定的實收付／結清來源與 native 財務證明。缺證據維持阻擋，不能為跑通畫面改成成功。
3. **正式遠端驗收與部署**：需要真實公司應用的審批定義映射、本人共同核准、Drive 回執及 @ 訊息送達演練。以上本機測試不替代正式角色／兩瀏覽器／worker 重啟的整案驗收。
4. **既有 SOP 升版**：新版本不自動覆寫既有已發布／已操作內容，須透過現有改版申請與核對。完整替代仍需來源範本覆蓋對帳。

## 跨 agent 審查修正

此組指出並與來源 owner 協作修正：applied skip 重查成功不能退成 approved；native change 首次送出須凍結；核准者須同應用已核實在職；回執須對目前公司權威；財務交付證明須有效且 Drive 已核實。來源 owner 另修查回失敗不得讓舊回執繼續授權新 apply。此組再修撤回後清除節點 waiver 引用及失效變更的明確恢復入口。

追加財務原生範圍核對：來源 owner 已將該財務節點的實質任務內容與必備條件納入 scope，修改成果或來源金額會令原回執失效；財務草稿限定 pricing／settlement。更新後獨立複跑 native routes／service、workflow automation、batch API、mentions **100 passed in 7.50s**（與上述測試有重疊，不相加）。
