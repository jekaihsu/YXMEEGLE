# 新日報驗收矩陣 — 2026-09-27

## 範圍與歷史界線

使用者已確認原有 535 筆 V4 日報是舊系統搬遷資料。先前快照的 0/535 配對結果保留為歷史觀察，**不能拿來證明新填日報失敗**。本輪把測試新列以原生 record ID 獨立追蹤，不用新舊混合總數當成通過與否。

正式應用權限維持唯讀。真列建立使用既有使用者 CLI 授權；程式驗收使用現有 application reader，在記憶體重播，尚不代表正式工作區資料庫已同步更新。

## 真實寫入前置查核

- 唯讀列出 V4 17 個工作流程；13 個 enabled，取得全部 13 個定義。
- `wkfHzJLC5be1TYk6`「新工作單展開車程夜測住宿津貼明細」會寫津貼匯整明細；觸發條件包含「所屬成本單」非空且未展開。
- 本輪新增只寫外業工作單的原生案件連結與 `CODEX-NEW-DAILY-ACCEPTANCE-20260927` 備註。成本、人員、數量、點數、檢核全部不填，因此不符合上述津貼自動化條件。不修改、停用任何 workflow。
- 新列沒有業務日期，應誠實顯示 `missing_date`；不把填表時間或同步日期當作工作日。完整日期／成本關聯情境只在離線 fixture 測試，不掛真實成本單。
- Live schema：外業 131 欄、內業 53 欄。外業 `fldfpNpQiE` 是往工程確認單的 link，`fldLwrDyJk` 是 text；成本 link 沒有預設值。欄位值只寫這兩個已核對欄。

私有證據：`.runtime/new-daily-workflows-list.json`、`new-daily-workflows-private.json`、`new-daily-schema-*.json`。不得把含業務設定／個人 ID 的完整私有檔包入部署。

## 離線可重現矩陣

執行：`python -m pytest backend/test_new_daily_acceptance.py -q`。

| 情境 | 必須結果 | 首輪 |
| --- | --- | --- |
| 日報直接關聯確認單 | 對既有案，不增案／任務、不完成任務 | 通過 |
| 內業／外業工項→填報工項→合約明細→確認單 | 使用原生 ID 鏈對案 | 通過（2 項） |
| 重複同步、備註修改 | 同一日報 ID 一筆，更新內容 | 通過 |
| 無引用、失效引用 | 待配對，不猜案 | 通過（2 項） |
| 兩個有效案引用、文字案號與 link 衝突 | 歧義待核對 | 通過（2 項） |
| 自建日報改指另一既有案 | 同一日報移動，不增案 | 通過 |
| 只連成本單 | 成本／日期不能當案件識別 | 通過 |
| 日期公式與成本 timestamp 一致／衝突／缺漏 | 台北日、衝突空日期、不得取同步日期 | 通過 |
| Native 人員 ID 與同名／偽 ID 文字 | 只用真 ID，不靠姓名；checkbox不算核准 | 通過 |
| 舊搬遷未配對列＋新正確列 | 新列獨立驗收不被舊列掩蓋 | 通過 |
| 有效＋失效原生關聯混合 | 未完整解析不得直接認定唯一案 | **缺陷：現直接配案，已交後端** |
| 外業組長／組員 user 欄 | 保留 native `source_actor_ids` | **缺陷：現遺漏，已交後端** |

首輪 13 passed / 2 failed。不是全部通過；後端修正後應重跑此矩陣及既有 source tests。

## 真列追蹤與清理

本輪只建立一列：`H7W6b0PFWaVF1BsgqXJj3pQ9pXb / tbl5zPLS0ExWNEty / recvwqDsYNAeUb`，連到事先唯讀確認仍存在的 `recvsnzx3bjtAA`（C115264）。穩定內部日報 ID 為 `src-f432473a769589f4d008`。操作順序 create→edit→unlink→relink→delete，所有修改／刪除前都回讀測試備註，且 hardcode/journal 雙重限制為本輪 ID，不能操作其他日報。

| 真實步驟 | 應用讀取與匯入結果 |
| --- | --- |
| 新增 case link＋測試備註 | 新列 matched C115264；15 正式案、266 接案不變；535 舊列另列待配對 |
| 重複匯入 | 同一日報 ID 仍只有一筆；case/task ID/status/output 不變 |
| 修改備註 | 同 ID 顯示 UPDATED 備註，不新增日報／案件 |
| 移除測試列案件 link | 新列轉 `missing_reference`，不掛任何案、不建立新案 |
| 重新掛回既有確認單 | 同一 ID 重回 C115264；仍不重複 |
| 刪除自建列 | CLI delete 成功；application fresh 外業日報全表確認測試 ID 不存在，日報總數回到 535；journal 已標 cleanup_completed |

首輪基線與新增是現有應用身分的全九表 fresh read（2,569→2,570 列）。後续 edit/unlink/relink/cleanup 為同一 application reader fresh 讀外業日報全表，搭配先前已核對的案件基線重播。所有匯入均在獨立記憶體狀態，不直接改正式工作區 DB，不能以此宣稱正式 UI 已完成同步驗收。

新列 `mapping_status=missing_date`、`source_actor_ids=[]` 是刻意留空成本／人員的結果；來源審核預設回傳 pending，未核准任何審核。CLI 回讀確認測試列成本、組長帳號、組員帳號均為空；沒有津貼觸發所需的成本關聯。

追蹤：`.runtime/new-daily-live-journal.json`、`new-daily-create-response.json`、`new-daily-record-delete-delete.json`、`new-daily-app-*-report.json`。可重現唯讀驗收腳本：`scripts/verify_new_daily_acceptance.py`。建立 helper 已加 journal 存在即拒絕重建的保護，避免重跑生成第二列。

## 後端修正後獨立複驗

2026-09-27，`python -X utf8 -m pytest backend/test_new_daily_acceptance.py -q` 的全部 15 項已通過（與管理報價單項合併執行共 16 passed）。有效＋失效引用以及外業組長／組員原生身分兩項首輪缺陷已修。

清理後亦發現原增量投影保留已刪除日報為有效列（S6）。修正採完整表範圍證據：只有 ready、數量符合、含明確 Base/table 身分的完整快照才能標示 `source_missing`；保留歷史與原來源欄位，不當有效日報，也不猜成新案。來源 agent 的真實清理快照本機重播紀錄 `.runtime/new-daily-deletion-fixed-20260927.json` 顯示有效日報 1→0、歷史缺失 1、原 535 搬遷列不變、重播穩定、案件／任務身分及狀態／成果不變。此重播未寫遠端、未碰正式 DB；不宣稱真實線上 UI 已同步。

測試 agent 另從 relinked 與 cleaned 私有快照獨立重建、重播，結果一致；證據 `.runtime/new-daily-independent-cleanup-replay-20260927.json`（零網路請求、未碰正式 DB）。唯讀验收腳本亦已傳入完整表覆蓋範圍，並分開回報「仍有效」與「保留為來源缺失歷史」，避免把保留歷史誤報為刪除失敗。
