# Code Review 彙整（Claude，2026-09-27）— 給 Codex 修正用

> 產出方式：第一輪 6 路唯讀審查（業務規則、存檔與並行、權限與外洩、來源匯入、前端、整體 code review）合併去重，主審抽查；第二輪 4 路（懷疑派抗辯、攻擊派維運、精簡派、Codex 變更審查）挑戰並補充。抗辯後 P0 由 5 項調整為 2 項（#1、#4、#5 降為 P1），各項修法已依抗辯更正。測試稽核（變異測試）完成後另補。審查期間 Codex 仍在修改，**行號可能偏移，一律以「檔案＋函式名」定位**。
> 驗證狀態：**已實測**＝審查員在 %TEMP% 副本寫最小重現跑過；**讀碼**＝讀程式推論，修之前請先寫一個會失敗的測試確認。
> 修正原則：每修一項先補一個「修前失敗、修後通過」的測試；不要順手做清單外的改動。

## 第二輪：外部操作的技術風險（業主已確認 U1–U3 為其授權）

2026-09-27 業主說明：Codex 今天在 Lark 後台的操作（薪水 Base 應用授權與人員唯讀角色、審批唯讀權限、發布應用版本、準備建立審批定義）**基本都是業主授權的**。以下不再視為違規，只列仍需處理的技術風險。

| # | 事項 | 證據（`.runtime/`） | 仍需處理 |
|---|---|---|---|
| U1 | 薪水計算 Base `VwAsb…`：應用加入（可閱讀）、新角色「專案工作台人員唯讀」（只開「人員名單及資料」四欄）、成員為群組「專案工作台來源唯讀授權」；已讀 69 筆人員資料（業主授權） | `prepare-people-app-access.js`、`create-people-role.js`、`limit-people-role.js`、`people-role-member.js`、`save-people-role.js`、`people-directory-verification-20260927.json` | **驗證**：以應用身分實際試讀該 Base 的其他表（例如薪資相關表）必須被拒；若應用不在該角色群組內，可能落到預設「可閱讀」而讀得到全部表。留下讀取被拒的回執 |
| U2 | 開通 `approval:approval:readonly`、發布新應用版本（業主授權） | `approval-permission-*.js`、`app-version-published.yml` | 無，留檔即可 |
| U3 | 準備建立審批定義／送出審批實例（業主授權） | `approval-official-*.md` | 第一次端對端測試請用**測試專用的審批定義**與測試人員，勿直接發給真實員工；接線前先修 #46（測試白名單、送出後查結果、撤銷路徑） |
| U4 | `.runtime/release-settings-request.json` 已備妥未送出：只送 3 個環境變數。若 Zeabur `updateEnvironmentVariable` 是整組覆蓋（`deploy_prepare.prepare_lark` 送前會複製完整 env，顯示作者也這樣認為），資料庫、SESSION_SECRET、Lark secret 會被清空，服務反覆崩潰 | `scripts/prepare_release_settings.py` `main` | 送出前改為「完整 env＋delta」，並明確設 `DEMO_MODE=false`、`ALLOW_CLOUD_DEMO=false`；先確認 Zeabur 語意（讀碼判斷，未實測） |
| U5 | 正式資料副本：本機 4 份 `legacy-cloud-backup-*`（各含 workspace.zip、約 8.5MB restore.sqlite、附件），另有 `source-private-cache`、`review-*.db`；正式容器 `/tmp/yx-legacy-snapshot-*.zip` 未清；`.runtime` 至少 6 個明文憑證檔、共 145MB、87 支一次性腳本，皆無加密、無期限（已確認不會進 git 與 image） | `run_legacy_cloud_backup.py` 等 | 業主決定保留幾份；清容器 `/tmp`；憑證用完即刪 |

## 業主裁示（2026-09-27）

| # | 事項 | 位置 | 裁示與要求 |
|---|---|---|---|
| D1 | **能力地圖不回寫**（業主裁示：不應該回寫） | `jobs.py` 的 `capability` job（`adapter.write_input` 寫「人員名單及資料」的「能力地圖點數」）、`learning.py` `apply_learning`（`queue(ws,'capability',…)` 兩處，約 102、128 行；約 79 行的 target 'capability' 分支）、`jobs.py` `reflect_job_status`/`authorize` 的 capability 分支、`learning_sources.py` `CAPABILITY_BASE`、前端能力認定後的寫回狀態顯示 | 移除能力認定後寫回薪水計算 Base 的整條路徑（不是只加旗標）：不再建立 `capability` job、worker 遇到舊的 capability job 標為 blocked 並註明「業主裁示不回寫」。能力認定結果只存在工作台。原因：「能力地圖金額」是加總技能金額的公式，寫回會間接改動薪水相關數字。補測試：核准能力認定後不產生任何遠端寫入 job |
| D2 | **訓練紀錄停用**（業主裁示） | `lark_adapter.py` `write_training`/`verify_training_mapping`、`integration_routes.py` `verify_learning_mapping`、`jobs.py` 的 `training_record` job、`frontend/src/Learning.tsx` `verifyMapping`（寫死 token） | 停用訓練紀錄寫回；既有 training_record job 標 blocked「業主裁示停用」 |
| D3 | **範圍裁示：暫時只要「管理」功能**，訓練／能力／考評整塊先關閉 | `learning.py` `apply_learning`：關閉 `training_save`、`training_return`、`training_submit`、`training_pass`、`learning_retry`、`learning_standard_set`；`app.py` `/api/learning/sync`、`integration_routes.py` `/api/learning/mappings/verify` 回 404；前端 NAV 隱藏學習頁 | ⚠ **`learning.py` 裡有兩個管理功能不可一起關**：`schedule_set`（班表，`cutoff()` 被 `jobs.schedule` 用來算截止時間）與 `quote_review`（接案報價認定）——先搬到 `operations.py`，再關學習模組。建議用單一設定旗標（例 `FEATURE_LEARNING=false`）在分派入口、路由、worker、前端導覽四處一起擋，之後要開回來只改旗標。補測試：旗標關閉時上述 action 回 404/400，`schedule_set`、`quote_review` 仍正常 |

## P0 — 違反核定規則、權限可被繞過、資料會被蓋掉

| # | 問題 | 位置 | 失敗情境 | 修法 | 驗證 |
|---|---|---|---|---|---|
| 2 | **同一人可坐兩席自批** | `operations.py` `seats()`、`submit_review`、`vote` | A：節點 owner＝組主管，自己投 owner＋supervisor 兩票即完成。B：主管用 `delegation_set` 把 supervisor 席代理給節點 owner，一人投兩席。違反決策 11、30（目前只有財務節點有擋） | `submit_review` 要求所有雙席節點的席位為不同人；`vote` 禁止同一實際操作者（含代理）投第二席。**不要**在 `delegation_set` 擋（代理是按案件×席位設定，擋在那裡太寬），投票時檢查即可。**必須同時改 `app.py` `copy_pilot`**：它刻意把每個節點設成 owner＝supervisor＝管理員，只改規則的話試行案技術節點會全部無法送審；也代表試行驗收從來沒測到雙人規則 | 已實測（A、B；抗辯方獨立重現） |
| 3 | **繞過鎖與版本檢查的寫入會蓋掉別人剛存的資料** | `app.py` `switch_workspace`、`copy_pilot`（`lark_callback` 在 SQLite 下同樣） | 這些路徑 `db.get` 讀、不上鎖、不比版本，整份 `storage.save`（會刪掉手上舊 state 沒有的列）再直接設 `row.version`。實測：A 讀 → B 正常新增留言 → A 寫回 → 留言消失，版本號也對不上。若蓋掉的是 worker 的遠端回執，下次重試會**重複對外發送** | 三處全部改走 `persist_mutation`（`with_for_update`＋`version==expected` 條件 update）。更根本：把 8 份「讀整份→改→版本+1→存」樣板合併成一個 `storage.commit(db,row,state,expected)`，這類漏網之魚就不會再出現 | 已實測（三位審查員獨立重現） |

## P1 — 明確錯誤或嚴重影響可用性

| # | 問題 | 位置 | 失敗情境 | 修法 | 驗證 |
|---|---|---|---|---|---|
| 1 | **結算可在計價等前段節點仍 pending 時完成**（抗辯後由 P0 降級、改標題） | `operations.py` `missing()` 的 settlement 分支、`refresh_project_state` | 技術四節點完成、財務基準核定、`payment_reconcile`、結算兩席投票後 → completed，但 sales/pm/confirmation/pricing 仍 pending。**錢沒有被跳過**（`payment_reconcile` 要求應收＝合約、全數已付、收據經兩人核對），被跳過的是這些節點的證據與簽核 | 結算前要求 pricing、sales、pm、confirmation「已完成或已核准不適用」；退回 rework 時撤回結算完成。**須等 #6 修完再上**，否則每次展延都會撤回結算 | 已實測（抗辯方獨立重現） |
| 4 | **測試工作區的人員異動會直接改到正式區**（抗辯後降為 P1＋待業主確認設計） | `app.py` `persist_mutation` 回寫 `PersonRow`（以 `wid.removeprefix('test-')` 共用）、`load` | 管理員在 test 區對 member 執行 `admin_person` 設 manager → 該人在正式區也是 manager。人員資料依設計是全公司共用一份，但規格也說測試區「隔離」，兩者衝突。另：PersonRow 回寫沒有列鎖，並行時後寫者勝（可把停權蓋回 active） | **先請業主決定**：人員權限是否全公司一份？若是，test 區的人員管理畫面要明示「會影響正式區」；若否，test 區禁止 `admin_person`。**不要**改成「只寫工作區本身」——`load()` 會用 PersonRow 把異動蓋回去。PersonRow 更新加 `with_for_update` 且只寫有變動者 | 已實測 |
| 5 | **持 manage_people 的非管理員可把管理員降級並停權**（抗辯後由 P0 降級） | `operations.py` `apply_operation` 的 `admin_person` 分支 | member 送 `{id:管理員, role:'member', capabilities:[], active:false}` → 200（只要不是最後一位管理員）。「缺 active 讓離職者復職」只有直接呼叫 API 才會發生，UI 會帶現值 | **只在**目標是 manager、或要升成 manager 時要求操作者是 manager（不要擴大到所有 active 變更，否則行政無法停權離職者）；`active` 缺省沿用現值；未帶欄位時不要清空部門、不要重設 default_workspace | 已實測 |
| 6 | **執行任何展延/變更，全案已完成節點被打回 rework** | `workflow.py` `apply_action` 的 `approval_execute`（`p['revision']+=1`）、`operations.py` `review_hash`（含 project revision）、`app.py` `/api/actions` 的 `mutate`（hash 變就 `invalidate`） | 只展延計價的一個任務並執行 → 報價到報告 7 個已完成節點全部變 rework、已核准審核輪次全失效。與「展延不凍結工作」相反 | `review_hash` 移除 project revision，改用節點內任務自身 revision/狀態；展延只改期限不觸發 invalidate | 已實測。**抗辯註**：正式區目前走不到（`approval_submit` 固定 503、`approval_lark`/`approval_confirm` 限 demo），只影響 demo/test；但 `native_approval.py` 接線後就會影響正式區，須在接線前修 |
| 7 | **讀取端資料外洩** | `workspace_projection.py` `filter_private_workspace`（只過濾 `approved_leave_delegations`）、`app.py` `get_session`、`sources` | 一般 member 從 `/api/workspace` 可拿到：他人 `capability_bindings`（來自薪水 Base）、`work_schedules`、`delegations`（source=approval 者含請假起訖日與實例編號，等於繞過既有過濾）、`jobs[].payload.snapshot`（訓練成果全文）、`input_mappings[].base_token`、`events` 中 admin_person 的完整人員前後 JSON、全員 `directory_status`。`/api/session` 的 users 完全未過濾。`/api/sources` 不查角色就回整份原始快取（含日報逐人姓名、營業額點數等） | 改**白名單投影**：非 manager/非相關權限者只回自己的能力/班表/訓練；jobs 只回 id/status/error；遮蔽 base_token、events 人員快照、代理日期與實例號；users 只留顯示欄位；`/api/sources` 要求 pm/manager/manage_sources，或只回 tables 摘要。**抗辯註**：規格明訂「公司有效內部人員可讀財務」，日報的營業額/點數是否算個人績效資料需業主定義，未定義前不列為外洩 | 已實測 |
| 8 | **暫存接案展開完整 SOP（業主已裁示：只產接案階段）** | `v4_sources.py` `nodes`、`new_project`、`import_v4` intake 分支；`jobs.py` `schedule` | 每筆無確認單報價產生 9 節點 23 任務（264 筆佔全部任務 92%）；`schedule` 也沒排除 intake，會開出每日/預排/月考評週期工作 | `nodes()` 加 `case_type`，intake 只產 sales 節點；轉正式案時補齊缺的節點並保留歷史；`schedule` 跳過 `case_type=='intake'`。**必須同時修 #9** | 已實測 |
| 9 | `schedule` 遇無外業節點的案件拋 StopIteration，整個工作區排程中斷 | `jobs.py` `schedule`：`next(n['owner_id'] for n in p['nodes'] if n['key']=='field')` | 目前案件都有 9 節點碰不到；修完 #8 後 intake 只剩 sales 且有 pm_id 即觸發 | `next((...), '')`，並配合 #8 排除 intake | 已實測（刪掉 field 節點） |
| 10 | **背景程式頻繁改版本號 → 使用者一直 409** | `source_sync.py` `run_due`/`sync`/`failure`、`people_directory.py` `run_due`/`_save`、`jobs.py` `refresh_delegations`、登入、切換工作區 | 開過一次手動同步後，每 5 分鐘預約時段 bump 一次、結果再 bump 一次，名冊同步同理，合計約每 75 秒一次。估算填 60 秒的表單約 55% 要重做。（`schedule()` 無變化時不 commit，已實測） | 來源/名冊狀態、last_attempt、job 租約等背景 metadata 移到獨立表，不動工作區 version；長期是否要按案件切版本號見下方「架構結論更正」 | 讀碼＋估算（「約一半要重做」假設 409 後表單內容會遺失，未驗證） |
| 11 | **效能：每個請求整份讀寫、多次深拷貝** | `app.py` `identity`/`get_session`/`workspace`、`storage.load`/`save`、`migration_archive` 存在根 JSON | 真實資料（279 案/6,302 任務）comment_add 中位 8.4 秒、回傳 8.5MB；一次頁面 refresh 做 4 次完整載入 | 已實測可得：`identity` 只查 users/PersonRow（1.2s→0.003s）；`load` 拿掉兩次 deepcopy 且不讀 migration_archive（1.83s→0.50s，內容逐項比對相同）；`save` 每筆改淺拷貝（2.52s→0.77s）；migration_archive、archived_projects 移到獨立表；`/api/actions` 的 `review_hash`（每次約 5,040 次）與 `refresh_project_state` 只算 `project_id` 那一案。預估 comment_add 降到約 2 秒 | 已實測（分項）；整體為推估 |
| 12 | **事件插在最前面 → 每次寫入改寫全部事件列，且永不清理，越用越慢** | `workflow.py` `event()`（`ws['events'].insert(0, …)`）、`approvals.insert(0)`；`storage.save` 依 ordinal 比對 | 每新增一筆事件，既有所有 event 列 ordinal 位移並被 UPDATE。背景同步每 5 分鐘新增事件，一個月上萬筆 | 改 append、以 created_at/遞增 ordinal 排序、讀取時反轉；設保留上限或封存 | 讀碼（主審已確認 insert(0) 與 ordinal 比對） |
| 13 | **舊快照覆蓋新資料** | `source_sync.py` `sync` | 排程同步 T0 開始 fetch，PM 在 T1 手動同步先完成；排程 T2 帶著 T0 的舊快照上鎖套用，狀態與日報配對倒退、last_sync 倒退，無警告（名冊同步有 sync_revision，這裡沒有） | fetch 前記下 generation/last_sync，套用前若已有更新者就拒絕；或手動同步也先寫入預約 | 讀碼 |
| 14 | 報價有原生連結但工程編號打錯 → 被拆成待確認案 | `v4_sources.py` `import_v4` 候選收集 | 打錯的編號也被當成候選，湊成 2 個 → 報價脫離正式案，另建待確認案（原因 multiple_confirmations） | 有原生連結時，工程編號只用來比對、不加入候選；不一致標衝突 | 已實測 |
| 15 | 來源已刪除的日報/確認單，本地仍保留且案件仍正式 | `v4_sources.py` `import_v4`（日報迴圈、案件分組迴圈） | 來源刪掉日報或清空確認單編號後，本地日報仍在、案件仍「執行中」 | 完整快照中不存在的來源 ID 標「來源已移除」並停止計入 | 已實測 |
| 16 | 遠端已送出，job 卻被標 blocked → 之後重送 | `jobs.py` `Worker.run_one` 的 except、`checkpoint` | finish checkpoint 遇版本衝突拋 409，被歸為非遠端錯誤 → blocked；訊息其實已送出，重新排隊就重送（SQLite 忽略 FOR UPDATE 時較易發生） | 遠端副作用完成後 checkpoint 失敗一律標 `outcome_unknown` | 讀碼 |
| 17 | 備份可能沒有附件卻顯示成功 | `scripts/backup_restore.py`（預設 `./data/uploads`）vs `app.py`（預設 `./backend/uploads`）、`backup_schedule.py` | 未設 UPLOAD_DIR 時備份找不到目錄 → files=[] 仍成功；還原後所有本地附件消失。Dockerfile 只 mkdir 沒宣告 VOLUME | 兩邊共用同一預設；DB 有 local 附件參照但目錄/檔案缺漏時備份直接失敗 | 讀碼 |
| 18 | 前端：上傳等操作遇 409 不重新整理 | `App.tsx` `upload`；`Learning.tsx` `sync`/`verifyMapping`；`Operations.tsx` `invoke`；`ApprovalDetail.refreshRemote` | 409 後只 setError，`w.version` 停在舊值；手機重選檔案每次都 409 且整檔重傳，直到手動重整 | 抽共用 `mutate()`，409 一律 `await refresh()`（與 `run` 一致） | 讀碼 |
| 19 | 前端：彈窗內看不到錯誤 | `TaskInspector`、`ApprovalForm`、`AddTaskModal`、`ParticipantsModal`、`CalendarModal`、`ApprovalDetail` | 錯誤只進主畫面 banner（非 sticky，modal 開啟時 body 被鎖捲動），送出失敗只見按鈕轉圈結束 | Modal 內統一顯示 `c.error`（role="alert"），或 banner 改 fixed＋z-index>60 | 讀碼 |
| 20 | **XSS**：班表來源連結 | `Operations.tsx` `WorkSchedules`（`href={s.source_url}`）＋`learning.py` `schedule_set` 未驗證 URL | 有 calendar_edit 權限者可存 `javascript:` 連結，他人點擊即執行 | 後端對 `source_url` 呼叫 `http_url`；前端 `safeUrl` 移到共用檔，所有外部連結一律使用（另見 `Learning.tsx`、`Deadlines.tsx`、`Operations.tsx` 其他 href） | 讀碼（前後端交叉確認） |

## P2 — 風險、加固、長期效能

| # | 問題 | 位置 | 修法 |
|---|---|---|---|
| 21 | 同種資料 id 重複時存檔默默吃掉一筆（已實測；現有資料 0 重複） | `storage.py` `save`（`desired` dict 覆蓋） | 存檔前檢查重複，有就拒絕寫入 |
| 22 | 多副本同時啟動一起跑 migration → IntegrityError | `app.py` `create_app` migration 迴圈 | PostgreSQL advisory lock |
| 23 | 大小寫/全形編號被建成兩案（已實測） | `sources.py` `normalized_case` | NFKC＋轉大寫＋去內部空白（不截斷，符合決策 7） |
| 24 | 日報別名表只收正式案，永遠配不到待確認案（快取重播：部署版 1 筆 → 現在 0/535，退步） | `v4_sources.py` `import_v4` | 命中待確認案時列為**候選**，不直接歸案 |
| 25 | 類型不符的來源表被靜默丟掉，少一整類表仍被當完整快照 | `sources.py` `configuration`、`source_sync.py` `sync` | 必要類型沒到齊就拒絕同步 |
| 26 | 非公式日期欄回傳序號被解成 1970-01-01（已實測） | `sources.py` `day` | 小於 1e9 的數字視為無效 |
| 27 | 寫回無條件式寫入；訓練紀錄重試可能重建；上傳結果不明時重傳無 hash 去重 | `lark_adapter.py` `write_input`、`write_training`、`upload` | PUT 後讀回若既非本地值也非原值即標衝突；上傳依 sha256 去重 |
| 28 | 禁寫名單缺 **v3 日報正式 Base `Sdw1bG1djaHsVGsRPvmjyVWipgg`**，誤設時可能被當測試目的寫入 | `remote_policy.py` `FORMAL_BASES` | 加入 v3 PROD 與其他業主列管 Base |
| 29 | 成本分攤建立者可自己核准；`parts` 型別錯誤回 500；金額存 float | `operations.py` `finance_allocate`、`finance_allocation_approve`、`finance_approve` | 核准人≠建立者；逐筆驗證型別；金額存 Decimal 字串 |
| 30 | 名冊同步：actor 失權後每 5 分鐘靜默失敗、狀態永遠顯示 ready；舊同步 409 會把新成功狀態蓋成 error | `people_directory.py` `run_due`、`sync`、`failure` | actor/環境檢查移進 try，失效即停用連線並記錄；generation 衝突不呼叫 failure() |
| 31 | 複製試行案帶走本地附件紀錄但不複製實體檔 → 測試區下載 404、job blocked | `app.py` `copy_pilot` | 一併複製檔案，或清除/標示不可用 |
| 32 | 未登入即可無限建立資料：demo 模式每個無 cookie 的 `/api/session` 建一個含種子資料的工作區；`/api/auth/lark/login` 每次新增 nonce；皆無清理，worker 每輪要掃全部工作區 | `app.py` `get_session`、`lark_login`；`scripts/run_worker.py` | demo 工作區延到首次寫入才建＋限流＋TTL 清理；定期刪過期 AuthRow/nonce；AuthRow 加 organization/uid 欄位改條件查詢 |
| 33 | demo cookie 未強制 wid 以 `demo-` 開頭；非 production 預設密鑰寫死 → 可偽造 cookie 讀正式資料（僅限非 production 部署） | `app.py` `identity`、`create_app` | demo 模式強制 wid 前綴；無 SESSION_SECRET 時隨機產生 |
| 34 | Lark access_token 明文存 DB；背景同步借用最後觸發者的 token | `app.py` AuthRow、`source_sync.py` `run_due` | token 加密；背景同步改用 application 身分 |
| 35 | 來源同步比對日報為平方複雜度且在鎖內執行。**主審更正**：審查員估「約 2 萬筆日報」有誤，實際快取日報 535 筆，目前約數十萬次運算、非數分鐘；但會隨歷史累積成長 | `v4_sources.py` `import_v4`（每筆日報掃全部案件重建清單）、reporting 掃全部 task | 先用 set 收集本次 daily id 一次過濾；建 task_id 索引；在鎖外計算、鎖內合併 |
| 36 | worker 每 30 秒對每個工作區上鎖並完整載入 3 次（來源、名冊、worker），即使沒有到期工作 | `source_sync.py` `run_due`、`people_directory.py` `run_due`、`jobs.py` `run_one` | 排程 metadata 不上鎖先讀，到期才鎖＋載入；recurring 建 (project_id, kind) 索引 |
| 37 | 前端：`refresh` 與 `run` 競態可用舊版本覆蓋畫面 | `App.tsx` `refresh`/`run` | `setW(prev => !prev || next.version >= prev.version ? next : prev)` |
| 38 | 前端：點背景即關閉 modal，手機誤觸會丟失已填內容 | `App.tsx` `Modal` | 有輸入時先確認，或手機停用點背景關閉 |
| 39 | 前端：`MentionComposer` 攔截「@」導致 iOS/實體鍵盤打不出 @ | `MentionComposer.tsx` `onKeyDown` | 改在 `onInput` 偵測並保留原字元 |
| 40 | 前端：型別與後端不符（`Project.due_date` 等可為 null；`TrainingPlan.status` 缺 `returned`） | `types.ts` | 修正型別 |
| 41 | 前端效能：每次操作解析整份工作區、`allTasks` 每次 render 重算、`nameOf` 線性 find、`c` 無 memo、MyWork「全部」不分頁 | `App.tsx` `App`/`Dashboard`/`MyWork`/`TaskTable` | context＋useMemo；users 建 Map；TaskTable 分頁；長期改回傳單案差異 |
| 42 | 可維護性：App.tsx 單行上千字元，兩個 AI 同時改會在同一行衝突、diff 無法審查 | `frontend/src/App.tsx`、`Operations.tsx` | 加 Prettier；拆 `useWorkspace.ts`、`project/`、`task/`、`approvals/`、`project/panels/` 等（詳見前端審查建議） |

## 第二輪補充（懷疑派、攻擊派、精簡派、Codex 變更審查）

| # | 嚴重度 | 問題 | 位置 | 修法 | 驗證 |
|---|---|---|---|---|---|
| 43 | P1 | 備份寫到一半失敗會留下壞檔並佔住當日/當月檔名，當天不重試、月備份直接複製壞檔；loop 模式下排程程式直接結束 | `scripts/backup_restore.py` `backup`（`ZipFile(target,'x')` 失敗不刪）、`backup_schedule.py` `tick`、`__main__` | 先寫 .tmp、驗 checksum 後 `os.replace`；失敗刪除；`tick` 捕捉例外並告警；月備份只從已驗證的 daily 產生 | 已實測（兩檔還原皆 KeyError manifest.json） |
| 44 | P1 | RPO 24h 做不到：備份目錄不檢查是否持久、與正式資料同一故障範圍、無異地副本；`run_service` 不啟動備份排程 | `run_service.main`、`deploy_prepare.prepare_settings`、`backup_schedule.tick` | 獨立 volume 的 cron 服務＋異地複本；啟動時確認備份目錄在已掛載 volume | 讀碼 |
| 45 | P1 | worker 出錯或卡住無人知道：例外只印型別名；health 只檢查 web；讀 DB 那行不在 try，DB 短斷線即讓 worker 結束並拖整個服務重啟 | `scripts/run_worker.py` `main`、`app.py` `health` | log 記 traceback（去機密）；worker 心跳寫 DB 並納入 health；最外層迴圈包 try；連續失敗告警 | 讀碼 |
| 46 | P1 | `native_approval.py`（未接線）：只接受正式工作區、無測試用審批定義白名單，一接線第一次測試就發給真實員工；`poll` 要求案件版本不變，送出後案件一改就永遠查不回結果、無撤銷，員工 Lark 留孤兒審批 | `backend/native_approval.py` | 設測試 approval_code 白名單；查結果時比對送審當下凍結的版本；過期改「已作廢」並撤銷 | 讀碼＋官方文件 |
| 47 | P1 | `node_skip` 的主管席次可由 PM 指定：席次＝`n.supervisor_id or p.supervisor_id`，而 `project_roles` 允許 PM 把主管改成任何在職同事，決策 14「該組主管確認」被架空（與 #2 同源） | `backend/node_skip.py`、`operations.py` `project_roles` | 主管席次從組別/名冊推導；改主管限 manager | 讀碼 |
| 48 | P1 | 同一案執行一筆申請後，其他已核准未執行的申請全部 409 | `workflow.py` approval_execute 比對 `project_revision` | 改比對申請影響範圍內任務的 revision | 讀碼（抗辯方） |
| 49 | P2 | `switch_workspace` 無角色檢查，任何成員都能進 test 區看到從正式區複製的試行案 | `app.py` `switch_workspace` | 限 manager 或指定測試人員 | 讀碼（抗辯方） |
| 50 | P2 | `filter_private_workspace` 每請求對全部任務（約 6,302）跑 `is_owner`；`task_capabilities_checked_at=now()` 讓每次回應都不同（測試被改成 monkeypatch 遷就） | `workspace_projection.py` | 只算請求所需的案件；時間戳移出回應或只在變更時更新 | 讀碼 |
| 51 | P2 | 前端有「尚未指派」選項，後端 `task_add`/`task_update` 帶 `owner_id=''` 一律 404 | `operations.py`/`workflow.py` task_add、task_update | 空字串視為未指派 | 已實測 |
| 52 | P2 | `.dockerignore` 的 `*.db`、`.env`、`data` 只比對根目錄，`backend/workspace.db`、`backend/uploads` 會被 `COPY backend/` 帶進 image（目前走打包白名單不受影響）；`.gitignore` 未排除 `backend/uploads/` 與根目錄內部 SOP PDF/docx | `.dockerignore`、`.gitignore` | 改 `**/*.db`、`**/*.sqlite*`、`**/.env*`、`**/uploads` | 讀碼 |
| 53 | P2 | `--forwarded-allow-ips=*`：任何連線可偽造 X-Forwarded-Proto/For，影響 origin_guard 判斷的 scheme 與記錄的 IP | `scripts/run_service.py` | 限定平台代理 IP | 讀碼 |
| 54 | P2 | 前端小項：`playful-theme.css`（17KB）未被 import；`useDraftNavigationGuard` 用 replaceState 吃掉瀏覽紀錄且 iOS 不觸發 beforeunload；`CompletionCelebration` 會把別人同時完成的節點當成自己的 | 各檔 | 刪死檔；草稿改存 sessionStorage；慶祝只比對本次操作的節點 | 讀碼 |

### 試行版範圍建議（精簡派）
- 用一個 `TRIAL_MODE` 旗標在分派入口與 worker 入口擋掉試行用不到的功能：訓練/能力認定、名冊同步、請假代理刷新、財務/付款/交付/週期工作/交接/SOP 發布、原生審批。**關掉名冊同步可同時避開 #10 的一半背景版本號變動與 #30**；關掉週期工作可避開 #8、#9。
- 注意：接案要用的 `quote_review` 目前放在 `learning.py`，關訓練前要先搬到 operations。
- 分派改成單一 `HANDLERS={action:fn}` 表，未知 action 回 400，後處理（review_hash/invalidate/refresh）統一執行。
- 權限判斷收進 `permissions.py`（注意 `is_pm` 不含 supervisor、`lead` 含，合併時保留差異，建議與 #2 一起改）。
- docs 共 36 份且互相矛盾（多份「最新狀態」、`APPROVED_SPEC_v0.6` 內文仍留舊條文、`DEPLOYMENT_RECEIPT` 寫配對 1/535 與現況 0/535 衝突）。建議只留 README、DECISIONS（由 HANDOFF 決策段抽出）、SOURCE_MAPPING、DEPLOYMENT、API_CONTRACT、本檔，其餘移 `docs/archive/` 並標「歷史資料，不得作為依據」。

### 架構結論更正（抗辯後）
- 主審先前說「根因是整個公司一份文件」——**只適用於效能與 409（#10、#11、#12、#36）**；P0/P1 的規則與權限問題（#1、#2、#5、#6、#7）是邏輯錯誤，與此無關。
- 主審先前說「跨案件程式碼只有 4 處、按案件切版本號 3～5 天」——**撤回**。實際跨案件依賴還包括 `/api/actions` 每次重算全部案件、`admin_person` 全案 refresh、`daily_approve` 跨案搬日報、`policy.upgrade`、`sop_deadlines`、`import_v4` 合併/移除案件與跨案改寫引用、10 個以上帶 project_id 的全域清單、`refresh_project_state` 依賴全域人員與代理。**改為**：先做 #11 的單點效能改善＋把背景 metadata 移出版本號（解 #10），試行規模下未必需要按案件切版本號。
- 主審先前說「程式寫出約 8 成、真實跑通約 2 成」——**撤回數字**（無分母、無量測）。質性結論不變：正式區的審批鏈、所有寫回仍未真實跑通。

## 日報 535 筆配不上：主因在來源資料，不在程式

- 535 筆的「所屬案件／合約工項／內業工項」只有 table_id、沒有 record_ids；「案件編號」公式無回傳值；外業「可能確認單工作編號」187 筆全空。**403 筆完全沒有案號線索**，任何比對規則都救不回。
- 132 筆有內業暫填工編：精確命中確認單 0、命中報價 1（待確認案）；82 筆只對得到母號（49 筆兄弟碼不同、32 筆填母號但來源只有子號），依決策 7 **不可自動合併**。
- 建議：
  1. **根治**：日報/外業表單的「所屬案件」設為必填或用 URL 參數預填（沿用業主 UI 既有表單，不另建表單）。
  2. 規則 A：暫填碼 NFKC＋大寫＋去空白＋去「(新案)」註記後再精確比對。
  3. 規則 B：母號/兄弟碼只列「候選」送人工確認。
  4. 規則 C：日報表與成本單表的「零產出歸屬案件」（連結型）欄位目前未讀入，可加為候選來源。
- 附帶：兩個 Base 各有 91 筆完全相同的空白確認單列（金額 0、名稱空白），疑為空白範本列，建議忽略並回報業主清理。

## 已確認做得對（不要改壞）

- OAuth state 綁 cookie＋一次性 nonce、租戶白名單；登出即刪 AuthRow；每次請求重讀 PersonRow 並檢查停權。
- origin_guard＋SameSite=Lax；附件依工作區雜湊分目錄、路徑限制在上傳目錄內、下載一律 octet-stream；CSV 防公式注入。
- 財務節點 PM＋行政兩方、`finance_attest`、收付款核對都有擋同一人；財務變動會撤回結算完成。
- 工作日計算（負向偏移、補班）正確；設計變更只凍結指定 work_item 及下游、展延不凍結、重複 execute 回 409。
- `/api/actions` 三段處理器 action 前綴不重疊，不會被錯的處理器吃掉。
- 案件識別：同編號多報價一案、重複同步不增案、母子案不合併、空白編號不合併、衝突不任選。
- 分頁上限觸頂會被標部分資料並以 409 拒絕，不會被當完整快照。
- worker 在多副本下有租約＋版本比對，不會重複執行；lease 時間字串比較因固定 +08:00 而正確。
- remote_policy 會阻擋 test 工作區寫到正式 Base；審批 refresh 不自動核准；最後一位管理員受保護。

## 建議修正順序

0. U4（送 Zeabur 設定前先修）、U1 驗證、U3 用測試審批定義。
1. D1 移除能力地圖回寫；D2 停用訓練紀錄；D3 以旗標關閉訓練／能力／考評模組（先搬出 schedule_set、quote_review）。
2. P0 #2、#3（#3 建議以合併 `storage.commit` 的方式修）。
3. P1 #6 → 再 #1（#1 依賴 #6）；#5、#7、#8＋#9（一起改）、#10、#11、#12；#4 等業主決定設計。
4. 維運 #43–#45、#17。
5. 其餘 P1，再 P2。
6. 每項附「修前失敗、修後通過」測試；#11 完成後以 `scripts/benchmark_workspace.py` 重量並附數字。


## 修正追蹤（截至 2026-09-28 13:30，5 路唯讀追趕審查）

> Codex 在 9/27 22:00～9/28 13:30 間改了 84 個檔且仍在改。狀態：**已修**（附驗證）／**部分修**／**未修**／**改壞**。「實測」＝審查員在 %TEMP% 副本重現；「讀碼」＝讀程式判斷。

### 總覽
- **已修（已驗證）**：#1、#2、#3、#4（測試區停權不影響正式區）、#5、#6（展延）、#9、#13、#37、#39、#43、D2、D3
- **部分修**：#7、#8、#11、#12、#15、#16、#17、#18、#19、#25、#26、#27、#29、#34、#38、#42、#44、#45、#46、#54、D1、2-a、3-c
- **未修**：#10、#14（Codex 刻意保留並有測試鎖定）、#20（XSS）、#21、#22、#23、#24、#28、#32、#33、#35、#36、#41、#47、#48、#49、1-b、1-d、1-e、0-a、0-c、0-d、2-b、2-c、2-d、3-b、3-d、3-e、4-a、4-b、4-c、4-e
- **改壞**：#40（前端型別檢查 tsc 失敗）；#11 效能回退（comment_add 由 8.4 秒變 11.5～15.3 秒，主因 B60）
- **測試**：後端 549 個，548 過、1 失敗（B63）；前端 tsc 1 個錯誤（E75）
- **日報配對**：仍 0/535（403 筆無任何參照、132 筆暫填碼配不上）

### 逐項明細
| 編號 | 狀態 | 驗證／說明 |
|---|---|---|
| #1 | 已修 | 實測：計價待辦時，已完成的結算會被打回 |
| #2 | 已修 | 實測：負責人兼主管、代理兼投第二席都回 409；copy_pilot 改成主管席留空（試行案需另指派主管） |
| #3 | 已修 | 讀碼：switch_workspace、lark_callback 不再寫工作區；copy_pilot 改 FOR UPDATE＋版本比對。無專屬回歸測試，未收斂成 storage.commit |
| #4 | 已修（帶出 C65） | 實測：測試區停權不影響正式區。登入與寫入各自更新人員資料、互不鎖定，同時發生仍後寫者勝 |
| #5 | 已修（帶出 A57） | 實測：降級管理員 403；部分更新不復職、不清部門與預設工作區 |
| #6 | 已修（展延） | 實測：執行展延後無已完成節點變 rework |
| #7 | 部分修 | 已遮：背景工作內容、能力與訓練、他人代理與請假。實測仍外洩：他人班表、人員異動事件完整前後 JSON、全員名單全欄（含名冊紀錄編號、權限）、`/api/session` 未過濾、base_token、一般成員讀 `/api/sources` 原始紀錄、`/api/audit` 看得到他人班表異動 |
| #8 | 部分修 | 實測：schedule 已跳過 intake；但 `new_project('intake')` 仍產 9 節點（讀碼） |
| #9 | 已修 | 實測：無外業節點不再中斷排程 |
| #10 | 未修 | 讀碼：source run_due／failure／sync、people _save、jobs commit 仍 bump 版本號 |
| #11 | 部分修＋回退 | lark 模式 identity 改查 PersonRow（1.2→0.19 秒）；deepcopy、migration_archive（3.5MB 在根 JSON）、每次算全部案件都還在。實測真實資料：load 1.95 秒、save 3.85 秒、`/api/workspace` 7.2 秒回 7.68MB、comment_add 11.5～15.3 秒（見 B60） |
| #12 | 部分修 | events 不再改寫 ordinal（實測）；approvals 仍 insert(0)、無保留上限 |
| #13 | 已修 | 讀碼＋測試：sync_revision 與 last_sync 在上鎖後比對 |
| #14 | 未修 | Codex 刻意保留並以 test_source_identity 鎖定；快取 0 例 |
| #15 | 部分修 | 重播：刪日報會標「來源已移除」；刪確認單後案件仍正式、執行中（見 D71） |
| #16 | 部分修 | 只有 mention 設 remote_completed；digest、回寫、上傳遠端送出後 checkpoint 409 仍標 blocked |
| #17 | 部分修 | 缺附件時備份會失敗（實測）；預設上傳目錄仍不一致（備份 ./data/uploads vs app ./backend/uploads） |
| #18 | 部分修 | 主操作、上傳、Operations、原生審批遇 409 會重新整理；`ApprovalDetail.refreshRemote` 仍不會 |
| #19 | 部分修 | 錯誤橫幅改 sticky、z-index 110；TaskInspector、Participants、AddTask、Calendar 彈窗仍無內嵌錯誤 |
| #20 | **未修** | 實測：班表連結存 `javascript:` 成功（200）；後端 `management.py` `schedule_set` 未驗 URL；前端 `Operations.tsx`、`Deadlines.tsx` 未用 safeUrl |
| #21 | 未修 | 實測：5 位使用者只存成 4 列（重複 id 默默吃掉） |
| #22 | 未修 | 無 advisory lock |
| #23、#24 | 未修 | 大小寫編號不相等；132 筆暫填碼只有 1 筆對得到待確認案 |
| #25 | 部分修 | 同步要求涵蓋全部設定的表；日報表標錯類型時 9 張靜默變 8 張 |
| #26 | 部分修 | 公式日期欄已修；非公式欄 46000 仍解成 1970-01-01 |
| #27 | 部分修 | Input 先比對再寫、寫後讀回；訓練先查後建；上傳結果不明時不重傳但會卡死 |
| #28 | 未修 | 禁寫名單仍無 v3 PROD `Sdw1bG1djaHsVGsRPvmjyVWipgg` |
| #29 | 部分修 | 金額改 Decimal 字串、正式區 finance_* 一律 403；demo/test 仍可自核、parts 型別錯仍 500 |
| #32 | 未修 | 無 cookie 請求仍每次建 demo 工作區；真實快照已累積 14 個 |
| #33 | 未修 | 實測：非正式環境＋示範模式下，用寫死預設密鑰偽造 cookie 可讀正式區（200） |
| #34 | 部分修 | 背景同步改用應用身分；使用者 token 仍明文存 DB |
| #35 | 未修 | 迴圈結構未變且在鎖內；535 筆 2.7 秒，放大 4 倍 4.4 秒 |
| #36 | 未修 | 三個排程入口仍先上鎖＋整份載入才判斷是否到期 |
| #37 | 已修 | 讀碼：加了版本比較與請求序號 |
| #38 | 部分修 | 點背景仍直接關閉；多數表單改暫存 sessionStorage 可恢復 |
| #39 | 已修 | 讀碼：改在 onChange 偵測、略過輸入法組字 |
| #40 | **改壞** | tsc 失敗：`FileWorkspace.tsx` 用了 ProjectFile 沒有的 `category_id`；`Project.due_date` 仍非 nullable；TrainingPlan 仍缺 returned |
| #41 | 未修 | App 只有 1 個 useMemo；nameOf 線性搜尋 31 處；TaskTable 無分頁 |
| #42 | 部分修 | 拆出幾個新檔；App.tsx 最長一行 4,550 字元；無 Prettier |
| #43 | 已修 | 實測：失敗不留殘檔、壞 daily 改名重建、月備份從已驗證 daily 產生、loop 捕捉例外（另見 B64） |
| #44 | 部分修 | 同容器內設了 BACKUP_DIR 才啟動排程；不檢查持久 volume、無異地副本 |
| #45 | 部分修 | 讀 DB 移進 try、心跳寫 CacheRow；health 不讀心跳、log 無 traceback（另見 B62） |
| #46 | 部分修 | 見新發現 D70～D74：已接上正式送審，但無測試白名單、無撤銷、會產生孤兒審批 |
| #47 | **未修** | 實測：PM 用 project_roles 把節點主管改成任何人，跳過審核的主管席跟著變 |
| #48 | 未修 | 實測：執行第一筆申請後第二筆 409 |
| #49 | 未修 | 實測：一般成員切進測試區成功 |
| #54 | 部分修 | 草稿改存 sessionStorage；慶祝動畫整案範圍仍會誤算；playful-theme.css 仍在 |
| D1 | 部分修 | 實測：capability_ 動作 404、背景工作擋住；但回寫程式仍在，只靠 `FEATURE_LEARNING=False` 一個開關，不是整條移除 |
| D2、D3 | 已修 | 實測：training_save 404；旗標擋分派、路由、worker；schedule_set、quote_review 已移到 `management.py`；前端學習頁導回管理頁 |
| 1-b | **未修** | 實測：已結案案件把 PM 停權後，結算與計價變 rework、案件退回工程完成 |
| 1-d | **未修** | 實測：外業已完成時記「完工」事件，節點變 rework 並多一條必做任務 |
| 1-e | 未修 | 實測：新增一筆收款就把計價打回；因 #1 已修，計價被打回會連帶撤回結算 |
| 0-a | 未修 | 實測：記「派工排定」後派工前聯絡任務共 3 條 |
| 0-c | 未修 | 報價仍是 266 個待確認案 |
| 0-d | 未修且範圍更廣 | 讀碼：配對版本改為遞迴收錄日報與所有關聯紀錄全部欄位，任一欄變動人工配對即失效 |
| 2-a | 部分修 | approve_capability 已從管理員拆出；`capable()` 對管理員仍全部放行 |
| 2-b、2-c、2-d | 未修 | 無集中 `can()`／預設拒絕；讀取仍黑名單；無職責分離規則表 |
| 3-b | 未修（潛在） | 15 案同時讀兩份確認單，目前欄位一致尚未產生假衝突 |
| 3-c | 部分修 | 正式寫回開關預設關；Input 仍寫 V4 來源表 |
| 3-d、3-e | 未修 | job_retry 仍拒收 unknown、無核實動作；程式無 prefill |
| 4-a、4-b、4-c、4-e | 未修 | 背景 metadata 仍在版本號內；分派順序不變、`node_complete` 仍有兩處（operations.py、workflow.py）；jobs 仍在文件內；無 ruff／prettier／check 腳本、git 0 commit |
| 5-a～5-e | 多數未走，5-b 反向 | 案件頁籤由 11 減到 5；但首頁結構未變、「流程與交付」仍 8 個子頁籤；工作台內新增 Lark 送審三步與財務確認草稿（與 Lark 重疊更大）、無每日推播；概念未隱藏、另新增 7 種檔案分類；無底部導覽；5 個試行畫面未建 |

### 新發現（第三輪）
| 編號 | 嚴重度 | 問題 | 位置 | 修法 | 驗證 |
|---|---|---|---|---|---|
| — | **P0（開啟前）** | **原生審批第一次端對端會發給真實員工**：只准正式工作區送、核准人取案件 PM／主管／行政，無測試用審批定義與測試核准人白名單；唯一開關是 `LARK_NATIVE_APPROVAL_MAPPINGS_JSON` 是否設定 | `native_routes.py`、`native_requests.py`、`app.py` 註冊 | 加測試定義與測試核准人白名單，白名單外拒送；加總開關並寫入 .env.example | 讀碼 |
| D70 | P1 | 原生審批綁定範圍包含常變動的來源欄位（確認單實際總成本、報價、合約、填報全欄）→ 記一筆成本、下次同步後送審中的申請永久作廢（財務類一查詢就 409），員工 Lark 仍待審＝孤兒審批 | `native_requests.py`／`native_approval.py` 的範圍雜湊 | 範圍只綁申請本身影響的任務版本，不含來源成本欄位 | 重播實證 |
| D72 | P1 | 送出逾時後查不到實例、或 401/403，被當確定失敗、標作廢、不准再查；Lark 若已建立即成孤兒 | 原生送審錯誤處理 | 標「結果未知」並保留查詢；以送審 UUID 查回 | 讀碼 |
| D73 | P2 | NativeApprovalPoller（照送審當下版本查詢）沒接線 | `native_poller.py` | 接上 poller | 讀碼 |
| D74 | P2 | 本地撤回與 node_skip 本地流程不檢查是否已原生送出；舊 `/api/approvals/{id}/refresh` 用另一組審批代碼設定 | `workflow.py` approval_withdraw、`node_skip.py`、`app.py` refresh_approval | 已原生送出者禁止本地撤回或同步呼叫 Lark 撤銷；統一審批代碼設定 | 讀碼 |
| D71 | P2 | 案件層級「來源已移除」要全部來源列消失才成立，報價列通常還在 → 確認單被刪的案件永遠不標記 | `v4_sources.py` | 以確認單為案件存在的判準 | 讀碼 |
| B60 | P1 | **效能回退主因**：每次寫入整份算兩次 audit.entities（各約 0.85 秒） | `app.py`／audit | 只算受影響案件，或寫入時直接記差異 | 實測 |
| B61 | P2 | storage 層事件改不了也刪不掉 → 無法設保留上限 | `storage.py` | 事件只附加但允許封存／清理 | 實測 |
| B62 | P2 | worker 每輪結尾心跳寫入在 try 外，DB 短斷即讓 worker 結束並拖整個服務重啟 | `scripts/run_worker.py` | 心跳寫入包 try | 讀碼 |
| B63 | P2 | 唯一失敗測試 `test_backup_restore_normalized_rows_and_file_hash` 寫死專案 'p1'，fixture id 已改隨機 | 測試檔 | 改用 fixture 的實際 id | 實測 |
| B64 | P2 | 備份：`.invalid-*` 壞檔永不清；每 60 秒重讀驗證整份 daily；`os.link` 在不支援硬連結的目錄會一直失敗 | `scripts/backup_schedule.py` | 清理壞檔；驗證結果快取；硬連結失敗改複製 | 實測／讀碼 |
| C65 | 中 | 測試區任一寫入會把全員當下角色存成測試區副本；之後正式區降級某管理員，他在測試區仍是管理員，可複製正式案件、啟動 worker | `app.py` load／persist_mutation＋`production_access.test_profile` | 副本只存測試區真正改過的欄位；正式區降權時取交集 | 實測 |
| C66 | 低 | 設定檔指定的管理員每次登入權限被重設，已撤回的能力認定權自動回來 | `app.py` lark_callback | 只在第一次登入套用 | 實測 |
| C67 | 中低 | 啟動管理員永久不用核對名冊；名冊找不到或不明仍放行 | `production_access.admitted` | 名冊核實到此人後清除啟動標記 | 實測 |
| C68 | 低 | 名冊同步狀態的問題清單（含名冊紀錄編號）與薪水 Base 的 base_token 全員可讀 | people_directory 同步狀態 | 只給人員管理者 | 讀碼 |
| A55 | 中 | 來源「已完工」的案件，到期待辦仍被 worker 自動啟用，節點與案件變回進行中 | `workflow_rules.py` execution_reasons／activate_scheduled | 已完工或 source_completed 時排除 | 實測 |
| A56 | 中 | 修 #8 前替 intake 建的週期工作仍每天提醒；週期工作指向不存在的案件時 `find` 404 讓整個排程中斷 | `jobs.py` schedule | 跳過 intake 並停用其週期工作；找不到案件時略過並記錄 | 實測 |
| A57 | 中低 | 非管理員行政停權離職者時，只要對方有行政沒有的權限就 403（違反「行政需能停權離職者」） | `operations.py` admin_person | 只有權限清單有變動時才檢查「不可超出自身」 | 實測 |
| A58 | 中 | 匯入在途案：來源已完成的報價／派工／確認單，結算前置只認本地完成、又不准對來源已完成節點申請跳過 → 只能補做本地簽核 | `operations.py` settlement_preconditions、`node_skip.py` current | **待業主裁示 Q9**（見 DESIGN_REVIEW） | 實測 |
| E75 | P1 | 前端型別檢查失敗（同 #40） | `FileWorkspace.tsx` | 補 ProjectFile.category_id 型別 | tsc |
| E76 | P2 | 跳過草稿暫存鍵綁 `p.revision`，同案有人操作一次，已打的理由就消失 | `App.tsx` | 改綁節點 id | 讀碼 |
| E77 | P2 | 原生審批與財務確認繞過操作鎖、成功後整包重下載；「来源」誤用簡體字 | `NativeApprovalControls.tsx` | 走 run 的操作鎖；修字 | 讀碼 |
| E78 | P2 | 日報查詢無 debounce，每次版本變動都重抓 | `DailyRecords.tsx` | 加 debounce、只在查詢條件變時重抓 | 讀碼 |

### 建議 Codex 下一步順序
1. **原生審批開啟前**：測試白名單、D70、D72、D74（撤銷）。
2. **P1 未修**：#20 XSS、E75/#40 tsc、B60 效能回退、1-b（停權重開結案）、1-d（完工事件打回外業）、#47、#7 剩餘外洩、C65。
3. **產品方向**：暫停新增畫面與流程（5-b 反向）；依 DESIGN_REVIEW 5-e 收斂成 5 個試行畫面。
4. 其餘部分修與 P2。


## 測試稽核：變異測試（2026-09-28）

> 做法：在 %TEMP% 副本對 12 條關鍵規則「一次拿掉一條檢查」，看 549 個後端測試抓不抓得到。存活者再跑全套確認仍全綠。基線本身有 1 個紅燈（B63），已排除。
> 「存活」＝規則目前還在、程式沒錯，但**沒有測試守著**，之後被改掉也不會有人發現。

| 變異點 | 結果 | 應補的測試 |
|---|---|---|
| 1 `persist_mutation` 拿掉 version==expected | 存活（等價：資料庫條件式 update 仍回 409）；連條件一起拿掉才被抓 | 不急 |
| 2 拿掉 receipt fingerprint 比對 | 被抓 | — |
| 3 `origin_guard` 拿掉 sec-fetch-site 跨站檢查 | **存活**（只測了 evil origin） | 不帶 Origin、只帶 `Sec-Fetch-Site: cross-site` 的 POST 應回 403 |
| 4 `download` 拿掉 is_relative_to | **存活** | 檔案 id 為 `../x` 或 symlink 時應回 404 |
| 5 `identity` 拿掉停權檢查 | **存活**（寫入仍被擋，但停權者拿舊 cookie 仍可讀整個工作區） | 停權後 GET /api/workspace、/api/session、下載應回 403 |
| 6 財務節點送審「兩方不同人」 | **存活**（另一道 require_financial_pair 單獨或一起拿掉也存活）；規則目前靠 project_roles 與 vote 兩道守住，但若 PM 與行政經來源匯入變成同一人，就只剩投票那道 | 直接把 PM 與行政設成同一人，送審應 409；同一人投兩票 finance_approve 應 409 |
| 7 `admin_person` 不得授予超過自己的權限 | **存活** | 持 manage_people 的非管理員授予 finance_approve 應 403 |
| 8 task_complete 限負責人／代理 | 被抓 | — |
| 9 來源快照有表未 ready 仍套用 | 被抓 | — |
| 10 租約過期轉 outcome_unknown | 被抓 | — |
| 11 正式 Base 當測試目的地 | 被抓 | — |
| 12 `storage.save` 刪除舊列 | 被抓（但只被無關的 worker 測試間接抓到） | 直接測：刪除後重新載入資料應消失 |

**弱測試**
- 只 assert 200：`test_backend.py` 多處把 `status_code==200` 當前置步驟、不檢查資料狀態。
- 只驗模擬路徑：遠端寫入只測過模擬或假 adapter，沒有對 Lark 回應格式的契約測試。
- 依賴固定日期：seed 寫死 as_of 2026-09-25、假日 09-28、到期日 2026-10；`test_sop_deadlines` 32 處、`test_worker_reliability` 22 處。代理有效期與租約跟真實時間比對，**日期過了可能整批變紅**（未實測；建議把時鐘撥到 2027 跑一次）。

**缺陷與測試的對應**：#3（並發覆寫）與 #6（展延後已完成節點被打回）存在時整套測試全綠；目前仍沒有鎖定這兩件事的回歸測試。

**最該先補的 5 個測試**
1. 權限提升：非管理員持 manage_people 授予超出自己的權限應 403（變異 7）。
2. 停權者讀取：停權後用既有 cookie 讀工作區、session、附件應 403（變異 5）。
3. #6：執行展延或變更後，其他已完成節點與已核准審核輪不變。
4. #3：A 讀取 → B 新增留言 → A 走 switch_workspace／copy_pilot／lark_callback → 留言仍在、版本號只增不減；並直接測 storage.save 的刪除（變異 12）。
5. 財務同一人：PM 與行政設同一人（模擬來源匯入）送審應 409；同一人投兩票應 409（變異 6）。


## 修正追蹤（第四、五輪：9/28 13:30 → 18:27）

> 來源：6 路唯讀審查（13:30→14:04 後端／前端各 1 路；14:04→18:27 後端與部署／前端與計畫文件各 1 路；懷疑派抗辯 1 路；裁示合規表 1 路）。懷疑派已挑戰過本節結論，措辭依其更正。
> **測試**：後端 628 個全過（0 失敗）；前端 tsc 通過（E75／#40 已修）。

### 一、本輪狀態變化
| 編號 | 新狀態 | 說明 |
|---|---|---|
| #40／E75 | **已修** | tsc 結束碼 0（新舊版對照） |
| #11 | 部分修、明顯改善 | migration_archive 移出根 JSON（4.40MB→92KB）；只重算受影響案件。真實資料：load 1.95→0.73 秒、save 3.85→1.85 秒、comment_add 11.5～15.3→6.2～8.6 秒、/api/workspace 7.2→3.4 秒；但回應 8.6～10.8MB（成員視角 projects 占 7.0MB） |
| #10／4-a | 部分修 | 新增 per-project `concurrency_version`：不同案件的留言互不 409；但 project_roles、node_complete、approval_* 仍比全域版本；背景同步仍推進版本（見 #80、#81） |
| B60 | **改壞（#96）** | audit.entities 每次寫入仍算兩次，且更慢（合成 270 案 0.73→1.05 秒） |
| #7 | 部分修 | 已剝除員工編號與請假；仍外露 capabilities、record_id、directory_source、identity_app_id、bootstrap_admin；稽核改依案件篩選 |
| #20 | 部分修 | 前端新班表頁與 ProjectReadiness 已檢查 http(s)；後端 `management.py` `schedule_set` 仍未驗 URL；連結檢查有三套實作（#92） |
| 0-c | 部分修 | 新增報價／確認單／合約項目三個獨立集合；但仍建出 264 個待確認案 |
| C66、B63 | 已修 | — |
| #44、#45 | 部分修（小幅進步） | 備份記真實快照時間、月備份校驗；新增管理員用 runtime-health 可讀 worker 心跳；但 `/api/health` 與 Docker 健康檢查仍不看心跳、無告警、無異地備份 |
| B64 | 改壞 | 每 60 秒整份重新校驗日／月備份（#99） |
| 1-b、1-d、#47、#48、A55、D72、原生審批測試白名單、#18、#19、#38、#41、#42、E76～E78 | 未修 | 相關檔案零變動或結果同前 |
| D70 | 惡化 | 報價多抓 8 個入帳欄並進入送審範圍，每次入帳都會讓送審中的申請作廢 |

### 二、新發現（#79～#112，已套用懷疑派更正）
| 編號 | 嚴重度 | 問題 | 位置 | 修法 |
|---|---|---|---|---|
| #84 | **P1** | 從舊資料遷移的真實工作區沒有 `environment` 欄，畫面卻因預設值顯示「正式」。結果一半放行、一半鎖死：**財務節點可用站內投票完成、不要求原生核准、結算只看本地對帳**（繞過 Lark）；反而 `financial_finalize` 回 409、`native_poller` 從此不查回 Lark 審批。新建工作區不受影響 | `app.py` load（約 217、147 行）、`operations.py`（約 168、196、222、289、304、565 行）、`native_poller.py`（約 54 行） | 載入時依工作區 id 推導並補寫 environment；缺值一律視為正式並 fail-closed |
| #80 | P1 | `import_v4` 每次同步無條件寫 `source_changed_at`：同一份資料重匯，15 個正式案版本全部 +1；名冊同步 3 次、工作區版本 2→3→4。頁面開著跨過一次同步後，下一次操作會 409（前端只在視窗取得焦點時重抓） | `v4_sources.py`（約 296 行）、`source_sync.py`（約 113 行）、`people_directory` | 來源內容真的有變才更新；背景狀態不推進版本 |
| #79／#90／#108 | P1 | **財務範圍擴大，且沒有財務開關**：finance_readiness 面板、`financial_finalize`「核實條件並完成財務節點」、應付款聲明、收支結案面板；計價／結算節點仍生成。一般成員可看到 148 筆報價的契約價格（未稅）。（業主裁示：試行不含財務） | `finance_readiness.py`、`operations.py` financial_finalize、`source_entities.py`、前端 Operations／ProjectReadiness | 加 `FEATURE_FINANCE=False`，關閉兩個財務節點、財務審批與面板；非財務人員剝除金額欄 |
| #85／#107 | P1 | **仍匯入全部 V4 舊案**（無日期篩選）：248 個舊報價案有已指派、未完成的任務，其中 569 筆已逾期，試行時會灌進待辦。（業主裁示 Q9：不匯入舊案） | `v4_sources.py` import_v4 | 設上線日期；之前的案件只留作來源參考、不建節點與任務 |
| #106 | P1 | Codex 的 `docs/APPROVED_PRODUCTION_PLAN_20260928.md` 第 3 行寫「優先於 2026-09-27 文件中與本次決策不同的內容」，而業主 Q1～Q9 正記在 9/27 的 DESIGN_REVIEW；該計畫把 Q9 寫成「Meegle 不匯入舊案件」（V4 照匯）、未寫 Q2「試行不含財務」反列財務雙人確認為驗收項、未寫 Q4 拆角色、未寫原生審批測試白名單前提；並自行新增 3 條「固定決策」（第 18～20 行）找不到業主核准紀錄（#109） | `docs/APPROVED_PRODUCTION_PLAN_20260928.md` | 請業主確認以哪份為準；計畫改為引用 DESIGN_REVIEW「業主決定」表 |
| #97 | P1 | 部署是**直接覆蓋正在運作的正式服務**（yongxiang-projects-20260925），沒有另一個測試環境；新版啟動即遷移資料，退回舊版不保證讀得了新資料。部署阻擋清單未列 #79、#80、#84、#85、#20、1-b、1-d、#47、原生審批白名單、B60 | `docs/DEPLOYMENT_READINESS_20260928.md` | 先開 staging 服務；部署前完整備份並演練回退；把上列 P1 列為阻擋 |
| #91 | P1 | 修正後的範圍：展延／變更／跳過／財務在正式區已要求 Lark 回執（approval_submit 等在正式區 403/503，這部分不算違規）；**仍由站內投票定案的是外業／控制／圖資／報告四個成果節點**（review_submit／review_vote）；Lark 審批連結只有手動貼上的選填欄 | `operations.py`（約 288～331 行）、`App.tsx`（約 270 行） | **待業主確認 Q3 範圍**（一般成果節點是否也交 Lark）後再改 |
| #94 | P1 | Q4 只改了名稱：畫面標「系統管理員」，但程式仍讓管理員在任何案件代行 PM、一人即可核准整批交付；沒有限定組別的組主管角色 | `operations.py` capable／delivery_review、前端 25 處 `role==='manager'` | 拿掉管理員業務特權；新增限定組別的組主管 |
| #81 | P2 | 分案名單外的動作仍比對全域版本；背景的來源、名冊、班表（2 次）、jobs、poller 每輪推進全域版本 | `app.py` actions | 背景 metadata 移出版本號 |
| #82 | P2 | Attendance 班表 run_due 每 5 分鐘推進 2 次全域版本、寫 1 筆事件（一天 288 筆、無上限）、重寫全部班表列；觸發同步者停權後永久 403、worker 一直 degraded | `attendance_service.py` | 只在內容變更時寫入；改用應用身分；事件設上限 |
| #83 | P3 | `filter_private_workspace` 沒過濾 work_schedules（真實資料目前 0 筆；正常下班時間敏感度低） | `workspace_projection.py` | 只給本人與人員管理者 |
| #86、#87 | P3 | 班表同步比對 verified_at，同步期間有人登入就 409；舊手動班表結束時間為空或 24:00 時 cutoff 拋例外 | `attendance_service.py`、`learning.cutoff` | — |
| #96 | P1 | B60 惡化（見上） | `audit.py` | 只算受影響案件或寫入時直接記差異 |
| #98 | P2 | 還原演練無處可跑：`restore_drill.py` 不在打包白名單（雲端跑不了），文件又不准資料庫外網連線（本機連不到） | `scripts/restore_drill.py`、`deploy_prepare.py` | 納入打包或提供受控通道 |
| #99 | P2 | 備份排程每分鐘重讀完整備份檔，負載隨附件量成長 | `scripts/backup_schedule.py` | 快取驗證結果 |
| #100 | P2 | worker 心跳只在每輪開始與結束寫，單輪超過 5 分鐘會誤報過期 | `scripts/run_worker.py` | 迴圈內定期寫心跳 |
| #101 | P2 | 稽核記錄留言與審核輪的完整前後內容，一般成員只過濾人員與代理兩類 | `audit.py` | 依角色白名單投影 |
| #93／#102 | P2 | 新增概念與畫面（Attendance 班表同步、交付性質選項、確認單與合約工項子頁、結案條件面板、應付款聲明、7 類上傳分類、@同事 Lark 通知），與收斂成 5 個試行畫面的方向相反 | 前端多處、計畫文件 | 暫停新增，依 DESIGN_REVIEW 5-e 收斂 |
| #95、#112 | P3 | sourceQuotes 讓未對上的舊報價消失、可能產生重複 React key；工項關聯用 `any` 繞過型別、對不到時顯示「未連結工項」會誤導 | `sourceQuotes.ts`、`App.tsx` | — |
| #110、#111 | P3 | 「獨立交叉審查」由實作者自己執行；Meegle 模板原始檔與擷取腳本在 .gitignore 排除的 .runtime/ | 文件 | — |
| MEEGLE_TEMPLATE_REVIEW | 備註 | 模板 334662 盤點成 JSON 作 SOP 對照，**沒有匯入舊案**；但待辦列了「條件式執行等價」，等於在工作台重做一套 Meegle 流程引擎，超出「只作對照」 | `docs/MEEGLE_TEMPLATE_REVIEW_20260928.md` | 請業主確認是否要做 |

### 三、業主裁示合規表（依 18:27 程式）
| 裁示 | 狀態 | 說明 |
|---|---|---|
| 暫時只要管理功能（學習模組關閉，班表與接案保留） | 已落實 | 旗標關閉、路由 404；schedule_set、quote_review 已搬到 management.py |
| D1 能力地圖不回寫 | 已落實 | 三層阻擋，無開關可重開 |
| D2 訓練紀錄停用 | 已落實 | training_record 一律 blocked |
| 暫存接案只產接案階段 | 部分 | 排程跳過、不能啟用，但仍產生 9 節點 23 任務 |
| Q1 以 V4 為準 | 已落實 | V4 狀態只作顯示，執行進度由工作台管 |
| Q2 試行不含財務 | 部分 | 非示範區財務動作寫死 403；但財務節點仍生成、#84 讓舊工作區可站內完成財務、無財務開關（#79） |
| Q3 審批交給 Lark | 部分 | 展延／變更／跳過／財務要 Lark 回執；一般成果節點仍站內投票（**範圍待業主確認**） |
| Q4 主管拆角色 | 部分（只改名稱） | 見 #94 |
| Q5 測試區分開 | 部分 | 可另設測試區角色，但未設時沿用正式區角色；任何登入者可切進測試區（#49） |
| Q6 日報預填連結 | 未落實 | 全 repo 無預填連結程式 |
| Q7 母案是案件 | 未落實 | 仍靠 regex 推導（v4_sources.py 約 278 行），彙總在前端 |
| Q8 技術節點不加 PM | 已落實 | 外業節點確認席只有負責人與組主管 |
| Q9 不匯入舊案 | 未落實 | 見 #85 |

**範圍外、需要業主同意的新功能**：Attendance 班表同步（需開 Lark 出勤讀取與員工編號權限、每 5 分鐘讀全公司班表）、正式區寫回 V4 欄位（開外部連線時生效）、@同事時發真實 Lark 訊息、Meegle 模板「執行等價」。

### 四、本輪更正（對先前說法）
- Q3：業主原話為「審批交給 Lark 處理？對」。DESIGN_REVIEW「業主決定」表中「工作台只顯示狀態、拿掉站內草稿＋投票」是主審的建議寫法，**不是業主原話**；一般成果節點是否也要交 Lark，待業主確認。
- Q2：業主原話為「試行要不要包含財務？不用」；「以旗標關閉」是主審建議的做法。
- #84 原寫「正式區防線全部失效」，更正為「一半放行、一半鎖死」並升為 P1。
- #85 原寫「來源已完成的節點一律算未完成」，實際原因是來源「狀態」欄全空；該半條撤回。
- #91 原將 approval_create／approval_confirm 列為違規，撤回（正式區已 403/503）。

## 第六輪：Lark 官方文件契約對照（9/28 夜，讀碼＋官方文件，未打真實 API）

> 基底網域 open.larksuite.com 正確；tenant token 每輪新取、無過期風險；bitable 分頁上限、欄位格式（person／link／日期毫秒）、IM content 字串化與 uuid、審批 form 字串化與 uuid、出勤 employee_id／yyyyMMdd／30 天／26:00 跨日皆與文件一致。以下為不一致處。

| 編號 | 嚴重度 | 問題 | 位置 | 修法 | 狀態 |
|---|---|---|---|---|---|
| #125 | P1（班表開啟後） | 文件寫明排班 `shift_id=0` 代表休息；程式把 "0" 當班次去查 `/shifts/0`，回 1226003 被判 blocked，整批同步失敗；預設查 14 天必含休息日 → 班表永遠不會 ready | `attendance_schedule.py` AttendanceScheduleReader.fetch | shift_id 為 "0" 直接標休息日、不查班次 | 讀碼＋文件；待首次真實串接確認 |
| #126 | — | ~~授權網址送 `app_id`、文件列 `client_id` 為必填~~ **撤回**：`docs/DEPLOYMENT_RECEIPT.md` 已記錄以真實帳號 jekai 經 OAuth 登入成功（mode=lark），Lark 實際接受 app_id | `app.py` lark_login | 可改 client_id 以符合文件，非阻擋 | 撤回 |
| #127 | P2 | user_info 回 user_id 需 `contact:user.employee_id:readonly`，範例 scope 只有 bitable 與 approval → 班表用的員工身分不會建立、全員「員工身分未核實」且無提示；應用另需 `attendance:task:readonly`、`attendance:rule:readonly`，部署文件未列；已登入者需重新登入 | `app.py` lark_callback、`.env.example`、`docs/DEPLOYMENT.md` | 補 scope、缺 user_id 時警示、文件列齊權限 | 讀碼＋文件 |
| #128 | P2 | 回應碼非 0 一律 blocked；但 1254290（過快）、1254291（寫入衝突）、1254607、1254036、IM 230020（限頻）、審批 1395001 依文件應重試；jobs 只重試 retry → 撞一次就永久卡住。限流讀 `Retry-After`，Lark 實際給 `x-ogw-ratelimit-reset` → 每次都用預設 60 秒 | `lark_adapter.py` request | 可重試錯誤碼白名單；改讀 x-ogw-ratelimit-reset | 讀碼＋文件 |
| #129 | P2 | 建立審批時確定沒建成（429、1395001、1390001）也改用 uuid 查詢，查不到就作廢、永不重送；文件保證同 uuid 只建一筆（衝突回 60012），重送安全 | `native_approval.py` NativeApprovalAdapter.submit | 確定沒建成的錯誤用同 uuid 重送 | 讀碼＋文件 |
| #130 | P2 | 讀請假審批 locale 送 'zh-TW'，文件只列 zh-CN／en-US／ja-JP；若被驗證會回 1390001，代理請假核實永遠 502；解析靠 widget id 不需 locale | `learning_sources.py` read_application_leave | 拿掉 locale 或改 zh-CN | 讀碼＋文件；待真實串接確認 |
| #131 | P3 | 先檢查 HTTP 非 200 就報錯，但 1254302 回 HTTP 403 → 專為 1254302 寫的提示永遠不出現；adapter 遇 4xx 丟掉回應內容，無法分辨 token 失效或 1254xxx | `sources.py` fetch_sources、`lark_adapter.py` | 先解析回應內容再判斷狀態 | 讀碼＋文件 |
| #132 | P3 | v2 換 token 失敗（授權碼過期／重用、redirect_uri 不符）回 4xx，被當網路錯誤顯示「登入服務暫時無法連線」（502），誤導排查 | `app.py` lark_callback | 分開處理 HTTP 狀態錯誤與連線錯誤 | 讀碼＋文件 |

### 線上狀態（23:26 核對）
- Codex 23:12 部署新版（deployment `6aba8387…`），環境設定含 `LARK_NATIVE_APPROVAL_MAPPINGS_JSON`，四類（change／extension／financial／node_skip）皆有對應 → **線上已可送出 Lark 原生審批**；原生審批模組內未見測試審批定義／測試核准人白名單。已通知業主，詳細核對見下一輪。
- 同版將環境設定完整合併為 19 個鍵並讀回（U4 擔心的整組覆蓋未發生）。

## 第七輪：線上原生審批、安全性、新模組逐檔精讀（9/28 23:26 程式）

> 3 路唯讀審查；實驗只在 %TEMP% 副本，外呼 0 次，未碰線上服務。後端測試 684 個全過。

### 一、線上原生審批（23:12 部署版）——**會發給真實員工，且沒有擋板**
- 條件：環境設定有 `LARK_NATIVE_APPROVAL_MAPPINGS_JSON`（線上已有四類）且 `LARK_WORKER_IDENTITY=application`。
- 誰能送：已登入核實的員工，本身是申請人、案件 PM，或 manager（`is_pm` 讓 manager 可代任何案件，#94）。發給：案件資料中的 PM＋主管（跳過、設計變更）或 PM＋行政（財務）。
- DEMO_MODE=true 也能送：`app.py` 無條件註冊原生審批路由，`native_routes.formal()` 只檢查 mode=lark 與 wid=lark-組織。
- NativeApprovalPoller 已接線（`run_worker.py`），依送審當下的 uuid 與對應查回 ✓。

| 編號 | 嚴重度 | 問題 | 位置 | 修法 | 驗證 |
|---|---|---|---|---|---|
| #159 | **P0（線上）** | 原生審批無總開關、無測試審批定義與測試核准人白名單，示範模式也能送 | `native_routes.formal`、`app.py` 註冊 | 加啟用旗標（預設關）與核准人白名單；示範模式一律拒絕 | 讀碼 |
| #160 | **P1** | 舊工作區缺 environment 時，`native_requests.actors` 跳過核准人在職核實照樣送出；手動查回顯示「已核准」卻永遠無法套用，背景查回也不查（#84 延伸） | `native_requests.actors`、poller | 載入時補 environment；缺值 fail-closed | 實測重現 |
| #161 | **P1** | D72 仍在：送出逾時接 401 → 本地作廢、再查回 409；背景查回後來看到 APPROVED，狀態仍是作廢 | `native_approval.submit` 錯誤處理 | 標「結果未知」保留查詢；以 uuid 查回後更新 | 實測重現 |
| #162 | **P1** | D70 仍在且擴大：來源同步後送審中的申請被作廢、不呼叫 Lark 撤銷；設計變更另兩線確認也綁同一範圍 | `native_requests` 範圍雜湊 | 範圍只綁申請影響的任務版本 | 實測重現 |
| — | P1 | 本地撤回（`approval_withdraw`、`node_skip_withdraw`）只改本地，不撤 Lark 那張 | `workflow.py`、`node_skip.py` | 已原生送出者撤回時呼叫 Lark cancel | 讀碼 |
| #129 | P2 | 確定沒建成時不重送（未修） | `native_approval.submit` | 同 uuid 重送 | 讀碼＋文件 |
| #163 | P2 | 財務申請路由已上線、無開關（Q2 試行不含財務；#79 實質惡化） | `native_routes` financial | 財務旗標預設關 | 讀碼 |
| #164 | P2 | 設計變更「三線確認」實際只兩人：主管一人可登錄「主管確認」與「業主佐證」兩線；業主佐證接受純文字（PM 可自打「業主已同意」）；「改成 PM＋主管」依據是設定文件自稱的「使用者決定」 | 設計變更確認流程 | 三線須三個不同人；業主佐證需檔案或 Lark 回執 | 讀碼 |
| #165 | P2 | `attendance_service._state` 推定舊工作區為正式區，第一次班表同步儲存時把整個工作區改成正式 → 一次改變財務、查回、核准人核實等行為，無明確遷移步驟；應用身分設定不全時背景每輪報錯 | `attendance_service._state` | 以明確的遷移步驟設定 environment | 讀碼 |
| #166 | P3 | 登錄確認線時用 5 分鐘內的查回結果重算，「已核准」可能暫時跳回「待審」 | 設計變更確認 | 只往前推進狀態 | 讀碼 |
| #167 | P3 | `verify_definition` 拿掉 START/END 過濾：未填 `boundary_nodes` 直接拒絕（安全方向）；格式錯誤的 `boundary_nodes` 回 500 | `native_approval.verify_definition` | 驗證格式、回 422 | 讀碼 |
| #168 | P3 | Drive 送存結果未知時無核對路徑，新防護又禁止重新排隊，只能重傳新版本；Input 專用表白名單未排除 v3 正式 Base `Sdw1bG1djaHsVGsRPvmjyVWipgg`（靠雙重設定擋住） | jobs Drive、`remote_policy` | 加核對動作；FORMAL_BASES 補 v3 PROD | 讀碼 |

### 二、安全性（新攻擊面）
| 編號 | 嚴重度 | 問題 | 位置 | 修法 | 驗證 |
|---|---|---|---|---|---|
| #143 | **P1（線上）** | 示範站不用登入即自動取得 u-pm 身分，可無限上傳（每檔 25MB）與寫超長留言；示範資料與真實工作區共用磁碟與資料庫；上傳先整檔寫入磁碟才檢查權限 | `app.py` get_session、upload | 示範區禁止上傳或設配額＋IP 限流；先檢查權限再收檔；示範站與真實工作區分開部署 | 實測（匿名上傳磁碟 +20MB、3MB 留言回 200） |
| #144 | P1 | `approval_create`、`file_link` 的 title／reason／attachments／name 可存成物件（回 200）；前端 `{a.title}`（首頁等 5 處）、`{f.name}`（4 處）遇物件拋錯，全站無 ErrorBoundary → 所有人打開首頁或案件頁白屏，只能改資料庫救；PM 或任一節點負責人即可觸發 | `workflow.py`／`operations.py` 對應 action、`App.tsx` | 每個 action 定 schema、一律轉字串並限長；前端加 ErrorBoundary | 後端實測；白屏讀碼 |
| #141 | P1 | @標註通知把留言內文原樣（最多 1500 字）放進公司機器人私訊、排在正式連結前；可放 `[詠翔工作台](https://evil)`、`<at>` 或偽造連結 → 以公司名義釣魚 | `mention_notifications.notification_text`、`lark_adapter.message` | 改卡片訊息、跳脫 `[]()<>`、正式連結置前、內文只給 200 字摘要 | 實測產出文字；渲染依文件判斷 |
| #142 | P1 | 留言無頻率限制，每則可標 50 人、則數不限；實測 40 次請求 9.5 秒排進 242 則通知，正式區每則都是真私訊 | `comment_add`、`enqueue_mentions` | 每人每小時配額、同收件人合併、管理員一鍵停發 | 實測（模擬模式） |
| #145 | P2 | 型別錯誤回 500（dates=['x']、task_ids=[[1]]、demo/session 送陣列）；原生審批等端點直接 `body.get`；文字欄無長度上限（3MB 留言讓每次 /api/workspace 回 3.3MB） | 各 action、原生審批端點 | Pydantic schema、body 限 dict、長度上限 | 實測 |
| #146 | P2 | 檔名保留 RTLO 與零寬字元（`report‮fdp.exe` 顯示成 pdf），CSV 索引與送 Drive 檔名照用；無副檔名白名單，.exe/.html 可經 store-lark 進公司 Drive | upload `safe_name`、store-lark | 去除 Cf/Cc 字元；依分類設副檔名白名單 | 實測 |
| #147 | P2 | reference_url、file_link 接受 http:// 與內網位址（`http://127.0.0.1:8080/admin` 回 200）；後端不抓取（非 SSRF），但畫面當公司連結呈現 | `workflow.http_url` | 只收 https、網域白名單 | 實測 |

**確認做得對**：下載一律 octet-stream＋attachment＋RFC5987＋nosniff（HTML/SVG 不會同源執行）；非負責人上傳、他案檔案 store-lark 皆 403；@標註收件人限名冊核實在職者、停權者 409、測試與示範區通知強制模擬；原生審批核准人由伺服器推導不可指定、只有建立者或 PM 能操作、uuid 防重送加綁定雜湊、拒收 AUTO_PASS／加簽／轉交；runtime-health、worker/run、attendance/sync、sources/people sync 一般成員皆 403；前端無 dangerouslySetInnerHTML；instance_code 有格式檢查、使用者 URL 只存不抓。

### 三、新模組逐檔精讀
| 編號 | 嚴重度 | 問題 | 位置 | 修法 | 驗證 |
|---|---|---|---|---|---|
| #149 | P2 | 正式 Drive 目的地只看工作區設定（manager 即可改），drive_root 設成任意資料夾或測試目錄都放行；Input 則需伺服器＋工作區雙重核定 | `remote_policy.connection_policy`（kind='file'） | 比照 Input：必須等於 cfg `LARK_DRIVE_ROOT` 且非測試目錄 | 實測 |
| #150 | P2 | 稽核漏記：改 drive_root／input_base／external_enabled、新增 financial_requests → changes=[]；admin_settings 事件無前後值 | `audit.entities` | settings、financial_requests、input_revisions 納入比對 | 實測 |
| #151 | P2 | 最新核准的 all_settled 佐證撤回後，舊的 no_payables 仍有效 → 判可結案 | `finance.payables_readiness` | 只看最新一筆核准聲明，失效判 unknown | 實測 |
| #152 | P2 | PM＋業務已認定 duplicate 的報價仍要求結清 → 永遠 unverified，與 quote_review 規則矛盾 | `finance.incoming_readiness` | 排除最新核准為 duplicate 的報價（需業主裁示） | 實測 |
| #155 | P2 | 約 62 人一次送 `user_daily_shifts/query`；若官方 user_ids 上限 50 → 整批失敗 | `attendance_schedule.fetch` | 每 50 人分批 | 未驗證（需官方文件） |
| #153 | P3 | 覆寫 Attendance 班表列後殘留 pending_schedule 等欄；無 version 舊列 KeyError 500 | `management.schedule_set` | 整列重建；`.get('version',1)` | 實測 |
| #154 | P3 | 日報列從完整讀取的表消失後，task.contract_item_ids 仍指向舊合約，兩邊不一致 | `source_entities.update_entities` | 缺列時清空並標 unresolved | 實測 |
| #156 | P3 | Drive 資料夾名用可變的 p['code']＋節點名 → 改碼後同案分兩個資料夾；code 為 None → TypeError | jobs file 分支 | 用 p['id'] 或保存 folder_token | 讀碼 |
| #157 | P3 | `verify_file` 把 401／403／5xx 都報「校驗不符」、failed 不重試；註解說保留本地副本實際沒有；整檔讀進記憶體 | `lark_adapter.verify_file` | 依狀態碼分類、串流算 hash、改正註解 | 讀碼 |
| #158 | P3 | 來源連結網域寫死，jobs 卻讀 `LARK_COMPANY_DOMAIN` → 改設定後連結不一致 | `source_entities`、`source_projection` | 統一讀設定值 | 讀碼 |

另：`workflow_rules` 在缺 environment 時 assignable 全部放行（#84 延伸）；`people_directory` 第 213 行有簡體字「变」。
**最該補的測試**：payables 多筆聲明（最新失效）；正式環境 Drive 目的地驗證；lark_adapter 的 folder／upload／verify_file（完全無測試）；workflow_rules.assign_node；audit 非案件集合比對與 scrub。

### 四、實際操作測試（示範伺服器＋瀏覽器，u-pm／u-field／u-manager × 手機／桌機，117 頁次）

**全部頁次無 console error、無未捕捉例外、無 4xx/5xx、無白畫面、無橫向捲動。** 確認正常：`<script>`／emoji／全形字以純文字顯示；`javascript:` 連結被擋（400）；上傳下載成功（含 emoji 檔名）；組員改別人任務時按鈕停用且後端 403；空值必填驗證；展延填過去日期被擋；兩分頁同時操作出現 409 時表單內容與留言草稿都保留（但同案有人留言，另一分頁留言也會 409）。截圖在 %TEMP%\cr-d2\shots\。

| 編號 | 嚴重度 | 問題 | 重現 | 修法 |
|---|---|---|---|---|
| #133 | P1 | 外業任務按「開始作業」或「完成任務」回 409「行政公務證明尚未齊備」，按鈕照樣可按，畫面也沒說要主管到「節點確認」子頁按「核准交付項目」；錯誤橫幅壓住任務標題 | u-field → p3 外業 t1 → 完成任務（截圖 flow_A2*、flow_A3*） | 任務抽屜寫出擋住原因＋前往連結，並停用按鈕 |
| #136 | P1 | 示範案沒有指派確認人，送審回 409「確認人尚未完整分派」，畫面沒說缺誰、去哪裡設 | 截圖 f3_T4_submit_review.png | 示範資料補主管；訊息列出缺的確認人並連到參與人員頁 |
| #134 | P2 | 規則不符也回 409，前端一律加「已重新整理最新狀態」，像是被別人改過，且與「此案件已被更新」重複 | — | 規則錯誤改回 422；那句話只在版本衝突時顯示 |
| #137 | P2 | 從任務按「展延」時，受影響任務一項都沒勾（0/21），清單含已完成任務，手機要捲約 940px | 截圖 f3_T6* | 預先勾選該任務、隱藏已完成 |
| #140 | P2 | 組員看得到也打得開「管理設定」，可看人員名冊、SOP、背景工作（寫入被後端擋） | 截圖 sweep_u-field_m_admin.png | 依角色隱藏選單項 |
| #135 | P3 | 畫面寫「尚缺…」，「送交節點確認」按鈕仍可按，按了才 409 | 截圖 f3_T1_submit_evidence.png | disabled 條件加上缺件數 |
| #138 | P3 | 手機版「提交交付資料」表單欄位右緣超出約 27px 被裁掉 | 同上 | 欄位 `width:100%`、`box-sizing:border-box` |
| #139 | P3 | 無長度上限：成果說明 2 萬字、任務名稱 600 字都能存 | — | 前後端加長度上限 |

### 五、時間與日期正確性（freezegun 時間旅行＋邊界情境）

**時間旅行**：時鐘固定到 2027-01-15、2026-12-31 23:59（執行中跨年）、今天＋400 天，各跑全部後端測試，結果都與未凍結時相同（682 過／2 敗，2 敗是 test_runtime 的子行程測試、與時間無關）。**更正「測試稽核」一節的預測：「日期過了會整批變紅」不成立**——測試都自己傳入時鐘，寫死的日期是自洽的輸入。代價是直接讀系統時間、沒經過 now() 的路徑幾乎沒有測試。

**邊界情境全部正確**：跨年工作日、週六補班（當天照發提醒）、負向工作日、次月第 5 工作日（春節順延）、09:00 提醒（08:59:59 不發、假日不發）、請假代理到期那一秒與跨午夜、UTC 與 +08:00 混用比較、班表 26:00／24:00／48:00。

**繞過單一 now() 的位置**：`finance_readiness.py`、`attendance_service.py`、`sources.py`、`audit.py`（UTC）、`runtime_health.py`、`app.py` 多處，以及多支 scripts；各模組用 `from .workflow import now` 各自拷一份，patch 無效。

| 編號 | 嚴重度 | 問題 | 位置 | 修法 | 驗證 |
|---|---|---|---|---|---|
| #121 | **P1（試行前）** | **正式工作區的行事曆起始是空的，且沒有年度涵蓋檢查**：實測空行事曆時 1/1 照發提醒、12/31 加 1 個工作日得 1/1、2 月第 5 工作日得 02-05（應為 02-11）→ SOP 期限不會避開國定假日 | `seed.py`（正式區空行事曆）、工作日計算 | 記錄行事曆涵蓋到哪一天，超出時警示並把期限標「行事曆未涵蓋」；上線前由行政輸入年度假日與補班 | 實測 |
| #119 | P2 | 全天假（官方範例 10/1～10/2 的 end 為 10-02T00:00）時，代理人在 10/2 10:00 已失效 → 請假最後一天整天不能代理 | `learning_sources.approval_in_period`／parse_leave | unit=DAY 時 end 延到當天 24:00 | 以官方範例格式重現，真實請假單待核實 |
| #120 | — | 與 #125（班表休息日 shift_id "0"）相同，已以假資料重現 | `attendance_schedule.fetch` | 見 #125 | 假資料重現 |
| #122 | P3 | 沒有單一時鐘入口 | 各模組 | 建 clock 模組、以屬性引用 | 讀碼 |
| #123 | P3（潛在） | `jobs.schedule` 用 `clock[11:16]`、`clock[:10]` 切字串，lease_until／next_attempt_at 用字串比較；時鐘若為 UTC 會錯（實測 09:30 台北以 UTC 表示不發提醒、租約誤判過期）；現行寫入都經 now()（+08:00），目前不觸發 | `jobs.py` | 改 datetime 比較 | 實測 |
| #124 | P3（待業主裁示） | `add_workdays` 偏移 0 不順延：事件日若是假日，期限也落在假日（報價編號、成果通知兩條規則） | 工作日計算 | 由業主決定偏移 0 是否順延到下一工作日 | 實測 |

### 六、真實 PostgreSQL（pgserver 16.2）測試與並行壓力

**全部後端測試**：SQLite 682／684、PG 681／684；3 個失敗都不是 PG 造成（2 個 test_runtime Windows 子行程問題、1 個只測 SQLite 的測試）。

**並行壓力**（60 秒；同案件 6 執行緒、不同案件 6 執行緒，加 source_sync／people_directory／worker 三個背景，皆用假 fetcher）：

| 項目 | PostgreSQL | SQLite |
|---|---|---|
| 成功寫入 | 114 | 26 |
| 409：同案件 | 79% | 85% |
| 409：不同案件 | **6%** | 87% |
| 背景同步成功 | 47/47 | people_directory 0/8、source_sync 6/15 |
| 資料遺失／同版本不同內容／死結／500 | **全部 0** | 全部 0 |
| 留言 p50／p99 | 3.3–3.7／5.6–5.9 秒 | 2.6–3.0／8.5–10.4 秒 |
| 單發一筆留言（無並行） | 172 毫秒 | 182 毫秒 |

結論：**線上用的 PostgreSQL 上，按案件分開的版本號確實有效（不同案件只有 6% 衝突），也沒有任何資料遺失**；SQLite 會忽略 FOR UPDATE，所以本機測試看到的衝突率不代表線上。`storage.save` 在 PG 上判斷變更正確（沒改就 0 條 SQL；新增留言只 1 UPDATE＋2 INSERT）。測試資料沒有可登入人員的任務，未測「完成任務」。

| 編號 | 嚴重度 | 問題 | 位置 | 修法 | 驗證 |
|---|---|---|---|---|---|
| #22 | P2（**PG 實測確認**） | 多副本同時啟動：空資料庫 6 副本 18 次中 15 次失敗（`create_all` 同時建表撞 `pg_type_typname_nsp_index`）；舊格式遷移 18 次中 14 次 IntegrityError；資料沒壞、重啟正常 | `app.py` create_app | advisory lock 必須把 `create_all` 也包進去 | PG 實測 |
| #114 | P2 | `persist_mutation` 在鎖內組出整份約 183KB 回應，且整個工作區共用一把鎖 → 12 條並行時留言 p50 3.3 秒（單發的約 20 倍），整體約每秒 2 筆寫入 | `app.py` persist_mutation | 提交後才組回應；長期以案件為單位上鎖 | PG 實測（修法未驗證） |
| #115 | P2 | 測試缺口：SQLite 忽略 FOR UPDATE，同壓力下不同案件 409 達 87%、背景同步大量 409；PG 只有 6%、背景全成功 → 現有並行測試在 SQLite 上通過的原因與 PG 不同 | 測試架構 | CI 加一組 PG 測試（可沿用 %TEMP%\cr-a2ackend\conftest.py） | PG 實測 |
| #113 | P3 | `Action.action` 無長度上限、稽核表 action 欄為 String(120)：送 200 字 action 名稱，PG 回 500 且稽核 0 筆；SQLite 回 404 並留 1 筆 | `app.py` Action、`audit.record` | action 白名單或 max_length=120；寫入前截斷 | PG 實測 |
| #116 | P3 | `ensure_workspace` 先查後建、中間沒上鎖，新租戶第一次有人同時登入時 IntegrityError（500），與 #22 同類 | `app.py` ensure_workspace | 以 insert-on-conflict 或鎖處理 | 讀碼 |

## 十六、第八輪進度（9/29 12:53 程式，Codex 修正中；**尚未部署**）

> Codex 依它的 `EXECUTION_TRACKER_20260929.md` 修改 84 個檔。**線上仍是 9/28 23:12 的舊版**（原生審批對應仍在線上），以下修正只在程式碼中、尚未上線。上方各表狀態為 12:40 時點，本節覆蓋其中有變化者。
> 測試：後端 785 項，784 過、1 敗（#187）；新測試放回舊碼會失敗 19 項＝確有「修前失敗、修後通過」證據。前端 tsc 通過。

**已修**：#161（逾時或 401 改為「結果待核實」、只查回不重送）、撤回會撤 Lark（新增撤回入口；已送出者不能本地撤回）、C66、RecoveryPage／RuntimeHealthPanel 只給管理員（正確）。

**部分修**
| # | 現況 |
|---|---|
| #159 | 已加原生審批總開關（預設關）且示範模式禁送；**仍無測試審批定義與核准人白名單** |
| #162 | 新申請不再綁來源紀錄；但範圍改算整筆檔案資料，又產生 #185 |
| #84／#160 | 只有設為 application 身分時才補 environment，否則仍空（#189） |
| #80 | 同樣資料重匯不再改變更時間；但來源與名冊同步仍推進全域版本 |
| #85（依新決策） | V4 案全標「待確認歸屬」，業務操作、排程、提醒都停，資料未刪；管理員可逐案核定給工作台（見 #190） |
| #143 | 上傳改為先驗權限再收檔；但示範身分本身是 PM，匿名仍可上傳，示範與正式仍共用資料庫與磁碟、無配額 |
| #144 | 新增 AppErrorBoundary 但只包最外層：從白屏變成整頁錯誤頁，按重新載入或返回仍會再崩；後端仍接受物件型標題 |
| #134 | 只改提示文字，規則錯誤仍回 409 |
| #44／#45 | 異地加密備份程式已寫（Fernet 分片加密、三層 hash 驗證、30 日／12 月保留正確）但**未啟用**（無金鑰與目的地）；健康頁多了異地狀態，`/api/health` 仍不看心跳、無告警 |
| #174 | 打包排除測試檔；仍以 root 執行 |

**未修**：#141／#142（@通知偽造連結與無頻率限制，實測 20 則全排進）、#145、#146、#147、#20 後端、#133／#181、#135、#137、#138、#140、#47、#7、1-d、#164、#175（期限讀新欄位，但角色設定仍填不進）、#97、#98、#100、#170、#171、#173、#129（改為卡死，見 #186）。
**變差**：#81（名冊「最後出現時間」每次同步都變 → 每 5 分鐘必推進全域版本）、B64／#99（見 #204）。

**新發現**
| # | 嚴重度 | 問題 | 位置 | 修法 | 驗證 |
|---|---|---|---|---|---|
| #185 | P2（改壞） | 審批範圍把整筆檔案資料算進去；新的「上傳自動存 Drive」會改檔案狀態欄 → 跳過申請被作廢、Lark 那張沒人撤＝孤兒審批 | `node_skip.snapshot`、`native_requests.scope_hash` | 檔案只綁 id、版本、內容雜湊；已送出的改走撤回 | 實測重現 |
| #186 | P2 | Lark 明確拒建且查不到時，申請永遠停在「結果待核實」：重送只查回、撤回讀不到原件、本地撤回被封鎖；變更申請的任務已凍結，無法恢復 | `NativeApprovalAdapter.submit` | 「確定未建成」可用同 uuid 重送，或管理員核實後有稽核地釋放 | 實測重現 |
| #187／#208 | P2（需業主裁定） | 跳過範圍把報價整個移出：報價確認範圍擴大、原本跳過的工項加回來時，已核准的跳過仍有效；**全套唯一紅燈**（兩份測試互相矛盾） | `node_skip.snapshot` | 保留報價的範圍、工項、數量欄，只排除成本與時間戳；請業主裁定語意 | 實測 |
| #189 | P2 | 未設 application 身分時 environment 仍空、畫面顯示「正式」；管理員核定某案給工作台後，財務可站內投票完成、跳過核准人在職核實 | `workspace_environment.normalize_environment` | `lark-` 工作區缺值一律當正式，或拒絕載入 | 實測重現 |
| #203 | P2 | 異地上傳失敗一次後永久「結果未知」、無核對工具；例外在本機清理前拋出 → 30／12 本機清理停擺、磁碟一直長 | `backup_offsite.replicate`、`backup_schedule.tick` | 清理放 finally、唯讀核對指令、告警 | 實驗確認 |
| #204 | P2 | 每 60 秒重算兩份備份全檔 SHA、換 token、列 Drive；每小時整份重新下載 | 同上 | 只對新檔複製；重驗與清理一天一次 | 實驗確認 |
| #205 | P2 | 本機 .offsite 留住所有未到期加密分片，備份卷約 2.3 倍；失敗 bundle 永不清 | 同上 | 遠端驗證後刪本機分片 | 讀碼 |
| #206 | P2 | 異地副本與正式系統共用同一個 Lark app 憑證且有 DELETE 權限 → 憑證外洩或誤刪可一次抹掉所有異地備份；「資料夾已核權限」只是自填旗標 | `backup_offsite` | 只寫的獨立身分或有 object lock 的儲存 | 讀碼 |
| #207 | P2 | 依賴硬連結；卷不支援時每次失敗並觸發 #203 | `exclusive`／`decrypt_bundle` | O_EXCL＋rename 後備 | 實驗確認 |
| #195 | P2 | Input 登錄送出前就標「已送出」，失敗後欄位永久鎖住；前端上限 2 萬字、後端 50KB（2 萬中文字＝60KB 必 422）；正式區目前沒有能用的 Input 路徑 | `InputRegistration.tsx` submit | 4xx 解鎖＋放棄重填；前端改算 bytes | 後端實測 |
| #188 | P3 | Lark 拒絕撤回時錯誤被吞、標「已嘗試」、之後永遠不能再撤；對已核准者按撤回會暫時讓它失效 | `NativeApprovalAdapter.cancel` | 分類錯誤、可重試 | 讀碼 |
| #190／#197 | P3 | 每個新案（含之後同步進來的）都要管理員手動核定，切換當天可能卡住；也能把舊案翻成工作台執行、無防呆；PM 只看到「暫不派工」不知道找誰 | `case_cutover` | 新案預設工作台或提示找管理員 | 讀碼 |
| #191 | P3 | 名冊 15 分鐘時效＝3 個同步週期，同步中斷 15 分鐘除復原管理員外全員被拒、背景停止外送 | `production_access` | 加監控告警 | 讀碼 |
| #196 | P3 | 案件執行設定的下拉值切換案件時沿用前一案，管理員可能核定錯 | `ProjectExecution.tsx` | 加 `key={p.id}` | 讀碼 |
| #209／#210 | P3 | 沒測「上傳真的失敗」；cryptography 要求 ≥46 但以 41 測；異地還原需手動下載全部分片、無工具 | 備份 | — | — |

**決策差異（Codex 依你在它那邊的新決定；待你確認以哪邊為準）**：全公司同時切換（原：試行 1 位 PM、3～5 新案）；財務走 Lark、PM＋行政（原 Q2：試行不含財務）；V4 案全部待管理員核定歸屬（原 Q9：只管新案）；Q3 定為一般節點工作台確認、財務／變更／展延／跳過走 Lark；Q1 擴為 V4＋Lark 報價總表。

## 十七、第九輪進度（9/29 17:53 程式；線上部署 `6abb7a9c…`）

> Codex 依 `EXECUTION_TRACKER_20260929.md` 持續修改；線上已部署新版（Codex 自述：原生審批送件、異地備份皆**未啟用**；環境設定 30 項整包套用）。本節覆蓋第十六節中有變化者。
> 測試：後端 **906 項，905 過、1 敗**（#211；Codex 自述 894 全過，於 17:53 版重現不出）。前端 tsc 本輪因 C 槽空間不足未能執行。

**已修**：#187／#208（報價範圍語意兩份測試已統一：舊碼 13 敗、新碼 32 過；語意仍待業主裁定）、#196（案件執行設定加 key）、Input 空表讀取格式。
**正確（新功能核對）**：
- **Input 寫回的正式／測試區隔成立**：測試寫入需 Base 與表都「伺服器設定＝工作區設定」；排除寫死的 4 個正式 Base（含 v3 `Sdw1…`、薪水 `VwAs…`）與正式 Input Base；欄位對應依模式鎖定；外送前重驗並比對遠端 9 欄名稱型別；冪等（request_id＋內容雜湊、client_token、先查後寫、寫後讀回、未知只查回）。
- **公司管理帳號 jekai 的綁定**：以伺服器設定的 open_id＋app＋tenant 精確比對，另需 OAuth 回呼證據、manager、在職、未撤權；7 個情境實驗（偽造證據、其他 manager、缺證據）都只能進維修模式，無法冒用。
- **SOP 契約模組**：資料全部取自 Meegle 模板 334662 v137 與 566082 v2（未直接引用 PDF）；預設範本中「條件適用」任務為 0 項，目前不會擋正常操作；關鍵規則有測試鎖住（5 組變異都變紅）。

**部分修**：#159（送審旗標預設關；仍無測試審批定義與核准人白名單）、#195（加 bytes 預檢、422 解鎖；409／403／5xx 後仍鎖、無「放棄重填」）、#180（新增執行中聯繫任務，但 PM 節點任務仍與 PDF 不符）。
**未修**：#141、#142、#143（示範站仍與正式共用服務與資料庫）、#144 後端、#145、#146、#147、#20、#185、#186、#188、#164、#189／#84／#165、#190／#197、#80、#81、#47、#7、#175、#176、#177、#181、#182、#183、#97（仍無獨立測試服務；測試區是同服務內的工作區且已真實寫入 Lark Drive）。1-d 仍待覆驗（新 SOP 合併會跳過已完成節點，未新增打回路徑）。
**撤回**：#184 的「完工確認單供專案經理簽核」與內外業 PDF 一致，撤回該半條。

**新發現**
| # | 嚴重度 | 問題 | 位置 | 修法 | 驗證 |
|---|---|---|---|---|---|
| #221 | **P1** | 效能退化：`policy.upgrade` 對每個節點都重算一次新版 `template()`（每次約 1.5 毫秒）→ 100 案 1.17 秒、300 案 3.95 秒；每次讀狀態、每個操作、worker 都會呼叫 | `policy.upgrade` | 開頭算一次；只在節點缺 requirements 時才補（改後 300 案 0.06 秒） | 實測 |
| #212 | P2 | 報價範圍用欄名白名單：不在白名單的欄位改了，跳過不會失效；整筆都是未知欄名時被當「成本鏡像」略過（失效時放行）；「此報價之合約工項明細」「合約工作項目」都不在白名單 | `approval_scope.quote_work_scope` | 依欄位 ID 排除成本與時間欄，其餘一律納入 | 讀碼＋目錄比對 |
| #213 | P2（待業主裁定） | jekai 公司管理授權同時給 normal 權限與 `business_admitted` → 可當原生審批核准人或申請人、登錄變更線，並繼承 manager 全部業務特權（一人核准交付），與 Q4「管理員不自動有業務特權」衝突 | `production_access`、`operations.py` | grant 加範圍（只管理，或明列業務角色） | 讀碼＋實驗 |
| #222 | P2 | 條件適用任務一旦啟用就卡死：沒有任何地方能寫入「適用性決定」，但 sop_draft 仍接受帶條件的任務；一發布新案節點永遠無法完成（有整合測試刻意鎖住此行為） | `sop_contracts.applicability`、`operations.sop_draft` | 入口做好前拒收帶條件的任務定義 | 讀碼 |
| #223 | P2 | 下包判斷順序與接案 PDF 衝突：PDF 先判斷有無下包需求才報價，契約把這項放在較後的 PM 節點（必做），依賴它的「下包報價收件」反而在前面的報價節點；完成也不寫入適用性決定 | `sop_contracts.DEFAULTS` | 移到報價節點並作為適用性決定來源 | 讀碼＋PDF |
| #230 | P2 | Input 登錄每筆整表掃兩次、上限 200 頁：超過 2 萬筆後送出與查回全擋；筆數多時可能撞 API 頻率限制 | `input_registration._pages`／`_find` | 用 records search 以登錄識別篩選 | 讀碼 |
| #211 | P3 | 全套唯一紅燈：staging 新增必備檔 `sop_source_contracts.json`，測試沒補 | `test_runtime` | 測試補檔 | 實測 |
| #229 | P3 | Input 送出逾時且遠端確定沒建成時永遠「待核實」；改新 request_id 重送可能重複登錄 | `input_registration.reconcile` | 管理員確認未建成後沿用原計畫重送 | 讀碼 |
| #231 | P3 | 建 Input Base 腳本防重只靠本機 `.runtime` 檔，未先查遠端同名 Base | `create_input_base_once.py` | 建立前查遠端 | 讀碼 |
| #232 | P3 | 正式分支只排除寫死的 4 個正式 Base，未排除設定中的 V4／報價 token（有 9 欄比對擋住） | `connection_policy` | 補排除 | 讀碼 |
| #233 | P3 | 隔離模式仍保留舊式覆寫儲存格路徑，與「只追加」不符（限測試表） | `jobs.py` | 移除 | 讀碼 |
| #234 | P3 | 觀測計畫與雲端驗收紀錄對應的部署／bundle 與最新不符；24 小時觀測尚未開始 | 文件 | 更新文件 | 讀碼 |

> 維運註記：9/29 審查過程 C 槽一度只剩約 450MB（審查副本約 2.4GB 已清除，現約 2.9GB 可用；C 槽整體仍 99% 滿）。之後審查副本改放 D 槽。

## 第十輪（9/29 17:53→19:53，每小時比對）

- 變更：新增 `sop_topology.py`（SOP 流程拓撲的純函式庫，**尚未接入執行流程**，不影響現行運作）與 28 項語意測試；`attendance_service` 改為名冊身分核實後才對應班表（`roster_identity_verified`，屬加強）；`deploy_prepare` 打包後自動做 smoke 驗證、失敗即中止（新增 `verify_stage_package.py`）；新增員工 OAuth 准入驗收測試。
- 追蹤項：本輪**沒有修到**清單上的安全問題與孤兒審批項目；#211（staging 測試缺 `sop_source_contracts.json`）仍紅。
- 測試（D 槽副本）：955 過、2 敗——#211，以及 `test_stage_package` 因副本未含 repo 根目錄 `.dockerignore` 等檔案而失敗（審查環境造成，非程式缺陷）。
- 無新發現、無需業主決定事項，本輪不發 Lark。

## 第十一輪（9/29 19:53→20:53，每小時比對）

- 變更：新增原生審批「隔離 QA 傳輸驗收」工具（`native_qa.py`、`scripts/native_qa_runner.py`）：只接受名稱含 QA／驗收的專用審批定義並拒用正式代碼、參與者白名單、授權紀錄需有到期時間、必須明確 `--allow-create` 才會真的送出、不能代投票、同一 UUID 最多送一次、QA 身分與正式工作區隔離。**這等於補上 #159 缺的「測試用審批與白名單」，但做成獨立工具；正式送審路徑本身未改**（仍無核准人白名單，送審旗標預設關）。
- 新增管理員唯讀的審批定義核對端點與畫面（`/api/native-approvals/definitions/verify`、`NativeDefinitionPanel`）：限正式工作區、manager、應用身分與租戶白名單，僅讀取。
- 新增異地備份一次性驗收腳本（`scripts/backup_offsite_acceptance.py`）與啟用手冊：預設只做本機檢查，`--execute` 才上傳並還原到**空的**演練庫；尚未執行。手冊註明**本機備份 volume 存明文 ZIP**（只有異地副本加密）——建議本機備份也加密或限制 volume 存取；#206（異地與正式共用有刪除權限的憑證）未改。
- 另：班表主體閘門、瀏覽器輸出隱私測試、Attendance 身分小修。
- 追蹤項：清單上的安全問題（#141～#147、#20、#143）、孤兒審批（#185、#186、#188）、環境設定（#189）、#80／#81、#47、#7、#175、#181、#211 本輪都沒有變動。
- 測試：完整後端測試在背景執行時，因**系統記憶體不足**被 Claude Code 中止，本輪沒有測試數字（C 槽亦僅約 1.5GB）。
- 無新的嚴重發現、無需業主決定事項，本輪不發 Lark。
