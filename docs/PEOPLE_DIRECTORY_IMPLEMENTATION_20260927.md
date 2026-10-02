# 動態人員名冊與工作台標註實作

> 2026-09-27 真實 schema 與四欄唯讀驗證完成。名冊 69 列，63 個有效帳號（61 在職、2 明確離職），6 列缺帳號待核對。這是實際 API 讀取與本機記憶體合併驗證，尚不代表已部署或正式資料庫已同步。「內外勤」只作來源工作類別，不能推論實際組別；缺在職值不能當離職。

## 來源與權限

`backend/people_directory.py` 以專用 Lark 應用身分讀取 `VwAsbezz9app3YsramgjduLYp2U`，尋找唯一的「人員名單及資料」表。真實表 `tblrXclB7LSknReZ` 的「人員」是原生人員欄位（type 11），records 明確指定 `user_id_type=open_id`。保留舊「Lark帳號」原生人員欄相容；兩候選同時存在或型別不符會停止讀取，不猜映射。

真實來源每次只送四個 `field_names`：「人員」「姓名」「在職」「內外勤」。已確認姓名為 type 1、在職為 type 7、內外勤為 type 3（外勤／內勤／空選項）。在職僅布林 true／false 分別代表在職／離職，缺欄、null 或其他型別保持 unknown。來源工作類別保存 `source_work_category`；未有實際部門時顯示「來源內外勤：外勤（待確認組別）」等提示，不覆蓋人工已確認部門。缺真正部門欄保留 field_warnings。程式不讀薪資、銀行帳號、身分證；若回應額外夾帶未要求欄位，停止處理且不保存。

表、欄位、紀錄都完整分頁；缺has_more、重複頁碼、重複record ID或中途失敗即不套用新名冊。缺帳號、多帳號、重複open_id或缺姓名列列為待核對。同名但不同ID保持兩個人，不做姓名推測合併。

同步限 `lark-<LARK_WORKER_ORGANIZATION>`，且該公司須在 OAuth 允許清單；demo/test不直接讀正式名冊。應用ID記錄在目錄快照及新profile的 identity_app_id。已知不同行應用的身分不能合併、登入或標註；舊資料缺app metadata時保留相容，不憑姓名轉換openid。

## 更新與歷史保護

PersonRow是公司共用人員資料，工作區users跟随目前profile讀取。新進者預設 member、capabilities=[]。同步僅更新姓名、部門、名冊狀態與來源識別；不覆盖role/capabilities/default_workspace，不恢復active=False。

明確「離職／已離職／不在職」狀態可停用帳號；未提供、無法識別、來源少列或空表都不等於離職。來源回職也不自動恢復已停用帳號，须管理員核對。缺漏舊人保留directory_missing待核對，舊任務、評論、核准與案件資料不改人員ID、不刪除。

讀取前、每次HTTP邊界與提交前重新檢查操作者權限及公司／應用設定。部分失敗保留先前users、最後成功時間；以目前資料庫版本原子寫入，不用前端舊整包覆蓋。

每次成功同步增加sync_revision。若另一同步已先完成，較舊的在途快照回409且不能覆盖已提交名冊；保留最新人員與最後成功時間。

## API 與排程

- `POST /api/people/sync`：正式Lark登入且具manager／manage_people／manage_sources可執行，無需body；只回同步狀態。前端接著刷新workspace取得最新users。
- `workspace.people_directory_status`：status、last_success_at、last_attempt_at、source_count、valid_people、issues、field_warnings、stats、來源app/base/table及簡短message。status可為ready／review_required／error，錯誤保留最後成功欄位。
- 一次成功手動同步建立people_directory_connection；`scripts/run_worker.py`每輪檢查，最多每五分鐘同步一次。沒有首次核實連線的工作區不擅自啟動同步。
- 背景設定沿用 LARK_APP_ID、LARK_APP_SECRET、LARK_WORKER_IDENTITY=application、LARK_WORKER_ORGANIZATION、LARK_ALLOWED_TENANTS。讀取權限与HR Base资源角色須另經實測，不將OAuth token成功當成可讀名冊。

## 標註

`comment_add.payload.mentions` 是人員ID陣列，最多50人，伺服器去重並驗證每位是目前active且已存在的人員；同名文字不能代替ID。評論保存mentions，姓名更動仍由同一ID關聯；停用後保留舊評論，但不能新增標註。

此次沒有建立任何Lark私訊或群訊工作；只在工作台內保存標註。前端應顯示姓名及部門，並用ID作選擇值。

重新指派 task_add/task_update 與 participants_update 的負責人、協作人也由伺服器拒絕 inactive 人員；既有已完成任務的歷史owner不改。project_roles原有active_user檢查保留。

每次公開工作區回應導出 `task.can_execute` 與 `workspace.task_capabilities_checked_at`，沿用同一 `is_owner` 判斷目前負責人或有效代理，含請假狀態、五分鐘freshness、實際起訖、資格與任務範圍。PM／manager不自動有執行權。計算先於請假資料隱私投影，且不寫回DB、不採信前端旗標。can_execute只是身分權限；前置成果、狀態與必填資料仍按原規則檢查。

## 驗證與尚待完成

`test_people_directory.py`涵蓋白名單完整分頁、身分錯誤隔離、同名、人員更名／離職、停權／權限保留、空表、partial、錯誤來源／應用／公司、途中撤權、五分鐘節流及標註不產生外部消息。測試為in-memory與fake資料；不是外部端到端驗收。

本輪人員專項 **35 passed in 3.03s**，含真實四欄 schema、嚴格布林狀態、欄型別漂移、歧義拒絕、來源類別與人工部門保留。主線在此前守衛版本完整測試 291 passed；此次映射改版後完整專案驗收由主線執行。

主線已保存僅此表四個必要欄位的資源唯讀角色，其他表與薪資欄位不可讀。最新 schema 證據 `.runtime/people-schema-probe-20260927.json`。`scripts/verify_people_directory.py` 在 2026-09-27T13:30:56Z 使用同一應用實際讀取白名單欄位，聚合證據 `.runtime/people-directory-verification-20260927.json`：69 列、63 有效帳號、6 缺帳號、61 在職、2 離職、0 未知；重複合併 ID 穩定，原停權與權限保留，新增者無管理或能力權限。未輸出姓名／帳號 ID，未讀正式 DB、未寫遠端；本機合併通過不能當作正式同步已執行。
