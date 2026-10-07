# 效能深度分析與分階段計畫（2026-10-07）

> 範圍：唯讀分析。未改程式、未碰正式 DB / Lark / Zeabur / Linear。
> 量測來源：本機 SQLite + `backend/perf_fixture.py`（319 案、7,018 工項、33,592 筆 business_records，回應 14.08 MB），
> 以 `TestClient` 走完整中介層（含 gzip）。腳本為一次性 `/tmp/*_yx.py`，不入庫。
> **標記**：【量測】= 本機實測；【估計】= 由量測推算；【假設】= 尚未驗證，需要 Phase 0 儀表。

---

## 0. 結論（先看這裡）

1. **本機只花 ~0.47 s，staging 卻 10–14 s。這個 20–30 倍落差不能由本機量測解釋。**
   本機純 CPU 部分（SQLite + Python + gzip）=【量測】474 ms（identity）/ 516 ms（gzip）。
   staging 差距可能來自：PostgreSQL 與 app 之間傳 ~19 MB JSON 文字（`JSON` 欄、非 JSONB）、
   Zeabur 小型 vCPU、live-read `ensure()`、瀏覽器端下載＋`JSON.parse` 10 MB＋React 整頁重繪。
   **這些全是【假設】。Phase 0 必須先加 `Server-Timing` 才能排名真正瓶頸。**
2. 不論 staging 的倍數是多少，**「每個請求都載入並複製整個 workspace」是共同根因**，
   而且連 `/api/session`（只要 users）與 `/api/projects?limit=10`（只回 10 筆 7 欄位）都走全量載入。
3. **寫入路徑更糟**：一次 `comment_add` 本機【量測】≈1.6 s，且回傳整個 14 MB workspace。
4. 業主四個想法：(1) 方向對但不是最大塊；(2) 對，但要設計「時間相依」與「每人」的數字；
   (3) 對，但前提是先有可查詢的欄位，目前沒有；(4) 對，且是風險最低、收益最大的第一步。
   詳見 §4。

---

## 1. 資料如何儲存（含 file:line）

### 1.1 Schema
| 表 | 內容 | 位置 |
|---|---|---|
| `workspaces` | 一個 workspace 一列：`id`, `version`(整數樂觀鎖), `data` JSON（僅剩根層中繼資料；通常 ~320 bytes） | `backend/models.py:7-9` |
| `business_records` | **每個實體一列**，PK=`(workspace_id, kind, entity_id)`，另有 `parent_id`(單欄索引)、`ordinal`、`data` JSON | `backend/storage.py:13-21` |
| `company_people` | 人員檔（lark 模式用，覆蓋 workspace users） | `backend/storage.py:22-26` |
| `receipts`, `auth_sessions`, `source_caches` | 冪等回執、登入、來源快取 | `backend/models.py:10-18` |
| `action_audit` | 唯一有複合索引的表 `(workspace_id, created_at, id)` | `backend/models.py:19-27` |

- `kind` 共 27 種頂層集合（`COLLECTIONS`, `storage.py:10`）＋ 專案子層 `nodes / tasks / review_cycles / project_{files,comments,daily_reports,evidence,finance_versions,payment_batches,confirmation_issues,delivery_batches,quote_reviews}`（`storage.py:11, 40-50`）。
- 所以「workspace」是**列式**（`storage_schema==2`），不是單一 JSON blob；但**每一列的業務欄位仍是 JSON 字串**（`Column(JSON)`），
  **沒有任何可查詢的欄位**（status、pm_id、due_date、code 都在 JSON 內）。
- 索引現況：PK 前綴 `(workspace_id, kind)` 可用；`parent_id` 單欄索引；`ORDER BY ordinal` 無索引；
  `Base.metadata.create_all` 不會升級既有表（`app.py:121`、`scripts/migrate_audit_index.py:8`），**新增索引／表要走獨立 migration 腳本**（已有範本）。
- 【量測】DB 檔 19.5 MB；各 kind 資料量：tasks 7,018 列 4.66 MB、project_daily_reports 9,000 列 2.74 MB、events 7,916 列 1.95 MB、nodes 2,871 列 0.83 MB、files 1.5k 列 0.58 MB、projects 319 列 0.26 MB（headers）、其餘皆 <0.5 MB。
- 每次寫入的整併邏輯：`storage.save`（`storage.py:29-114`）把整個 state 攤平、與 DB 全部既有列逐一比對，只更新差異列；
  已算出 `changed_projects`（`:67-96`）並遞增 `concurrency_version`（`:93-97`）——**這是「更新時維護計數」的天然掛鉤點**。

### 1.2 載入路徑
- `storage.load`（`:171-183`）：一次 `SELECT kind,parent_id,data ... WHERE workspace_id ORDER BY ordinal`（全表）→ 在 Python 以 dict 組回巢狀結構。
- `storage.load_partial`（`:116-169`，perf-B1）：唯讀，可只取指定 collections / project_ids / project_children。**已存在但尚未被任何端點使用**（僅 `identity()` demo 模式 `app.py:~290` 取 users）。
- `app.py::load`（`:208-228`）再包一層：`upgrade()` → `normalize_environment` → `initialize_execution_system` → lark 模式合併 `PersonRow`。

### 1.3 端點與前端使用
| 端點 | 實作 | 載入方式 | 回傳 |
|---|---|---|---|
| `GET /api/workspace` | `app.py:400-410` | `load()` 全量 → `public_ws()` | 全量 14 MB |
| `public_ws` | `app.py:302-319` | `public_copy`(整份 deepcopy) → `filter_visible_cases` → `upgrade` → **對每個專案算 `project_summary`** → `project_execution_view` → `filter_private_workspace` | — |
| `GET /api/session` | `app.py:365-379` | **`load()` 全量**，只用 `['users']` | 9 KB |
| `GET /api/projects` | `app.py:421-428` | **`load()` 全量**，Python 過濾/排序/切片 | `limit=10` → 1.8 KB |
| `GET /api/company-dashboard` | `app.py:412-419` | `load()`+`public_ws()` 全量，再 `overview()` 聚合分頁 | 24 KB |
| `GET /api/daily-reports` | `app.py:430-445` | `load()` 全量＋filter | 14 KB |
| `GET /api/audit` | `app.py:476+` | keyset 分頁（已做對） | 小 |
| `POST /api/actions` | `app.py:520+` → `persist_mutation` `:320-358` | `SELECT … FOR UPDATE` + 全量 `load` + 全量 `storage.save` 比對 + **回傳 `public_ws` 全量** | 14 MB |
| 中介層 | `GZipMiddleware(minimum_size=1000, level=5)` `app.py:157`；`/api` 一律 `Cache-Control: no-store` `app.py:~187`；**後端尚未發 ETag** | | |

- 前端 `scope=shell` 已接好但**後端未實作**：`App.tsx:113-114` 讀 `session.features?.workspace_shell`，
  而 `/api/session` 不回 `features`（grep 後端無 `workspace_shell`/`scope` 處理，僅 `test_perf_budget.py:48` 傳入設定）。`api.ts:21-34` 已支援 ETag/304 快取（`etag:true`）。
- 前端目前**單一 `Workspace` 物件承載所有畫面**；`refreshWorkspace`（`App.tsx:108-118`）= `/api/session` + `/api/workspace`；每次 mutation 回傳整份 workspace 並 `acceptWorkspace`（`:100`）。

---

## 2. 量測（本機 SQLite fixture，319 案）

### 2.1 各端點（p50，5 次，gzip）【量測】
| 端點 | p50 | 回應大小 | 備註 |
|---|---|---|---|
| `GET /api/workspace` | **474 ms** | 14.08 MB raw / **1.09 MB gzip** | 16 次 SQL、SQL 約 19 ms |
| `GET /api/session` | 102 ms | 9 KB | 其中 92 ms 是無謂的全量 `storage.load` |
| `GET /api/projects?limit=10` | 114 ms | 1.8 KB | 88 ms 是全量 load；回 10 筆 |
| `GET /api/projects?limit=30` | 119 ms | 5.4 KB | |
| `GET /api/company-dashboard?limit=30` | 408 ms | 24 KB | 全量 `public_ws` 後只回 24 KB |
| `GET /api/daily-reports?limit=50` | 259 ms | 14 KB | |
| `POST /api/actions` (comment_add) | **≈1,600 ms**（1565–1629） | 回 **14.08 MB** | 全量 load + 全量 save 比對 + 全量 public_ws |

### 2.2 `/api/workspace` 分階段（ms/請求，包含式、彼此重疊，不可直接相加）【量測】
| 階段 | ms | 佔比 |
|---|---|---|
| `filter_private_workspace` | 122 | 26 % |
| `project_summary` ×319（`policy_summary`，1.75 MB 輸出） | 92 | 19 % |
| `storage.load`（SQL 取 33.5k 列＋JSON decode＋組樹） | 90 | 19 % |
| `public_copy`（整份 deepcopy） | 68 | 14 % |
| `policy.upgrade` | 9 | 2 % |
| 其餘：Starlette `json.dumps`≈28 + gzip(level5)≈46 + 雜項 | ~90 | ~19 % |
| 純 SQL 時間（SQLAlchemy event） | 19 | 4 % |
| 純 `SELECT` 取字串（無 decode） | 29 | 6 % |
| 用戶端等效 `json.loads` 14 MB | 43 | （瀏覽器端另加 React 重繪【假設】） |

**讀法**：
- DB 查詢本身（19–29 ms）只佔 4–6 %；`load`（含 decode＋組樹）約 19 %。**「從 DB 一列一列讀」不是本機主因**；主因是「讀完之後對全部資料做的 Python 工作」（public_copy＋filter＋summary ≈ 60 %）加上「輸出巨大」。
- 14 MB → gzip 1.09 MB（壓縮比 13:1）。傳輸不是頻寬問題，但**14 MB 必須在記憶體建立、序列化、壓縮、解析**。
- 回應組成（【量測】）：`projects` 13.4 MB（其中 nodes/tasks ≈ 27 KB／案 ×319 ≈ 8.6 MB、daily_reports ≈ 8.9 KB／案、files/comments 其餘）、`events` 1.96 MB、`policy_summary` 1.75 MB、work_schedules 0.43 MB、contract_items 0.37 MB。

### 2.3 局部載入潛力（`load_partial`，【量測】）
| 讀取 | ms | 大小 |
|---|---|---|
| users only | 1.4 | 11 KB |
| project headers（319） | 2.4 | 329 KB |
| 1 個專案完整樹（nodes+tasks） | 1.8 | 18 KB |
| 1 個專案＋所有子清單 | 1.9 | 29 KB |
| 全量 `storage.load` | ~90 | 14 MB |

→ 局部載入比全量快 **40–60 倍**；`/api/session`、`/api/projects` 光換成它就可由 ~100 ms 降到個位數～十幾 ms。

### 2.4 SQLite 上的 JSON 欄過濾（【量測】）
`json_extract(data,'$.status')` 對 319 筆 projects 列 0.3 ms —— 小資料量下 JSON 查詢可行，
但 PostgreSQL（`JSON` 型別）語法/索引完全不同（見 §6），**不建議把「分頁/排序」建立在 JSON-path 上**。

### 2.5 沒有量到的（誠實清單）
- PostgreSQL 的實際讀取、網路往返、`JSON`→Python decode 時間。
- Zeabur 容器 CPU 與本機 M 系列晶片的倍數差。
- 瀏覽器端：下載 1 MB gzip、`JSON.parse` 10–14 MB、React 全頁 reconcile、`allTasks()` 等全量衍生計算。
- live-read `coordinator.ensure()`（`app.py:403-404`）是否在 staging 上阻塞。
- `scripts/benchmark_workspace.py` 需要私有備份（`.runtime`），本輪依規定未使用。

---

## 3. 前端各畫面需要的最小資料

> 依 `App.tsx` / `Operations.tsx` 等對 `c.w.*` 的使用盤點。「現況」=目前一律由全量 workspace 供應。

| 畫面 / 元件 | 實際需要 | 現況 | 建議來源 |
|---|---|---|---|
| App 外框（側欄徽章、頂欄、逾期數） `App.tsx:130` | 4 個整數 `counts{approvals_pending, daily_unmatched, my_overdue_tasks, my_active_tasks}`、user、environment、version、freshness | 掃全部 task 計算 | shell |
| 儀表板 Dashboard（`App.tsx:~170-182`） | 計數、最近 20 筆 events、「案件進度」前 N 案＋進度整數 | 全量 | shell ＋ `/api/events?limit=20` |
| 案件總覽 Projects（`:187`） | 每案：id/code/name/client/pm/status/priority/due/case_type/execution_status/progress{completed,total}/overdue_tasks；兩個計數頁籤 | 前端全量過濾／排序 | `/api/projects`（伺服器分頁＋篩選＋排序＋facet 計數） |
| 我的工作 MyWork（`:190`） | 與我相關的 task（owner/collab）＋所屬 project/node 名稱；status 篩選 | `allTasks(w)` 全量展開 | `/api/my-work?scope=mine&status=&offset&limit` |
| 案件詳情 Project（`:204+`）各頁籤 | 單一專案完整樹（nodes/tasks/review_cycles）、其 approvals、files、comments、daily_reports；`policy_summary` 僅此案 | 全量 | `/api/projects/{id}`（`load_partial(project_ids=[id])`）＋分頁籤子資源 |
| ‧日報 `DailyRecords.tsx` | 已用 `/api/daily-reports` 分頁；回退用 `w.daily_unmatched` | 半成品 | 維持分頁端點；去掉回退全量 |
| ‧操作紀錄 `AuditTrail.tsx` | 已用 `/api/audit` keyset 分頁 | ✅ | 不動 |
| 核准 Approvals（`ApprovalList :310`） | `approvals`（可依狀態/案件分頁）、`approval_connection` | 全量 | `/api/approvals?status=&project_id=&offset&limit` |
| 排程 / 出勤（`AttendanceWorkSchedules`, `Deadlines`） | `work_schedules`（人×日）、`calendar` | 全量（1,441 列 0.43 MB） | `/api/work-schedules?user=&from=&to=` |
| 資料來源 Sources（`:338`） | 已自行 `fetch /api/sources` | ✅ | 不動 |
| 公司駕駛艙 CompanyCockpit | 已用 `/api/company-dashboard`（已分頁），但**後端內部仍全量算** | 後端慢 | 改讀 `project_index`＋彙總表 |
| 管理 Admin / 例行 Routines（`Operations.tsx`） | `users`、`settings`、`sop_templates`、`delegations`、`calendar`、`file_categories`、`work_schedules` | 全量 | 各分頁各自 lazy 端點（低頻，晚做） |
| ProjectReadiness / 契約、報價 | 單案 `contract_items / source_quotes / source_confirmations` | 全量 | 併入案件詳情子資源 |
| MentionInbox | 與我相關的留言（需跨案） | 全量 | `/api/mentions?limit` |
| 全域：`OwnerSelect`, `nameOf(w, id)` | `users`（65 筆 11 KB） | 全量 | shell 內含 users（可接受） |

---

## 4. 業主四個想法逐一評估

| # | 想法 | 判定 | 依據與修正 |
|---|---|---|---|
| 1 | 慢是因為每次從 DB 載入每個 job 的 row | **部分對（約 1/5）** | 「每次載入全部」確實是結構性問題（連 `/api/session` 都載入 33k 列）。但本機 SQL 只佔 4–6 %，`load` 含 decode 約 19 %。真正佔大頭的是載入後的 `public_copy`／`filter_private_workspace`／`project_summary`（~60 %）與輸出大小。**PostgreSQL 上 DB 部分可能較大【假設】**，要靠 Phase 0 驗證。結論：不是「讀 DB 慢」，而是「讀了不需要的全部，然後全部再處理一遍」。 |
| 2 | 計數/徽章用儲存的整數（寫入時維護或每幾分鐘更新） | **對，且是核心** | 兩個陷阱：①「逾期」隨日期自然變化，不能只靠寫入觸發 → 存**到期日分桶**或用 SQL 即時 `COUNT`（有索引後 <1 ms），不存「逾期數」本身；②「我的」數字是每人不同，且受 `filter_private_workspace` 可見性影響 → 存**每專案**聚合＋輕量 `task_index`，查詢時依身分 `SUM`。寫入時維護（同交易）＋每日／每 N 分鐘 reconcile 比較穩，只靠定時刷新會讓使用者剛完成工項卻看到舊數字。 |
| 3 | 真正伺服器端分頁，第 1 頁 10 筆只載入 10 筆 | **對，但目前做不到** | 現在 `/api/projects` 已「回」10 筆，但先全量載入再切片（114 ms，其中 88 ms 浪費）。要「只載入 10 筆」必須**可在 SQL 篩選/排序的欄位**：`status, pm_id, due_date, code, case_type, case_visibility…` 目前都埋在 JSON。解法：新增 `project_index` 實體欄位表（§5.2），不要靠 JSON-path 索引（SQLite/PostgreSQL 不相容）。另外可見性規則（`visible_project`、`filter_private_workspace`）必須先下推到 SQL，否則 `total` 會洩漏／錯誤。 |
| 4 | 依畫面延遲載入 | **對，風險最低、收益最大** | `load_partial` 已就緒（單案樹 1.8 ms）。優先順序：shell → 案件詳情 → 清單分頁 → 次要頁籤。需配合前端以 `useViewData`（已存在 `viewData.ts`）逐頁請求，並處理「mutation 後只更新受影響案」。 |

**補充兩個業主沒提到、但實測影響很大的點**
- **寫入路徑 ≈1.6 s 且回傳 14 MB**：`persist_mutation` 全量 load＋全量 save 比對＋全量 `public_ws`。即使讀取變快，使用者每按一次完成/留言仍等 1.6 s（本機）。
- **`policy_summary` 在每次讀取重算 319 案（92 ms）**：它的輸入只有該案與少數 workspace 層設定，**適合寫入時算好存起來**（`storage.save` 已知哪些專案變動）。

---

## 5. 設計

### 5.1 根因排名（依實測影響）
| 排名 | 根因 | 實測影響 | 對應修法 |
|---|---|---|---|
| R1 | 每請求全量載入＋全量處理（含 `/api/session`、`/api/projects`） | 90–120 ms 基底＋最高 ~470 ms | Phase 1–3（局部載入、shell） |
| R2 | 讀取時重算 `policy_summary`／全量 `public_copy`／`filter_private_workspace` | ~280 ms（60 %） | 存好摘要；shell 不走 `public_ws` 全量 |
| R3 | 回應 14 MB（序列化＋gzip＋傳輸＋瀏覽器 parse） | ~75 ms 伺服器＋瀏覽器未量 | shell ≤150 KB；分頁；ETag/304 |
| R4 | 寫入：全量 load/save/回傳 | ≈1.6 s／次 | Phase 5 |
| R5 | 缺少可查詢欄位與索引，導致無法分頁下推 | 結構性 | Phase 2 |
| R6 | staging 未知放大（PG 傳輸、CPU、瀏覽器） | 10–14 s 中無法歸因的 ~9–13 s【假設】 | **Phase 0 儀表** |

### 5.2 資料表（新增；一律與 `storage.save` 同交易維護）
```
project_index           PK(workspace_id, project_id)
  code, name, client, pm_id, admin_id, status, execution_status, priority,
  case_type, case_visibility, source_status, execution_system,
  due_date, created_at, concurrency_version,
  nodes_total, nodes_completed, tasks_total, tasks_completed,
  tasks_open, tasks_overdue_cached?  (※僅作對帳參考，不作為顯示依據)
  summary JSON            -- 原 project_summary(ws,p) 輸出，寫入時重算
  updated_at
  INDEX (workspace_id, case_visibility, due_date, project_id)
  INDEX (workspace_id, pm_id, status)
  INDEX (workspace_id, code)

task_index              PK(workspace_id, task_id)
  project_id, node_id, owner_id, status, due_date, required, can_execute 所需欄位
  INDEX (workspace_id, owner_id, status, due_date)
  INDEX (workspace_id, project_id)

workspace_counters      PK(workspace_id, key[, subject_id])
  value INT, updated_at, source_version   -- approvals_pending, daily_unmatched ...
```
- **逾期不存整數**：以 `task_index` 上 `status IN (open) AND due_date < :as_of` 即時 `COUNT`（索引覆蓋，目標 <5 ms）。其餘不隨時間變化的計數（待核准、未配對日報、案件數）存 `workspace_counters`。
- **維護**：在 `storage.save` 末端，用既有 `changed_projects` 集合重寫對應 `project_index` / `task_index` 列；`project_summary` 於 `persist_mutation` 已有完整 `state` 時計算（成本與變動案數成正比，不再 ×319）。`sop_templates` 變動時 `storage.py:91` 已將全部專案標為變動 → 會觸發全量重算（罕見，可接受）。
- **對帳（reconcile）**：每日＋啟動時一次，重新由 `business_records` 計算並與 `project_index/task_index/counters` 比對；不一致則修復並記錄 audit；另提供 `GET /api/admin/index-health`（比對筆數與 checksum）。**讀取端以 `source_version`≠`workspaces.version` 偵測落後並退回舊路徑（feature flag）**。

### 5.3 Shell 契約 `GET /api/workspace?scope=shell`
- 回傳：`scope:'shell'`, `version`, `as_of`, `environment`, `workspace_id`, `users`(11 KB), `calendar`, `source_status`, `freshness`, `counts{approvals_pending, daily_unmatched, my_overdue_tasks, my_active_tasks}`, `projects[]` 僅「清單列」欄位（id, code, name, client, pm_id, status, execution_status, priority, due_date, case_type, source_lifecycle, progress{…}, overdue_tasks, active_tasks, concurrency_version，**不含** nodes/files/comments/daily_reports）、`approval_connection`, `file_categories`。
- **不得**包含 `events / work_schedules / contract_items / source_* / daily_unmatched / approvals` 全量清單。
- `ETag` = `sha1(workspace_id, user.id, authz_version, workspaces.version, as_of)`；`If-None-Match` 命中回 304（連載入都省）。必須含 user 與 authz_version，否則會把 A 的內容快取給 B。
- `GET /api/session` 回 `features.workspace_shell`（由 `WORKSPACE_SHELL_ENABLED` 控制，前端已接）。
- 預算：raw ≤150 KB、gzip ≤30 KB【估計：319×~400 B + 11 KB users + 其餘 ≈ 160 KB】。

### 5.4 清單端點（伺服器端分頁／篩選／排序）
- `GET /api/projects?q&status&pm_id&case_type&lifecycle&overdue=1&sort=due|name|progress&dir&offset&limit(≤100)` → 全部在 `project_index` SQL 完成；`total` 與 facet 計數（正式案件/待確認接案）由同一查詢 `COUNT … GROUP BY` 取得。`offset` 大時改 keyset（`cursor=due_date,id`）。`q` 以 `code/name/client` `ILIKE`（PG 另加 `pg_trgm` 為選配）。
- `GET /api/my-work`、`/api/approvals`、`/api/events`、`/api/work-schedules` 同模式，只回列表欄位。
- 所有端點先以**身分與可見性條件下推到 WHERE**（`case_visibility`、私有請假等），再 `LIMIT`。

### 5.5 延遲詳情端點
- `GET /api/projects/{id}` → `load_partial(project_ids=[id])`＋該案 `project_summary`（讀 `project_index.summary`）＋execution view。
- 子資源 `…/files|comments|daily-reports|approvals|quotes` 各自分頁。
- 回傳帶 `concurrency_version`，沿用現行 409 契約。

### 5.6 寫入回應瘦身
- `POST /api/actions` 增加 `?response=delta`：回 `{version, projects:[變動案完整樹], counts}`；前端 `acceptWorkspace` 改為合併。預設仍回舊格式（旗標漸進切換）。

### 5.7 回應預算（CI 斷言，沿用 `test_perf_budget.py` 風格）
| 端點 | raw 上限 | gzip 上限 | SQL 次數 |
|---|---|---|---|
| shell | 150 KB | 30 KB | ≤6 |
| `/api/projects` limit=10 | 4 KB | 1.5 KB | ≤3 |
| 案件詳情 | 120 KB | 25 KB | ≤6 |
| `/api/session` | 12 KB | 4 KB | ≤3 |

---

## 6. 分階段 issue 清單（每項一個聚焦 commit，可單獨上線）

> 每項都要：旗標預設關閉或對舊行為零影響 → 單元＋契約測試 → 更新 `test_perf_budget.py` 對應預算。
> 測試方法皆使用既有 `perf_fixture.build_scaled_workspace` 與本機 SQLite。

### Phase 0 — 先量對（不改行為）
- **P0-1 `Server-Timing` 儀表**：`/api/workspace`、`/api/session`、`/api/projects`、`/api/actions` 回 `Server-Timing: load;dur=, project;dur=, serialize;dur=`（用 `perf_counter`，環境變數開關）。
  驗收：staging 一次請求即可看到各階段毫秒；不影響 body。測試：TestClient 斷言標頭存在、值為數字。
- **P0-2 瀏覽器端量測**：`performance.mark` 記錄 `fetch→response→parse→first-render`，`?perf=1` 時 console 輸出。驗收：能分辨「網路/解析/渲染」各占多少。
- **P0-3 把本文 §2 數字存為基準報告** 並在 `test_perf_budget.py` 加入 `/api/session`、`/api/projects`、`/api/actions` 的 SQL 次數與位元組斷言（目前僅有 workspace）。
  *完成後以 staging 實測回填 §2.5 的空白，再決定 Phase 2 以後的順序。*

### Phase 1 — 低風險快贏（局部載入，無 schema 變更）
- **P1-1 `/api/session` 改用 `load_partial(collections=('users',))`**（保留 lark `PersonRow` 合併）。
  驗收：本機 102 ms → 目標 ≤15 ms；回應位元組不變。測試：與舊實作回應逐欄相等（snapshot）＋ SQL 次數 ≤3。
- **P1-2 `/api/projects` 改 `load_partial(collections=('projects',))`**（只需 header 欄位，`nodes=[]` 無妨）。
  驗收：114 ms → ≤20 ms（【估計】：headers 2.4 ms ＋ Python 篩選）；過濾/排序/total 與舊結果一致。測試：參數化 q/status/owner/offset 比對舊輸出。
- **P1-3 `/api/daily-reports` 同樣局部載入**（需 projects 子清單 daily_reports；用 `project_children=('daily_reports',)`）。
- **P1-4 `filter_private_workspace` / `public_copy` 熱點最佳化**（避免對已是 fresh decode 的資料再 deepcopy；`load()` 回傳已是新物件）。驗收：`/api/workspace` 在不改輸出的前提下 -100 ms 以上；輸出逐位元組不變。

### Phase 2 — 可查詢的索引資料（schema 變更，旗標 `INDEX_TABLES_ENABLED`）
- **P2-1 新增 `project_index`／`task_index`／`workspace_counters` 表＋獨立 migration 腳本**（仿 `scripts/migrate_audit_index.py`，`CREATE … IF NOT EXISTS`，PG 用 `CONCURRENTLY`）。驗收：SQLite、PG 皆可建；`create_all` 在舊 DB 不破壞。
- **P2-2 回填腳本 `scripts/backfill_index.py`**（讀 `business_records` → 寫索引表，可重跑、冪等、不鎖主表）。驗收：回填後 `index-health` 比對全部 0 差異。
- **P2-3 `storage.save` 同交易維護索引**（用 `changed_projects`）。驗收：對 `test_perf_budget` fixture 與既有整合測試，隨機 N 次寫入後「索引 ≡ 由 business_records 重算」（屬性測試）。**必須在 `persist_mutation` 的同一個 `sessions.begin()` 內**，失敗整體回滾。
- **P2-4 `project_summary` 寫入時計算並存入 `project_index.summary`**。驗收：與現場計算的 `policy_summary` 逐案相等。
- **P2-5 每日 reconcile 任務＋`GET /api/admin/index-health`**（僅 manager/admin）。驗收：人為刪改一列後被偵測並修復，並寫 audit。

### Phase 3 — Shell 與清單（後端 F3–F5）
- **P3-1 `GET /api/workspace?scope=shell`＋`features.workspace_shell`**（旗標關閉時行為完全不變）。驗收：§5.7 預算；`scope` 缺省仍回全量；前端既有 perf-F2 測試通過。
- **P3-2 shell 的 ETag/304**（含 user、authz_version、version、as_of）。驗收：同使用者第二次 304、body 0 bytes；換使用者或權限變更後 200；**跨使用者不得命中**（專門測試）。
- **P3-3 `/api/projects` 改走 `project_index`**（SQL 篩選/排序/`LIMIT`，facet 計數）。驗收：第 1 頁 10 筆 SQL 只回 10 列（以 SQL 日誌斷言 `LIMIT 10` 且結果列數=10）；p50 ≤25 ms；與 P1-2 結果等價（雙跑比對測試）。
- **P3-4 `/api/company-dashboard` 改讀索引**（去除 `public_ws` 全量）。驗收：408 ms → 目標 ≤60 ms；輸出等價。
- **P3-5 `/api/my-work`、`/api/approvals`、`/api/events`、`/api/work-schedules` 分頁端點**。每個端點一個 commit。

### Phase 4 — 前端 lazy（對應 F3–F5 之後）
- **P4-1 儀表板／側欄改用 shell counts**（移除 `allTasks(w)` 全量掃描，`App.tsx:130`）。
- **P4-2 案件總覽改伺服器分頁**（`Projects` 元件 `App.tsx:187` 使用 `useViewData`，篩選/排序/頁碼進 query string；facet 計數用伺服器值）。
- **P4-3 案件詳情 lazy**（`/api/projects/{id}`；頁籤子資源各自載入）。
- **P4-4 我的工作／核准／排程各自改為分頁端點**。
- 每項驗收：該畫面不再讀取 `c.w.projects[].nodes`；既有 React 測試＋新增「shell 下畫面可正常渲染」測試；`Workspace` 型別逐步縮窄。

### Phase 5 — 寫入瘦身
- **P5-1 `persist_mutation` 僅針對受影響的專案比對／寫入**（`storage.save` 增加 `scope_projects` 快路徑，只攤平並比對該案列）。驗收：`comment_add` 本機 1.6 s → 目標 ≤250 ms；寫入結果列內容與全量路徑完全相同（雙跑比對）。
- **P5-2 `?response=delta` 回應**。驗收：回應 ≤50 KB；前端以 merge 套用；409 契約不變（見 §7）。
- **P5-3 `SELECT … FOR UPDATE` 範圍**：評估只鎖 `workspaces` 列的持有時間，縮短臨界區（先量測，再決定）。

### Phase 6 — 收尾
- **P6-1 移除 `ORDER BY ordinal` 全表排序**（新增 `(workspace_id, kind, ordinal)` 索引，僅對仍需全量的路徑有益）。
- **P6-2 舊全量路徑僅保留給匯出／管理用途**，其餘呼叫端移除；旗標預設開啟。

---

## 7. 風險與對策

| 風險 | 說明 | 對策 |
|---|---|---|
| **權限／身分隔離** | `filter_private_workspace`（請假等私有資料）、`filter_visible_cases`、`public_person` 目前在 `public_ws` 後處理。改走 SQL 後若漏套用會**洩漏私有資料或總數** | 可見性條件下推到每個索引查詢的 WHERE；為每個新端點寫「manager / pm / member / 他人」矩陣測試，與舊 `public_ws` 輸出比對（雙跑）；ETag 必含 user.id + authz_version |
| **計數過期** | 索引落後於 `business_records` | 同交易維護；`source_version` 檢查退回舊路徑；每日 reconcile；`index-health` 告警；逾期用即時 COUNT，不存 |
| **並發／409 契約** | 前端用 `version`（workspace 級）與 `project_versions`（`concurrency_version`）做樂觀鎖（`persist_mutation` `app.py:~335-338`） | 索引表不得成為新的鎖或版本來源；`concurrency_version` 仍由 `storage.save` 遞增（`storage.py:93-97`）；delta 回應必須帶最新 `version` 與受影響案的 `concurrency_version`；保留現有 409 訊息與測試 |
| **PostgreSQL vs SQLite 差異** | `Column(JSON)` 在 PG 為 `json`（非 jsonb，無 GIN／無 `@>`）；`json_extract` 與 `->>` 語法不同；`CREATE INDEX CONCURRENTLY` 不能在交易內；`FOR UPDATE` 在 SQLite 無效；大小寫／排序規則（zh-TW）差異；`ILIKE` 僅 PG | 查詢欄位用**實體欄位**而非 JSON-path；migration 腳本分方言；CI 至少跑一次 PG（docker）對索引表／分頁端點的契約測試；排序加 tie-breaker `project_id`；`q` 搜尋 SQLite 用 `LIKE`、PG 用 `ILIKE`，並以測試鎖定結果 |
| **寫入放大** | 每次寫入多更新索引列 | 只更新 `changed_projects` 的列；批次 `executemany`；以 P5 的 `scope_projects` 快路徑共用同一份差異 |
| **回填期間不一致** | 回填時有寫入 | 先上維護（P2-3）再回填（P2-2）；回填用 upsert，最後 reconcile 一次 |
| **前端回歸** | `Workspace` 型別被全站引用（`c.w.projects[].nodes` 等） | 以 `scope` 旗標雙模式（已有 perf-F2）；一次只改一個畫面；移除全量依賴前先加 shell 渲染測試 |
| **ETag 與 `Cache-Control: no-store`** | 後端對 `/api` 一律 `no-store`；前端自行管理 ETag 快取 | 維持 `no-store`（避免中間代理快取私有資料），仍以手動 `If-None-Match` 驗證；不要改成可共享快取 |
| **時間相依資料** | `as_of`、逾期、`now()[:10]` 寫入 public_ws（`app.py:307`） | ETag 納入 `as_of`；逾期即時計算 |
| **旗標治理** | 多個旗標交錯 | 旗標表：`WORKSPACE_SHELL_ENABLED`、`INDEX_TABLES_ENABLED`、`PROJECTS_FROM_INDEX`、`MUTATION_DELTA`；每個 phase 文件列出預設值與回滾步驟 |

---

## 8. 前後目標

> 「本機」= 同一 fixture（319 案）、TestClient、SQLite，可在 CI 重現。「staging」= Zeabur＋PostgreSQL＋瀏覽器，**目前只有業主回報的 10–14 s，尚無分階段資料**，目標屬【估計】，須在 P0 後修正。

| 指標 | 現況 | 目標 | 依據 |
|---|---|---|---|
| 本機 `/api/workspace`（全量）p50 | 474 ms【量測】 | 保留給匯出，不設目標 | — |
| 本機 shell（首屏）p50 / p95 | — | **≤60 ms / ≤100 ms**【估計】 | headers 2.4 ms＋users 1.4 ms＋索引 COUNT＋序列化 160 KB |
| 本機 shell 位元組 | 14.08 MB / 1.09 MB gz【量測】 | **≤150 KB / ≤30 KB**【估計】 | §5.3 |
| 本機 `/api/projects?limit=10` p50 | 114 ms【量測】 | P1：**≤20 ms**；P3：**≤15 ms** | 局部載入 2.4 ms 量測；其餘估計 |
| 本機 `/api/session` p50 | 102 ms【量測】 | **≤15 ms**【估計】 | users only 1.4 ms |
| 本機 `/api/company-dashboard` p50 | 408 ms【量測】 | **≤60 ms**【估計】 | 讀索引 |
| 本機寫入 `comment_add` p50 | ≈1,600 ms【量測】 | P5：**≤250 ms**；回應 ≤50 KB | 單案比對【估計】 |
| 本機 SQL 次數（shell / 清單） | 16【量測】 | ≤6 / ≤3 | 預算測試 |
| **staging 首屏載入（點開到可操作）** p50 / p95 | 10–14 s（業主回報，單點） | **p50 ≤1.5 s／p95 ≤3 s**【估計；P0 後校正】 | 伺服器下降約 8–10×、位元組下降 ~95 %，但 PG 與瀏覽器未量，保守估 |
| **staging 案件總覽第 1 頁（10 筆）** p50 / p95 | 同首屏（全量） | **p50 ≤400 ms／p95 ≤800 ms**【估計】 | 單次小查詢＋網路往返 |
| staging 重複進入（ETag 命中） | — | **≤200 ms，body 0 B**【估計】 | 304 |

---

## 9. 建議順序（一句話）
**P0（量對）→ P1-1/P1-2（半天內可上、零 schema 風險）→ P2（索引表，旗標關）→ P3-1/P3-2（shell＋304）→ P4-1/P4-2（前端首屏與清單）→ P3-3/P3-4 → P5（寫入）。**
若 P0 顯示 staging 主要時間在**瀏覽器 parse/渲染**或**PG 傳輸**，則 P3-1＋P4-1（縮小首屏位元組）應提前到 P2 之前；若主要在 **live-read `ensure()`**，則先修這個。
