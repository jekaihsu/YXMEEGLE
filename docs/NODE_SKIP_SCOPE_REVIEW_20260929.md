# 節點跳過範圍與原生審批第二次檢查

## 已實作

- 新跳過申請明示 `skip_scope_version=2`，使用 `approval_scope.task_scope` 保留任務內容、責任人、期限、數量／單位、工項關聯，加上實際任務狀態、本節點文件、佐證與核准席次。
- 不再把全案 quotes、source_records、source_scope_hash 納入新跳過內容雜湊；其他報價成本或來源行政備註刷新不會讓跳過孤立失效。
- 舊申請缺少版本一律沿用 v1 全量演算法。預設 snapshot/fingerprint 也保持 v1。即使舊 binding 為 outcome_unknown，不重簽、不改 UUID、不改 content_hash；舊範圍不符仍禁止採用，原始 binding 保留給 readonly poller 查回。
- 未知未來版本 fail closed。PM＋該組主管規則不變。

驗證：`test_node_skip_scope / test_node_skip / test_native_approval / test_native_poller` 共 **79 通過**。新增涵蓋無關成本刷新、真工項數量／責任人／期限／成果／狀態改變、舊 unknown binding 保留。

## 回報 root 的原生流程檢查

1. prepare/submit 的每次 HTTP 授權應重新檢查案件執行歸屬；只在入口檢查存在競態。root 已於 fresh authorize／送前 checkpoint 補核對。
2. 最初僅閱讀 poller 分支，懷疑 `applied` 會被改回 `approved`；補查 `native_business_status` 後確認已有保留 `applied`，原判斷撤回。新增實際背景 poller regression，確認 v2 已套用跳過在無關成本變更後仍維持 applied／approved_skipped，且只 GET。
3. root 已將 cancel 改為讀回原 immutable identity／form／UUID，不因目前 mapping 或 definition 改版阻止原申請撤回；仍須原申請人，遠端已 APPROVED 不可撤回。未知取消只讀查回不重送。

更新驗證：新增背景已套用跳過 regression、scope、node_skip、native service/routes/poller 共 **62 通過**。

此輪僅本機程式與測試，沒有送出或撤回任何真 Lark 審批。

## 獨立邊界回歸

新增 `test_native_cancel_independent.py`、`test_environment_gate_independent.py`，並擴充節點範圍測試，共 **42 通過**：

- 目前映射移除／定義改版後仍可撤回原 pending；UUID、申請人、表單內容、immutable binding 被替換時不 POST；遠端已核准拒絕撤回；取消前 DB checkpoint 失敗不送出。
- 舊 workspace 缺 environment 只按核定 namespace 遷移，保留資料；既有 demo/test/production 與 namespace 衝突一律 409；非核定公司、未核定應用不能取得隔離執行權。
- 正式 pending／Meegle 案件在 prepare 前擋住；definition GET 之間被改回 Meegle 時，未寫 attempted、未 POST。
- v2 snapshot 新增 project/node source_missing、archived_at、migrated_to 的布林存在性。task.source_missing 由共用 task_scope 正規化。以真 preserve_missing_sources writer 測試刪除、恢復及成果保留。

目前上述範圍無已重現、尚未修復的 P0/P1 阻擋。仍需 root 判定「來源已缺失的案件，在缺失前未有審批，可否新建審批」：存在性雜湊能讓後續變更失效，但不等於入口拒絕一開始已缺來源。正式 Lark 審批／專用 Input 真實 E2E、雲端環境設定及全套回歸不由這 42 個本機測試代替。
