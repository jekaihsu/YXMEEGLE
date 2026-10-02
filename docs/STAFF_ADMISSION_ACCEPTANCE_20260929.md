# 公司同事登入與動態名冊驗收

## 已知證據與限制

2026-09-29 的紀錄確認 Lark 0.4.3 已發布全員可用；jekai 已完成真實 OAuth 並以獨立公司管理員進入 normal。這不等於每位同事已實際登入。

`ATTENDANCE_READONLY_ACCEPTANCE_20260929.md` 的最新人員核對數為 **64 個儲存的 profile、58 個同 app／active／已核實在職的合格 profile**。其餘為 3 個 app 身分未核實或不符、2 個 inactive、1 個未核實在職。58/58 的 Contact 精確 ID 查核已成功，但不是 58 位同事的 OAuth 登入驗收，也不代表目前仍有 58 位可入站；現況必須以新鮮名冊重新計算。

本次僅檢閱本機程式、既有紀錄並執行合成測試。沒有操作瀏覽器、雲端、實際同事 session 或薪資 Base；沒有修改 app.py、production_access.py 或部署設定。

## 本機驗證結果

新增 `backend/test_staff_oauth_acceptance.py`，用合成 OAuth 供應者及隔離 SQLite 走真正 HTTP callback、session、workspace 路由，未偽造 production cookie。驗證一般 member 進正式工作區、不可同步名冊或自行升級 manager；既有 session 在停用、離職、未知在職、來源缺漏、app 不符與超過 15 分鐘後立即失效；重新 OAuth 不會復活停用或錯誤 app 身分。

`python -B -m pytest backend/test_staff_oauth_acceptance.py backend/test_production_access.py backend/test_people_directory.py backend/test_company_admin_admission.py -q`

結果：**77 passed in 15.25s**。其中新增 12 項。900 秒允許／901 秒拒絕的精確邊界由既有固定時鐘測試覆蓋。

程式審閱確認：名冊只要求姓名、人員、在職、內外勤四欄；依同 app open_id 合併；完整分頁與重複 ID 檢查失敗時不覆盖舊名冊。新名冊人員預設 member 且無 capabilities；同步不恢復停用權限。背景連線每五分鐘嘗試唯讀同步，成功時間超過 15 分鐘後普通同事停止進入業務路由。manager 及 capability 的明確既有授權仍有效，不能由名冊文字推導職權。

## 正常公司介面／API 的唯讀驗收步驟

1. 由已驗證的 jekai 使用正常 Lark OAuth 登入，切到公司正式工作區；GET `/api/session` 應為 mode=lark、access_mode=normal。GET `/api/workspace` 應為 200、environment=production。不要使用 test 工作區的覆蓋 profile 計數。
2. 開啟「Lark 動態人員名冊」，或讀取 GET `/api/workspace` 的 `people_directory_status`、`people_directory_connection` 與 `users`。記錄 last_success_at、last_attempt_at、status、source_count、valid_people、issues 數、missing_retained、connection.enabled，以及距 last_success_at 的秒數。不要把 valid_people 或 users.length 直接稱為在職可登入人數。
3. 以同一份回應計算普通名冊資格：active 不為 false、directory_status=employed、directory_missing 不為 true、identity_app_id 無值或等於本 app、directory_source.app_id 等於本 app、有 record_id，而且 directory_last_seen_at 距現在 0–900 秒。將「停用／非在職／來源缺漏／app 不符／過期」分項列數；獨立管理員例外另外列明。不要列出原始 open_id、姓名或薪資資訊。
4. 間隔至少五分鐘再透過正常介面重新整理或 GET `/api/workspace`；確認 last_success_at 與 sync_revision 前進。未前進時，以 GET `/api/admin/runtime-health` 查看 worker 狀態並追查名冊 status.message。單次新鮮讀取不能證明持續背景更新。若需手動恢復，正常「同步 Lark 人員名冊」按鈕會 POST `/api/people/sync`，這是唯讀 Lark、寫入本地同步快照的操作，不屬於純 GET 驗收。
5. 由一位實際普通同事本人在自己的瀏覽器透過已發布 Lark App 登入。確認 session 的本人、member（或已明確核定職權）、normal、正式 workspace，以及 GET `/api/workspace` 200。同事應看得到允許的業務頁，不能以 member 身分操作人員管理。不要借用 jekai cookie、改 uid、建立代登入 session 或代替同事 OAuth。
6. 紀錄只保留時間、部署／app 版本、回應碼、角色與彙總數。新進同事需等權威名冊具備唯一人員帳號並成功同步；復職但先前已停用的 profile 不會自動啟用，須走明確人員授權流程。不要為驗收而將實際同事改成離職、停用或管理員；這些負向情境已由本機隔離測試驗證。

## 仍待實機證明

### 已新增的正式唯讀背景觀測

root 透過正常 jekai 公司工作區 GET：2026-09-29 19:10:05（台灣）名冊 sync_revision=215、last_success_at=19:04:35；19:54:51 再查 sync_revision=223、last_success_at=19:53:41，背景連線 enabled=true。相隔 2686 秒，期間未手動要求 people sync，成功時間與版本皆前進。

後一次精確計數：64 profiles；58 位精確同 app／在職來源／active／15分鐘內 fresh；3 位在職來源但 identity_app_id 缺失或不同；2 位 inactive；0 位 fresh 門檻外的在職來源人員。獨立管理員例外不算一般名冊班表資格。這證明這段觀測區間背景名冊持續更新，仍不等同全部同事本人 OAuth 或完整24小時穩定觀測。

未發現一般 member 入站流程的可重現程式阻斷。仍須以上述 GET 驗證當下名冊 freshness、背景同步連續性及實際合格數，並由真正普通同事完成一次 OAuth；在這之前只能宣稱「已發布全員可用，符合新鮮名冊的普通同事具備入站路徑」，不能宣稱全員登入驗收完成。

## 後續實機發現：班表同步的混合身分阻斷

主執行者以正常 POST `/api/attendance/sync` 查詢 2026-09-28 至 2026-10-04 時收到 403「班表身分需同一應用已核實帳號」。這是班表讀取流程的選人錯誤，不是普通同事 OAuth 入站錯誤：service 使用較寬的 admitted()，把缺少 identity_app_id 的舊 profile 及 bootstrap 管理員也傳給要求精確 app 的 Contact resolver；先前只挑 58 位合格者的唯讀 runner 未觸及此混合情境。

本機修正 `attendance_service.py`：Contact 查核只傳入同 app、明確在職、來源存在、未缺漏、active 且具 open_id 的人員。其餘已入站但未符合班表資格的人員列入 pending issue，已核實同事仍可繼續查詢。獨立公司管理員身分只授權操作；沒有名冊在職證據時，即使有旧 attendance mapping 也不查詢該管理員班表。resolver 的嚴格核對與拒絕異常回應維持不變。

新增 58 位精確合格者＋2 位缺 app 身分＋1 位 bootstrap-only 管理員的整體 service regression，驗證 Contact 50/8、班表 50/8；3 位未核實者的 21 個 person-days 維持 pending，第二次快取同步仍可正常執行。35 項 identity/service/schedule 測試通過（5.28 秒）。這是本機證據；修復部署及正常 API 再驗收由主執行者負責。

正常 GET 彙總函式：`.runtime/staff-roster-exact-summary.js`；僅回傳數量、時間、狀態，不回傳原始 IDs 或姓名。使用 exact_roster_verified 作為班表候選彙總，fresh_exact_roster_verified 另外表示當下 15 分鐘新鮮度。

## 後續防線：歷史班表不代表當下可用的截止時間

第二批修正處理另一个獨立問題：離職或名冊失效者的既有 ready 班表會保留歷史，但原 cutoff 仍可能把它當有效截止時間，使 recurring 將 PM／主管列入逾期通知。

現在正式環境的 `learning.cutoff` 會重新核對當下同 app、active、明確在職、有來源紀錄、未缺漏，以及 15 分鐘內名冊 freshness。失效時回傳 pending_schedule／employee_identity_unverified；`jobs.schedule` 跳過該 routine 的通知與升級。只變更當下使用判定，不刪除或覆寫歷史班表日期、ready 欄位、版本與歷史。demo/test 不要求 Lark 名冊，既有人工班表操作保留。

`backend/test_schedule_subject_gate.py` 覆蓋停用、離職、來源缺漏、app 缺失或不符、名冊過期，確認舊 ready 班表不能產生 PM／主管升級通知，且班表內容完全保留；另驗證 demo/test 無 Lark 的人工 cutoff。相關 attendance/workflow/operations/learning 測試合計 **136 passed in 31.90s**。此項為第二批本機修正，部署與實機狀態須另外記錄，不能與第一批班表 403 修復混稱完成。
