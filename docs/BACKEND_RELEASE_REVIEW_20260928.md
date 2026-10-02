# 後端獨立發布審查（2026-09-28）

本次由 release_backend_review 獨立複核，依 APPROVED_PRODUCTION_PLAN_20260928.md、WORKFLOW_IMPLEMENTATION_20260928.md、SOURCE_IMPLEMENTATION_20260928.md。範圍為後端程式及隔離資料庫／HTTP 邊界測試；沒有新增或修改公司遠端業務資料。

## 結果與修正

初次完整 `python -m pytest backend -q`：**601 passed in 69.68s**，無排除。

發現一個既有測試未驗狀態欄的同步競爭問題：名冊同步 A 讀取中，B 先成功提交；A 隨後發生版本衝突或網路錯誤，原本會把 B 的成功狀態改成 error。人員資料雖未被舊資料覆蓋，畫面及維運卻會顯示失敗。

已在 `PeopleDirectoryService.failure` 加入預期同步代數檢查。失敗屬於舊代數時不修改較新狀態；目前代數的真失敗仍保留上次資料並顯示 error。先以兩個案例重現 **2 failed**，再修正；名冊、来源實體、財務、原生查回組合 **64 passed in 4.78s**。

另補原生週期查回的網路中斷回歸：先保存真正核對通過的測試回執，下一輪 timeout，確認歷史回執與 verified_at 原樣保留、設 verification_failed_at，且不能授權新的 fresh apply。查回專項 **6 passed in 3.46s**。這是 fake adapter 的故障驗證，不是 Lark 真送審證據。

第二輪全套與 ops 更新 staging 同時執行，結果 **607 passed, 1 failed**；失敗是測試程序已載入舊 staging fixture、部署打包清單已新增 backup_live_legacy.py 所致。ops 確認已同步 fixture；獨立重跑原失敗項 **1 passed**，ops 另報備份／runtime 組 13 passed。此輪不列為完整通過；待修改穩定後再記最終全套結果。

待 root／ops 程式穩定後，第三輪完整 `python -m pytest backend -q`：**613 passed in 66.76s**，無排除。包含 root 新增案件稽核範圍及 ops 備份／還原隔離檢查。

## 已複核的關鍵界線

- V4「已結案」保留 source_status／source_declared_completed，不能將本地節點或任務設為完成。來源實體測試直接驗證新匯入案件仍 pending。
- 正式結算仍要求前段報價／派工／確認單／計價、適用工程交付、原生財務共同核准、每筆來源報價收款一致性，以及有佐證的應付款宣告。空帳務清單及來源已結案不能取代這些條件。
- 正式本地財務票被拒絕；工作台只記交付確認，不操作正式收付款帳務。
- 名冊只讀核定四欄；同名不合併帳號。同步不升權、不恢復停權，測試授權不回寫正式權限。
- 原生背景查回只對已 attempted 的既有 UUID 做 GET，不送出或自動投票。已撤回會撤銷效力；公司／應用變更阻擋舊來源讀取。
- 薪資 Base 寫入與能力／訓練功能的封鎖仍由完整回歸涵蓋。

## 仍不能以本次測試宣稱完成

- Lark 正式應用權限發布、真名冊／九表／Attendance 同步與實際 Drive 存入讀回。
- 專用審批定義及節點席位映射、真正不同兩人共同核准、撤回端到端驗收。
- 公司正式帳號登入／停權／權限切換的瀏覽器與遠端整合验收。
- PostgreSQL 併發與還原、備份獨立保存、正式新版部署及釋出指紋核對。這些由 root／ops 負責，不能用 SQLite 或本報告通過代替。

本次程式修改限 `backend/people_directory.py`；測試為 `backend/test_people_directory.py`、`backend/test_native_poller.py`。未修改 app、storage、audit 或外部環境設定。

另複核代理遺留的本地 Meegle 範本本體，補出 334662 v137 的 62 節點／52 子任務／71 連線；詳見 `MEEGLE_TEMPLATE_REVIEW_20260928.md`。這更新了舊文件「僅有單案」的證據狀態，不代表已完成全部流程實作。
