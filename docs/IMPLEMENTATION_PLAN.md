# 詠翔專案管理 prototype 技術實作計畫

版本：v0.4｜日期：2026-09-25｜性質：實作及驗收計畫，非完工報告。

## 1. 架構與執行模式

- React＋TypeScript 負責繁體中文 Meego 風格互動；FastAPI 負責登入、授權、狀態機、檔案與來源快取；PostgreSQL 保存工作區、事件及持久資料。同網域 Docker 部署 Zeabur 預設 HTTPS 網域，雲端不用 SQLite，資料庫及 /data/uploads 文件掛載持久 volume。prototype 單實例並允許維護短停。
- demo 模式使用明確隔離的示範工作區與種子角色，操作寫入伺服器資料；唯讀來源另存 source cache。真實同步不自動把示範紀錄變成正式紀錄。
- 正式公司工作區強制 Lark OAuth 與 tenant 驗證，缺少設定不得自動切換 demo。APP_ENV=production 的雲端 preview 僅在 DEMO_MODE=true 且 ALLOW_CLOUD_DEMO=true 時明確開放示範身分、模擬確認與示範重設。這些操作只作用於隔離的 demo 工作區，不能偽造正式核准。真實資料入口即使在 preview 亦須有效 Lark session，不接受 demo 角色。
- API_CONTRACT.md 為前後端協作的 wire contract；本計畫補充業務檢查與部署要求，不建立另一組端點名稱或狀態值。

## 2. 實作順序與接口

| 階段 | 實作內容 | 完成證據 |
| --- | --- | --- |
| 1. 持久化骨架 | Workspace、版本、確定性種子、事件、登入模式、健康檢查 | API 可讀寫，重啟後資料仍在，cloud demo 不可冒用真實身分 |
| 2. 核心工作 | 九節點、SOP、分派繼承、期限初排、組日分配、開始／完成／退回、文件留言 | 前後端真實操作，角色與必要輸出 gate 有效 |
| 3. 受控變動 | 展延、設計變更三線、送審凍結、手動套用、新舊版本及審批歷程 | 狀態矩陣測試、局部影響及重複執行測試 |
| 4. 來源證據 | 來源設定、同步、快取時間、V4 對應、V3 日報習慣驗證 | 唯讀請求證據，無遠端寫入，案號證據不完成 SOP |
| 5. 部署交付 | Docker、Zeabur 設定、DB 與檔案 volume、備份恢復、正式限制 | 建置、整合及瀏覽器驗收；未實測項目明列 |

| API | 契約與重要限制 |
| --- | --- |
| GET /api/session | user、users、mode、auth_configured；不得回傳來源憑證 |
| POST /api/demo/session | 僅明確啟用的 demo，使用 user_id 切換示範角色 |
| GET /api/workspace | 回傳完整 Workspace；正式模式須登入 |
| POST /api/actions | action、version、request_id 及作用範圍；成功回最新 Workspace；過期版本回 409 |
| POST /api/files | multipart file、project_id、node_id、direction、version；成功回 Workspace |
| GET /api/files/{id}/download | 必須登入並有該資源的讀取權 |
| GET /api/sources | configured、last_sync、status、message、tables、records；來源未設定明示，真實資料限有效 Lark session |
| POST /api/sources/sync | 唯讀 Lark，寫入隔離快取，不改來源或示範案件；真實 session 授權不能由 demo 角色替代 |
| GET /api/auth/lark/login 及 callback | OAuth 入口與回呼；state、tenant、session 檢查 |
| POST /api/approvals/{id}/refresh | version、instance_code；僅真實 Lark 身分讀取既有原生審批，未驗證案件／範圍綁定時不授權執行 |
| GET /api/health | 部署健康檢查，不洩漏密鑰或來源內容 |

事件動作名稱使用 task_start、task_complete、task_return、task_update、task_add、node_complete、participants_update、comment_add、approval_create、approval_submit、approval_confirm、approval_lark、approval_execute、approval_withdraw、change_resume、file_link、calendar_update、demo_reset。各 payload 及角色依 API_CONTRACT.md，不允許任意狀態欄位 patch 繞過動作驗證。

## 3. 狀態機與一致性

- Node：pending / in_progress / completed / paused / superseded。Task 另有 rework。Approval：draft / pending / approved / executed / rejected / withdrawn；lark_status：draft / pending / approved / rejected。
- task_complete 由當前任務負責人或有效示範代理完成，輸出非空並符合指定輸入 gate。node_complete 由節點負責人執行，必要有效任務皆完成且沒有相關待審變更；PM 無 blanket override。
- participants_update 只更新仍在繼承的任務，不能覆蓋個別改派。初次排程寫 original_due_date；已有 due_date 的修改一律透過審批執行。
- 展延送審不凍結；原期限持續有效。Lark 核准後由 PM／指定主管 approval_execute 套用 dates，保存原期限與歷程。
- 變更送審將指定 work_item_id 及下游同工項工作暫停；三線 owner_confirmed、client_confirmed、lark_status=approved 同時滿足才 approved。核准仍不自動換版；執行保留舊任務為 superseded 並建立下一版。
- 駁回或撤回不自動解凍，change_resume 需原因且由負責人／PM 操作。凍結前狀態應可追溯，不把原已完成任務恢復成進行中。
- 每次成功 mutation 與 event 原子提交；version 檢查在提交時執行。request_id 冪等記錄與操作結果一併持久化；同鍵不同內容應拒絕，不回播另一個動作的結果。前端收到 409 重新讀取並要求重新確認，不靜默重試覆蓋。
- 來源未讀取、失敗、缺值和真實 0 分開。日期＋部門＋案號的日報證據只標示案件已有工作，不任意匹配到 SOP 或批次、不改 task.status。

## 4. 介面、資料及運行限制

- 首版介面採 Workspace 整體讀取與 mutation 後返回完整 Workspace；適合 prototype，不宣告已適用全公司歷史資料量。正式放大前量測並增加分頁、查詢及獨立事件載入。
- 財務與點數欄位缺值 nullable；金額與組日分開。工項總額與 SOP 分配不得在父子層重複加總，超配顯示待調整。
- 外部來源必須處理分頁、逾時與失敗；保存最後成功同步時間及錯誤摘要，避免把失敗快取偽裝成零筆資料。未驗證 record 關聯不以名稱猜接。
- 檔案以非使用者可控路徑命名，保存原檔名及大小。大小上限、允許格式、連結協定及來源讀取上限由實作設定明示；未完成掃毒不得標示已完成掃毒。下載不得以靜態公開目錄繞過認證。
- OAuth secret、session secret、DB URL、Lark token 放部署環境變數或受控 secret store，不進前端、Git、回應或事件日誌。Session 在 production 使用 Secure、HttpOnly 與適當 SameSite；寫入操作具來源／CSRF 保護。
- 正式審批與請假代理未設定前返回明確能力未啟用，不採人工勾選偽造正式結果。來源唯讀能力與正式外部寫入是不同授權及驗收範圍。

## 5. Zeabur 部署與恢復

1. 建立前後端 Docker 建置程序及 PostgreSQL 服務，透過環境參數設定 production 模式、資料庫、檔案目錄與 Lark OAuth。部署前確認映像不含本機憑證與真實私密資料。
2. 以持久 volume 保存 Postgres 資料與上傳檔案；啟動時執行可重入的 schema 初始化／migration，不以重播種子覆蓋已有工作區。
3. 配置 HTTPS 網域、OAuth callback 白名單與公司 tenant，健康檢查區分服務存活與依賴可用；正式模式不自動退回 demo，preview 須明確雙開關且仍隔離真實資料。
4. 備份應包括資料庫一致性快照、檔案及 schema／應用版本；同一恢復點能重建檔案索引及事件。prototype 交付備份還原指令，正式排程、保留期與責任人由公司指定。
5. 在隔離環境實際還原一次，抽驗案件、任務、審批、事件與至少一份附件；保存檢查結果。未完成恢復演練前不宣告備份已驗收。
6. 回退採上一容器版本及相容 schema；存在不相容 migration 時先備份並制定資料恢復程序，不只回退前端。

## 6. 測試矩陣及交付

| 類別 | 必測場景 |
| --- | --- |
| 單元／API | 非負責人完成、節點強制通過、既有期限直接修改、缺輸出、版本衝突及相同請求重送 |
| 審批 | 三線任一缺少不得執行；送審局部凍結、核准仍凍結、駁回後明確恢復、換版保留舊資料 |
| 展延 | pending 舊期限有效、approved 尚未套用、executed 僅更新核准 dates、重送不重複 |
| 資料 | 明確 0／空白、同案號多工項、同工單多人、缺來源關聯、同步失敗、來源／demo 隔離 |
| 權限 | 正式 Lark 工作區無 demo 切換／模擬核准／重設；preview 的 demo 不能讀真實來源或審批，未登入不能讀公司 Workspace 與附件 |
| 瀏覽器 | 駕駛艙下鑽、我的工作、開始完成、留言附件、角色切換、完整變更與展延旅程 |
| 運維 | build、啟動健康、重啟持久化、備份還原、OAuth 真实設定後正反向驗證 |

交付應包含程式、測試、Docker 與 Zeabur 部署說明、備份還原程序、PRD v0.4 Markdown／Word、來源對應、驗收記錄及未完成限制。驗收記錄將「已通過、未設定、未測試、失敗」分開，不把需求描述轉成完成宣告。
