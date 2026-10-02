# 2026-09-30 剩餘程式級發布缺口（獨立抽查）

範圍：對照 `ISSUES_MASTER_20260929_CLAUDE.md`、`EXECUTION_TRACKER_20260930.md` 與目前檔案。僅列本次仍有程式證據的缺口；不重列真人 OAuth、真人審批、異地還原、24 小時觀測。這不是全系統審查閉環，也不代表已部署。

| 優先度／項目 | 證據 | 風險與最低修法 | 確認程度 |
|---|---|---|---|
| P1：背景同步仍干擾部分前台提交（#80/#81，部分修） | `backend/source_sync.py:128` 成功同步、`:160` 排程占位均推進 workspace version；`backend/people_directory.py:169`、`:261` 同樣處理；`backend/app.py:413` 僅指定前綴動作採案件版本，`node_complete`、`project_roles`、`sop_*`、`approval_*` 仍用全域 CAS | 常用留言／任務已有案件版本保護，不能再聲稱全部動作受影響；但完成節點、角色、SOP／審批表單仍可能被無業務異動的五分鐘同步拒絕 409。最低修法：同步排程／健康狀態獨立修訂號；對確定單案的剩餘動作採完整案件 CAS，保留跨案授權重驗。補「只同步名冊／來源狀態，完成節點不衝突」HTTP 回歸。 | 程式路徑已確認；本次未重做並行 HTTP 壓測。 |
| P2：SOP 套用既有未完成任務未更新契約版本 | `backend/sop_contracts.py:193` 既有任務 changes 只更新 key、refs、applicability、disabled、required；`:126` 提出報價前置檢查卻限定 `sop_contract_version == VERSION`；新任務 `:147` 才設定該版本 | 新模板套用後，舊任務可能仍保留舊契約版本而不觸發新報價前置條件；同時責任說明／追蹤類別也未遷移。最低修法：對未完成任務以稽核化遷移更新行為版本與適用 metadata；已完成結果保留；補由舊模板升級後缺下包判定不得報價的測試。 | 已以純記憶體呼叫證實同一 quote_provide 任務舊版本 blockers=[]、新版有阻擋；尚未完整重演管理員套用 HTTP 流程。 |
| P2：舊 requirements 未自動退出，核定「日報參考」僅新模板完整生效 | `backend/policy.py:98` 僅缺 requirements 才補新版；`backend/operations.py:202` 繼續逐條強制；`:462` 必須另行 SOP 套用才換 requirements | 對仍可使用的既有案件／隔離測試案，舊必填日報／照片可能繼續卡住；舊案排除減少正式切換暴露面，但不能把模板修改當作既有任務已遷移。最低修法：明確核定版本遷移／套用流程，先列出受影響案件並保留完成歷史；新舊狀態分別回歸。 | 純記憶體實測 upgrade 保留舊 daily requirement；影響正式可見案件的數量尚未核實。 |
| P2：名冊中斷的公司准入可用性仍缺明確預警 | `backend/production_access.py:31`、`:71` 至 `:86` 在 900 秒後拒绝一般員工；`backend/people_directory.py:242` 失敗只存狀態；`backend/runtime_health.py:46`／`:50` 主要檢查 worker 心跳／成功時間 | worker 仍活著不代表名冊仍新鮮；員工可能統一失去正常操作，且重新 OAuth 無法解決名冊過期。最低修法：獨立名冊 freshness 健康項目、到期前告警、失敗重試／維運復原入口；不要為可用性直接放寬在職／停權檢核。 | 准入失效程式已確認；未證實部署外部監控是否已有等效告警。 |

資料隱私抽查：`workspace_projection.py` 已有來源欄位白名單、個人資料投影、請假代理過濾，因此本次不重報「原始薪资欄位仍全量外洩」。但 `work_schedules` 與 `people_directory_status.issues` 仍整份隨 workspace 回傳，見 `workspace_projection.py:66` 起的投影及 `people_directory.py:228`。班表全員可見是否合乎公司規則未核定，暫列待決定／補 API 欄位白名單測試，不能直接宣稱已證實薪資外洩。

本次只有 read-only 程式查閱與純記憶體驗證；未修改實作、未呼叫 Lark 寫入、未更動部署。

## 2026-09-30 後續修正驗證

上述 P1 已完成本機程式修正（尚不等於正式部署）：`/api/actions` 對 node_complete、project_roles、sop_apply 與明確 approval 動作採案件版本，申請 ID 必須同案件；跨案 SOP 發布維持全域 CAS。storage 已使 root 層 approvals／sop_requests／financial_requests／node_skip 等業務變更提升所屬案件版本，移案時兩案都失效，SOP 模板異動保守使所有案件失效。

`backend/test_extended_project_concurrency.py` 16 項 HTTP 正反例通過：背景狀態及名冊最後同步時間更新後可完成節點、更新角色、套用 SOP、建立／撤回申請；同案實質異動仍 409；借別案版本 422；最新權限仍重驗 403；跨案發布仍檢查全域版本。原生審批 REST 與 Input REST 本輪未改，仍保守使用原本並發規則，因此不能宣稱整個系統已完全消除背景版號衝突。
