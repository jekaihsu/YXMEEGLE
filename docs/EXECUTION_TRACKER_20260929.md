# 2026-09-29 核定完整計畫執行紀錄

使用者在本對話核定完整計畫並要求 Implement the plan。最新對話優先於舊規格與第三方審查中的推測；審查中的缺陷須重現修正，不直接當成新的業務決策。

## 固定決策

- 全公司同時切換；Meegle 舊案留原系統完成，新案工作台，不匯入 Meegle 歷史。
- 案件 V4＋Lark 報價總表；普通 SOP 本地交付確認，財務／變更／展延／跳過走 Lark。
- 財務 PM＋行政；跳過 PM＋組主管；變更保留業主佐證、主管本人確認、PM＋組主管內審三線。不得代票。
- 薪資／能力 Base 禁寫，訓練考評停用。名冊僅讀核定四欄。
- 名冊 15 分鐘時效；復原管理員僅維運。正常班表決定截止時間，不用打卡或固定17時。
- 上傳自動 Drive 保存並下載核實；Input 獨立 Base 雙白名單；測試不能污染正式資料。
- 每日備份30份／每月12份、独立加密副本、PostgreSQL 還原、24小時穩定觀測及真實角色驗收才可正式切換。

## 分工與完成標準

| 工作 | 主責 | 狀態 | 證據／下一步 |
|---|---|---|---|
| 案件舊案分流與來源／日報 | demo_acceptance | 實作中 | pending/meegle/workbench，正式API與worker共同gate |
| 名冊時效／Attendance身分／同步授權 | demo_release_checks | 實作中 | 同app批次精確映射，不靠姓名 |
| 健康管理UI／少點擊／SOP映射 | finish_ui_audit | 實作中 | frontend單一owner，與A/B交換接口 |
| native安全／共用入口／上傳／備份／部署 | root | 實作中 | 先修新審查已證實風險，再接完整驗收 |
| 專用Input目的／隔離真實串接 | A＋root | 待做 | 權限與資源核實，正常路徑讀回 |
| 真實審批／通知／Drive驗收 | root＋實際角色 | 待做 | 需明確驗收表單/人員，不代核准 |
| 備份異地／PG演練／24h觀測 | root | 待做 | 不把SQLite演練或worker心跳當整體完成 |
| Apple Design獨立複核 | UI交叉審查 | 待做 | 新版手機/鍵盤/縮放/減少動態 |

最新部署進度以本文件末段為準。前端為 DT7FQyzT／Bj1srCLy；先前 6abb6d99498d5ec175a08d0d 的公開 HTTP 12 項驗收通過，不代表公司正常登入及真實寫入通過。

## 新增審查處理

發現工作區新增 ISSUES_MASTER_20260929_CLAUDE.md，納入逐项核對。優先原生審批外送開關與未知結果、工作區環境一致性、案件分流與資格、資料型別及上傳限制。與最新計畫不同的舊裁示不自動採用。

## 本輪實作與驗證

- 正式案件 pending／meegle／workbench 接管與 API／worker 門檻已實作，保留來源及既有歷史。
- 人員資料 15 分鐘新鮮度及 bootstrap 主管 recovery 維修入口已實作；維修模式不能讀業務工作區。
- Input 改專用表追加修訂；文件上傳自動排入 Drive；未知結果先查回。仍待專用目的地與真實端到端驗收。
- 原生審批加入獨立送審旗標、原申請人撤回、防重送及 v2 語意範圍；工程範圍變更會失效，無關成本刷新不使 v2 失效，v1 保留原算法。
- 完整後端 828 項通過；前端 build、27 項本機／fixture 檢查通過。這不是外部整合全數通過的證據。
- 新版新鮮雲端六表備份、SQLite 與真正 PostgreSQL 獨立 DB 還原全部逐列／附件比對通過。獨立 DB 保留，不修改正式 DB、不啟動 worker。異地加密排程仍未開通。
- Lark 0.4.2 已發布通訊錄全部成員範圍；58/58 員工 ID 真實核實成功。實測發現 Attendance 每批最多 50 人，已修並通過 34 項測試；本地 adapter 查本週 406 人日：84 ready、210 缺少唯一排班、112 彈性或未知班次，未補預設時間。待新部署與正常 sync 驗收。
- Apple Design 發現的跨案件草稿沿用 P1 已修復，獨立 reviewer 原重現路徑及另 10 項檢查通過。剩餘手機小按鈕為 P2；不得再沿用舊版草稿。
- SOP 仍有 28 個非 Start 節點未有顯式等價映射（含 2 個已核定停用的考評節點）；第二模板 566082 v2 已取得 7 節點／0 子任務／6 連線。表單讀取仍有限制，不能視為引擎完成。
- 新增 Claude artifact 參考 FWhSDShmKTejqkCoDtCKup，瀏覽器停 Cloudflare；尚未取得內容，不推論功能。

證據詳見 IDENTITY_IMPLEMENTATION_20260929.md、CASE_CUTOVER_SOURCE_PROGRESS_20260929.md、BACKUP_OFFSITE_IMPLEMENTATION_20260929.md、ATTENDANCE_READONLY_ACCEPTANCE_20260929.md、NODE_SKIP_SCOPE_REVIEW_20260929.md、NODE_SKIP_QUOTE_SCOPE_FIX_20260929.md、UI_PRODUCTION_INTEGRATION_20260929.md、APPLE_DESIGN_FINAL_REVIEW_20260929.md。

## 追加核定與目的地

- 使用者確認 `jekai` 為登入及名冊姓名；實際權威名冊無此姓名／帳號，原 recovery 行為正確。使用者已核定將目前已驗證 OAuth 帳號設為獨立公司管理帳號，精確綁 app／tenant／open_id、記授權與停用稽核，不放寬所有 bootstrap，也不寫薪資 Base。程式及正常登入驗收進行中。
- 使用者明確要求其他人也能使用。Lark 0.4.3／版本 7690834540366056986 已發布、審核通過、可用範圍「所有員工」。工作台內仍依在職及角色准入，未宣稱所有同事逐人登入驗收完成。
- 正式及隔離測試 Input Base 已分別建立，九個 text 欄位及零紀錄讀回核實；正式／測試 Base、table、field IDs 不重複。schema/config 私存 `.runtime/lark-input-cli/`，未寫測試記錄。隔離 Input 修正後本地完整後端 842 項通過，bundle DT7FQyzT；此計數尚不含後續獨立管理員修改。
- 獨立 Drive 測試與備份目錄已建立；備份連結分享關閉，但 folder 成員查詢不支援，尚未標記私密權限已完整核實，未開異地備份。見 DRIVE_DESTINATIONS_20260929.md。
- 已合併獨立管理員片段，保留全部原 19 項的 30 項完整 Zeabur env 已套用，逐值回讀相同；禁止 delta 替換。未啟用異地備份或 native 審批送件。

## 管理帳號與整合版驗收進度

- 最終整合後端 894 項通過（241.83 秒），含 SOP、正式 V4 metadata、未知適用條件阻擋、全部真實外送資格檢查、公司授權稽核隱私。
- 公司管理帳號 jekai 的精確 OAuth 綁定及環境授權已設定；首次正常 OAuth 驗收仍為 recovery，不能宣稱 normal 已通過，待新行程載入設定再驗證。
- deployment 6abb79c7b57ea4921d62c52b 雖 RUNNING，部署包缺少 sop_source_contracts.json；線上 session 曾 502。已將資料檔加入明確白名單，重新封存 .runtime/zeabur-stage-feb56049（102 檔），直接在封存目錄成功載入 template 及兩份來源契約，再部署。仍需新的 HTTP／登入驗收。
- SOP 新版在既有公司工作區僅註冊草稿候選，不覆蓋已發布範本；6 項條件式工作維持 deferred，完整拓樸與切換 baseline 尚未完成。
- 備份目錄已授權精確 jekai 管理員、連結分享關閉、對外分享關閉；其他協作者範圍及權限仍待完整讀回，不能先標記 private-root 已驗證。

### 最新真實驗收（取代上述尚待狀態）

- 補齊資源的部署 `6abb7a9cb57ea4921d62c57b` 已 RUNNING；公開 HTTP 12/12 再驗通過，前端 assets bytes 一致。
- jekai 正常 OAuth 後 access_mode=normal、manager；切回公司工作區及讀取均 HTTP200。獨立管理授權 audit 一筆，核定理由／來源／時間齊備，session 未曝私密 proof/grant。薪資 Base 未寫入。
- 隔離附件正常上傳 → 自動 worker → Lark Drive 真實保存 → 下載 hash 核實通過（64 bytes，remote_status=verified、simulated=false）。
- 隔離 Input 第一筆 revision `e54ee2c7a1a34b71933d2b43d9af2207` 在寫入前讀空表時 blocked：`Input 登錄分頁內容不完整`。保留原 revision／request_id，未宣稱成功、未盲重送。C 正核對真實空集合 shape 並修復。

### 後續完成與正在修復

- 空表修正部署 `6abb7deeb57ea4921d62c688` 已 RUNNING；唯一 runtime 差異為 input_registration.py，44 項相關測試通過。原 Input 正常 job_retry 後 succeeded，遠端 reczz28HKWfQTlRX verified=true、simulated=false，九欄回讀符合原 plan。專用測試區端到端已通；未寫正式來源／薪資。
- 正式工作區 input_base／input_table 已透過正常 admin_settings 設定為專用正式登錄目的，讀回一致；未建立正式驗收記錄。
- 封装 smoke 已新增，對 checkout 外獨立 Python／臨時 DB 檢查，修正版 stage 九項通過、舊漏檔stage正確失敗；2 項防回歸通過。
- 一般同事准入新增 12 項 HTTP 合成測試，相關 77 通過；仍須同事本人 OAuth，不能代登入或將全員可用範圍當逐人驗收。
- 正常班表同步最新實測 HTTP403：`班表身分需同一應用已核實帳號`。先前只讀 runner 篩過身分，未覆蓋正常 service 的未核實人員；已派 agent 修成保留該人 pending、不阻斷已核實同事。19:10 台灣時間名冊 profile64、revision215、最後成功19:04:35；粗略在職來源61不等於可登入人數，尚需精確 app/freshness 分類。
- 實際共同審批驗收所需 PM／組主管／行政姓名已向使用者詢問，尚待回答；未代他人核准。
- 流程條件與拓樸核心新增28測試，連既有SOP57通過，尚未接runtime；不得宣稱完整流程引擎已完成。下包PM彙整／主管確認分工不能推成新本地雙席審批，未新增此核准路由。

### 班表正常流程與名冊持續更新驗收（更新前述 403／待選人狀態）

- **2026-09-29T20:09:39+08:00**，主執行者透過正常公司 `POST /api/attendance/sync` 查詢 2026-09-28 至 2026-10-04，取得 **HTTP 200**；持久化結果 `status=pending_schedule`、`ready_count=84`、`manual_override_count=0`、`issues=4`、`sync_revision=175`。一般 service 混合身分造成整批 403 的阻斷已通過正常 API 再驗；仍有待核實班表，不宣稱所有人日均 ready。
- 正常公司名冊觀察 **45 分鐘自然背景更新**，revision **215 → 223**；精確同 app 在職名冊資格為 **58 人**。64 是儲存 profiles 數，不能稱為 64 位在職同事；全員可用與名冊資格也不等於每位同事已完成本人 OAuth。
- 第二批「歷史班表當下使用 gate」本機 **136 tests passed**，保留歷史但不以已離職、停用、app／名冊未核實或過期身分產生有效截止時間及錯誤逾期升級，demo/test 行為保留。已納入 stage **`4a810052`**，目前部署進行中，**尚未驗證 RUNNING 或實機行為**，不可與上述第一批 HTTP 200 混稱已完成。
- 使用者已委任挑選測試人，選定 **文乃毅** 僅作 QA 驗收安排；**不修改正式 role 或權限**，不代其 OAuth 登入或核准。
