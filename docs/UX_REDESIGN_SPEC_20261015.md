# YX Survey 工作台 UX 改版規格

文件識別為 `UX_REDESIGN_SPEC_20261015`。擁有人為 Vincent。本文供實作人員拆工與驗收使用，這次交付只新增文件，不修改應用、不寫入 Lark、不推送、不部署。

## 1. 查證範圍與主要判斷

研究基準為 `ava-apple/node-assignment` 的 `27cd6bac8428218589a80d6e993b5ce62879e512`。研究工作樹為 `/Users/vc/.t3/worktrees/YXMEEGLE/t3-1ce9abf1`，目前分支為 `t3/ux-redesign-spec`。文件名稱沿用委派指定的 20261015，實際查詢日期為 2026-10-14，台北時間。檔案定位均指此基準，後續改版可能使行號移動。

參考專案為 [pm-solution](https://github.com/jekaihsu/pm-solution)。`git -C /tmp/pm-ref pull` 回覆 Already up to date，HEAD 為 `60a5cbb837f898c65804b2cbfc13bb6aeda98926`。以下 `pm-ref/` 定位指 `/tmp/pm-ref/`，不是本專案內的檔案。

已用 T3 preview 的無痕頁唯讀開啟 [staging](https://yongxiang-workbench-staging.zeabur.app/)。登入頁、靜態資源及 `/api/session` 回 HTTP 200。畫面只有「登入公司工作台」「使用 Lark 登入」「重新檢查」。沒有執行登入，也沒有測得登入後首頁、設定頁或任務操作。不能將本地分支等同目前部署版本，不能宣稱重現設定頁空白。

Lark 全程使用 `lark-cli` 的 `--as user`。成功讀取表目錄、部分欄位 metadata 及有限樣本。表數與筆數是這個身分可見的查詢結果，不代表所有身分都能看到同一範圍。沒有讀取全表私人資料，沒有更新 CLI 或授權設定。

主要判斷如下。

1. 首頁改為本人受指派工作的入口。工作來自真實節點指派與任務，並保留等待前置條件的指派。不能只呈現目前可按「開始」的任務。
2. 預設首頁為 `dashboard`。目前 `App.tsx:98` 會將符合角色者導向 PM 一覽，且 `pmGlanceConfig.ts:2` 設為所有角色。改版後 PM 一覽仍保留為管理視角。
3. 來源案件、SOP 定義、實際指派、每日作業證據是四種不同資料。不要用範本任務數當作 Lark 任務數，也不要用日報筆數當作完成數。
4. 變更與展延、追蹤與檢討先關閉。保留程式與歷史，不擬定重開計畫。
5. 快取與背景更新只改善讀取。寫入仍沿用伺服器授權、版本核對、重複請求保護及遠端回讀。

實作採 Experience First 原則。使用者先找到工作與案件，診斷資訊留在需要它的面板。驗收採 Prove It Works 原則。下列數字附查詢範圍，設定頁空白保留為未重現，而不是給出假根因。

## 2. 今日資料目錄與欄位對應

### 2.1 V4 表大小

執行下列唯讀命令可重查。`records_count` 是 CLI 表目錄回傳值，不是本輪逐頁點算結果。

```sh
lark-cli base +table-list --base-token H7W6b0PFWaVF1BsgqXJj3pQ9pXb --as user
```

| 表 | table ID | records_count | 本版用途 |
| --- | --- | ---: | --- |
| 工程確認單 | tblmSQrcCs9vPQZx | 106 | 案件與確認單身份 |
| 合約明細工項 | tblobs4qPy2w9MZ6 | 573 | 商業工項與工作量 |
| 合約填報工項 | tblwQPYk3c9RvCU7 | 701 | 可填報工作項 |
| 人員名單 | tblfaCO2xPUNptQH | 67 | 名冊與指派候選 |
| 儀器費率 | tblg3Fo23T6Gos6S | 144 | 參考來源，非首頁 |
| 車輛 | tblTQv8l5ntnbwyp | 20 | 參考來源 |
| 人力成本方案 | tbl0aJddgw3u7Ldo | 18 | 限權成本參考 |
| 行政工項標準 | tblQekGHgNHRVUHM | 63 | 參考來源 |
| 外業成本單 | tbl8wRYCUCvbSoJG | 213 | 工作日期與組員 |
| 外業工作單 | tbl5zPLS0ExWNEty | 187 | 外業日報證據 |
| 內業成本單 | tblKwSDRg6WaGHYr | 201 | 內業日期與組別 |
| 內業工作單 | tblrCo8KeZiuJUNh | 348 | 內業日報證據 |
| 行政成本單 | tbl7ngrBD2jSx6Cz | 59 | 非本次核心讀取 |
| 行政工作單 | tblHsH4ocQSG08g5 | 188 | 非本次核心讀取 |
| 業務PM成本單 | tblF0siL1McvVvLC | 143 | 非本次核心讀取 |
| 顧問成本單 | tblyDYEM4QaiKPK6 | 51 | 非本次核心讀取 |
| 內業每日費用 | tbleQZfZ0EWTuthf | 1 | 參考來源 |
| 名目分類 | tblV9Jyofp9gLAmL | 9 | 參考來源 |
| 約定帳戶 | tblepBPXwx3txJTT | 36 | 非首頁，權限限制 |
| 採購單 | tblC76IUep5pZSX6 | 0 | 零筆不代表所有身分零筆 |
| 採購單-非審批 | tblTr51I9RSrOZKa | 4 | 非本次核心讀取 |
| 支出單 | tbligcwRyAGhxL2e | 1 | 非本次核心讀取 |
| 行政結算 | tblpHFaVfmgZVkoD | 0 | 非本次核心讀取 |
| 工作預排 | tblZz6Mkhv9gHrB2 | 312 | 待驗證新增來源 |
| 日報稽核控制台 | tblCEGiti083yotW | 1 | 待驗證新增來源 |
| 津貼申請 | tblbSIRYfNhN6FeS | 0 | 非本次核心讀取 |
| 津貼匯整明細 | tblbxh8QQaY6N3DL | 287 | 非本次核心讀取 |
| 津貼匯整總表 | tblC8181oxaBcT0d | 122 | 非本次核心讀取 |
| 外業組別營業額統計 | tblgFHzOvgbVRU3f | 18 | 待驗證新增來源 |
| 內勤人員營業額統計 | tblMJ8whiR9T76b7 | 260 | 待驗證新增來源 |
| 節點指派 | tblcPZPmezkyeVb7 | 9 | 核心工作來源 |
| 任務 | tblsoyGcC6K5AipF | 0 | 核心工作來源 |
| SOP 案件總覽 | tbl3jzXUO8oyfvcu | 1 | SOP 摘要與關聯 |

總數為 33 張表。不要為了首頁一次載入這 33 表。[SOURCE_MAPPING.md](SOURCE_MAPPING.md) 第六節的 2026-09-25 數量是歷史快照，今日合約兩表已不同，不能沿用舊數量作驗收。

### 2.2 畫面元素的資料字典

下表代號供逐頁矩陣引用。除 Q 外，欄位名稱均在本輪透過 `+field-list` 查證。metadata 存在不代表每筆有值，也不代表目前連接器已投影全部欄位。

| 代號 | 表與欄位 | 畫面用法與限制 |
| --- | --- | --- |
| N | 節點指派的 指派鍵、確認單編號、節點、工程確認單、案件總覽、負責人、指派人、指派方式、狀態、進度、任務、開始時間、完成時間、核准人、核准時間、退回原因 | 節點卡、我的工作、責任人與覆核。負責人是多人欄位。無截止日欄位 |
| T | 任務的 標題、內容、負責人、指派人、部門、節點指派、狀態、截止日、完成時間、建立時間 | 真實任務列、內容詳情、到期排序。負責人為單人。部門原選項含 圖報A、圖報B，不自行拆成圖資或報告 |
| S | SOP 案件總覽的 確認單編號、工程確認單、節點指派、目前節點、總節點、已完成節點、業務、PM、確認單、外業、控制、圖資、報告、計價、結算 | 案件 SOP 摘要。lookup 可能空白，核對 N 後才顯示衍生結果 |
| C | 工程確認單的 工程確認單編號、工程名稱、確認單標題、所屬案件、SourceID、狀態、啟動 SOP、合約明細（日報關聯）、合約總額、預估總成本、實際總成本、工程確認單 PDF、報價單 PDF、建立時間、資料警示、案件關聯檢核 | 案件身份與來源詳情。合約、成本權限分開。零值不自動表示已接實際成本 |
| D | 合約明細工項的 合約項次、合約工作項目、合約數量、合約單位、來源明細唯一鍵、SourceID、所屬案件、所屬成案確認單（日報關聯）、合約填報工項（日報關聯）、分項金額(原始)、分項金額(報出)、外業數量、控制數量、圖資數量、報告數量、各組預估工天 | 合約明細與商業口徑。不得把各組工作量再加成合約金額 |
| W | 合約填報工項的 工項名稱、工項類別、工項細碼、填報工項、工編號碼、來源工項識別、來源合約明細（日報關聯）、所屬案件、基準數量、標準點數、對應營業額、換算係數、計價權重 | 工作項詳情。欄位使用原名，不改造上游拼字。可顯示標準及來源缺值 |
| O | 外業工作單的 工作單號、工作日期-薪資、所屬案件、案件編號、合約工項、所屬成本單、組別、完成數量、修改後數量、營業額點數、最終營業額點數、檢核狀態、備註、附件、各項 ⚠ 警示 | 外業日報、異常與原始佐證。關聯缺失保留未配對 |
| I | 內業工作單的 工作單號、姓名、所屬案件、案件編號、所屬成本單、內業工項、本明細適用工項、計價數量、營業額點數、修改後營業額、最終營業額點數、品管檢核、檢核時間、自訂說明、附件、可能的確認單工編(若暫無確認單才需填寫) | 內業日報。日期須連成本單，不能以填報時間替代 |
| OC | 外業成本單的 工作日期、組別、組長、組員、組長帳號-津貼自動化、組員帳號-津貼自動化、檢核狀態、工作單列 | 補足日報業務日期及人員，非每人重複計點 |
| IC | 內業成本單的 工作日期、內業組別、所屬組別、組別、填報帳號、填報人、工作單列 | 內業日期與組別補值。多義關聯不任選 |
| P | 人員名單的 姓名、Lark帳號、同步_OpenID、所屬組別、職級、組長、在職、通訊錄同步時間 | 名冊與指派候選。角色與應用權限由伺服器設定，不能以職級文字代替 |
| Q | 報價 Base JoOqbggsVar0ATsVgbcjh6IIp1g 的 tblENZvYAya93Twa | 本輪未重查。工程編號、報價編號、工程名稱、案件負責人、期限等僅依 SOURCE_MAPPING 歷史與部署映射，擴充前重查 |
| L | 工作台本地流程、事件、討論、附件索引、授權、審批回執、feature flags、同步狀態 | 不是 V4 欄位。API 必須標示 local_workflow 或 native_approval，不能偽稱 Lark 原始欄位 |
| A | 出勤與出差的 Lark 原生 API | 非 Bitable 表。本輪未讀取出勤 API 或 permission scopes，沿用 peopleAttendance 的 readState，不從日報猜出勤 |

重查欄位使用 `lark-cli base +field-list --base-token <base> --table-id <table> --as user`。有限樣本使用 `+record-list --limit 1 --field-id <field>`。CLI 的 filter JSON 是 CLI 包裝格式，不能直接當作 OpenAPI search 的 body。

### 2.3 本輪樣本與直接影響

| 樣本 | 已觀測值 | 設計含義 |
| --- | --- | --- |
| C 的 recvsnzx3bjtAA | 工程確認單編號 C115264，工程名稱 新昇案-33筆地號(鑽探)，狀態 null | 顯示來源未填，不推論進行中 |
| N 的 reczz28NHQYDHxPf | 指派鍵 C115264\|業務，節點 業務，狀態 待處理，負責人 null，工程確認單關聯存在 | 此筆不是「指派給我」，不能因 PM 角色加入首頁 |
| N 的 reczz28NHQYo9MD0 | 指派鍵 C115264\|PM，狀態 未開始，負責人 null | 預設節點存在不等於已指派 |
| S 的 reczz28NHQX9rvFN | 確認單編號 C115264，目前節點 null，已完成節點字串 0，總節點字串 9 | 正規化 lookup 數字。沒有進行中節點可如實顯示「尚未開始」 |
| W 的 recvsrC9IguTm3 | 工項名稱 導線測量1/20000(2測回)，工項類別 外業，基準數量字串 50，標準點數字串 4.625 | 保留精度與單位來源，不能將點數寫成天數 |
| T | 表目錄零筆 | 沒有任務實例可驗證，不填假任務。需要未來隔離測試的真實格式樣本 |

N 只查 2 筆，`has_more=true`。不能聲稱全部 9 筆皆未指派。S 此投影 `has_more=false`。W 與 C 樣本仍有下一頁。P、O、I、OC、IC 本輪只核欄位，未逐筆驗證值或名冊資格。

## 3. 現況與 pm-solution 可採用之處

| 項目 | 本專案定位與現況 | 參考專案定位 | 目標與取捨 |
| --- | --- | --- | --- |
| 首頁 | frontend/src/DailyHome.tsx:13、78、130、147 分成接續工作、待我確認、交辦、shell 摘要。backend/home_queues.py:33 只收可證明的確認與交辦 | pm-ref/components/Overview.tsx:55 按來源獨立載入並以報告卡進入細節 | 採面板獨立狀態與可鑽取卡片。首頁呈現工作，不複製全表連線 KPI |
| 工作資料 | backend/my_work.py:42 的 FORMAL_DUE_FIELDS 為空，正式期限一律未核實。:194 先確認指派再判斷可執行 | pm-ref/components/SourcePanel.tsx:413 提供欄位排序與 aria-sort | 對齊真實 T 截止日與既有流程日期的 provenance，保留等待工作 |
| 管理視角 | backend/manager_overview.py:143 用確認單版本母體。backend/company_dashboard.py:108 計工作台任務，:129 依案號排序 | pm-ref/components/FieldReport.tsx 與 InternalReport.tsx 用異常優先、來源關聯與日期 | 來源成案數、版本數與執行任務數各自標示，不混用母體 |
| 大量讀取 | backend/sources.py:60 依 records_api 採 search 500 或 list 200，:115 做 field projection。node_assignment/lark_table.py:334 已每頁 500 | pm-ref/lib/lark.ts:421 每頁 search 500，:463 追 cursor，:365 補關聯標題 | 使用既有能力，補 panel query 與可見範圍分頁，不重寫全連接器 |
| 快取 | frontend/src/api.ts:4、28 有 ETag，:10 在 session epoch 切換清除。node_assignment/config.py:18 有讀取與名冊 TTL | pm-ref/lib/lark.ts:130 stale-while-revalidate 及 inflight 共用，:166 lastGood | 採 stale 快照與共用請求，但快取鍵必須含身分、角色、工作區與查詢 |
| 背景暖機 | 現有 live_read/coordinator 與資料集 refresh | pm-ref/lib/warm.ts:25 以 3 個 worker 暖所有 located source | 借 bounded concurrency，僅暖該使用者可見必要表，不能照搬 app 級全源快取 |
| 細節載入 | FullWorkspaceGate 位於 frontend/src/appCommon.tsx:84，部分頁仍須整包 workspace | pm-ref/components/useSource.ts:20、35 支援 enabled 及欄位投影 | 收合面板不讀，顯示時才讀，個別面板失敗不遮住全頁 |
| 頭像 | frontend/src/Avatar.tsx:6 限 HTTPS feishucdn，:22 lazy img 及錯誤回退。backend/people_directory.py:86、114 保存有效 URL | pm-ref/app/api/auth/callback/route.ts:59 取 OAuth avatar。components/AppShell.tsx:109 直接 img | 現有安全與 lazy 行為較完整，保留。補明確尺寸、cached URL 與可查來源缺失 |
| 表排序 | 來源或本地表有多種固定排序，Company 預設案號，My Work 預設 id | pm-ref/components/SourcePanel.tsx:424 數字比較與 localeCompare，EquipmentBoard.tsx:58 異常優先 | 借可理解的類型排序與異常優先，跨頁排序由 server 執行 |

pm-solution 不是本輪可驗證的真實任務首頁範本。它主要是來源報告總覽。`getSourceData` 會把一個來源讀到上限後才回傳，並非逐筆 stream。`useSource` 的漸進是各來源面板各自完成，不能宣稱它已有所有 server-side table pagination。不要移植其 demo 切換或敏感來源寬欄位讀取。

## 4. 虛構、範本與佔位資料盤點

判斷依據為 production reachable code path，不以檔名含 demo 就認定已洩漏。這次沒有登入 production workspace，故「可能曝光」是靜態風險，不是已觀測事故。

| 種類 | 定位 | 分類與 production 風險 | 規格 |
| --- | --- | --- | --- |
| 種子人員與案件 | backend/seed.py:4、5、14、18 | 明確虛構。含固定人名、案號、金額、點數、日期、輸入成果 | 保留供測試及隔離 demo，正式 API 不得 fallback 到 seed(False) |
| 種子日報、代理、事件 | backend/seed.py:26、31、34 | 虛構日報、代理期與建立事件。seed 並未預塞已核准審批 | 正式 workspace 的 source_kind=demo 需警示隔離，不能只拿掉標籤 |
| 空 workspace 初始化 | backend/app.py:257、1300、1311 | 正式 OAuth、工作區切換用 seed(True)，沒有帶種子人員與案件 | 維持空初始化。不能將所有 seed import 一律刪掉 |
| DEMO_MODE | backend/app.py:111、117、253、489、501 | 本機預設可 demo，cloud 另需 ALLOW_CLOUD_DEMO。正式身份不可切示範 | 部署檢查 DEMO_MODE=false，公開健康資訊可顯示模式但不顯示 secrets |
| 測試規模資料 | backend/perf_fixture.py:28、benchmark_company_cockpit.py:21 | benchmark 使用，environment=demo。未見 app handler import perf_fixture | 測試專用，保留，不載入 production |
| 案件母體 fixture | backend/case_universe.py:18、19、fixtures/f7_c115264.py:8、fixtures/lark/*.json | 測試與查核資料。case_universe 明確 seed users。未見 production handler 引用 | 測試專用，不能以 C115264 案號相同推論來源真實 |
| 固定 SOP 工作定義 | backend/policy.py:20、52、79 | 正式可達的流程定義，不是 Lark 任務實例 | 定義頁可顯示。首頁任務計數要排除未建立實例且未明確指派的定義 |
| 範本實體化 | backend/sources.py:183、195、199，backend/sop_contracts.py:157、212 | 正式來源案件可建立 new_task。已有「固定 SOP 範本」描述，但列表與 KPI 可能仍算成工作 | 新增 origin 與 assignment_state，保留 local SOP 歷史。不能聲稱每筆都是 T 的 record |
| 範本版號與完整性 | backend/policy.py:64、67 | published 與 partial_inventory 同時存在，不能當完整 Meegle 重現 | SOP 頁顯示核定版號、部分映射、待驗證範圍 |
| 營運同步 mock | backend/ops_sync/routes.py:112、146，flow.py:21、25，frontend/src/OpsFlowPanel.tsx:20 | FLAG 開啟後 routes 的 access 沒有明確禁止正式環境。回傳 synthetic 名冊、mock approvers 與日期。settings 無條件掛面板 | production 明確阻擋 mock routes 與面板。保留本機測試。不能僅依 live=false 隱藏假資料 |
| mock flags | backend/ops_sync/flags.py:23、backend/app.py:1389 | 預設關閉，live writes 硬關閉。環境錯配仍可把 mock UI 掛上正式工作區 | 正式不顯示 mock_ui。測試具名隔離，server gate 同步 |
| 模擬審批 | backend/workflow.py:219、225、230，node_skip.py:150、170，frontend/src/App.tsx:152 | 受 demo、simulated 或 test 保護。正式不可使用模擬核准代替原生回執 | 保留測試，但現階段 change、extension 再套 disabled gate |
| 模擬通知、Drive、Input 回執 | backend/jobs.py:295、313、335、357，remote_policy.py:28 | demo/test adapter 生成 simulated message_id、file_token，非已發送的證明 | 顯示「模擬」，正式作業狀態不能接受 simulated=true 為成功 |
| mentions 通知 | backend/mention_notifications.py:47、55 | 正式需核實 identity，與舊 fake Bell 是不同功能 | 保留真實 mention。只有真實未讀來源才能有未讀數 |
| header Bell | frontend/src/AppShell.tsx:42 | 圖示只導向 approvals 並檢查 pending，不是通知 inbox。不是 fake 紀錄，但語意誤導 | 兩功能停用時移除，未讀通知有正式來源才另建入口 |
| demo 標籤與角色切換 | frontend/src/AppShell.tsx:41、42，App.tsx:102、112、176 | 正式與測試標籤部分共用 demo-tag CSS。類名不是假資料來源 | demo 標示只在 demo 環境，移出 topbar。保留身份與環境真相 |
| 安全字首頭像 | frontend/src/Avatar.tsx:19、22 | 姓名首字是 UI fallback，沒有捏造照片 | 保留，以「無頭像」語意供輔助科技，姓名仍清楚可讀 |
| skeleton 與 input 範例 | frontend/src/NodeAssignments.tsx:31、194、195，viewData.ts | 佔位骨架、輸入提示，沒有實體 record | aria-hidden skeleton，loading 不顯示假筆數。提示不提交成預設內容 |
| 欄位未知預設 | frontend/src/ProjectDetail.tsx:157，DailyHome.tsx:37、45 | 「請參考本節點」等缺值說明，不是來源成果 | 改「來源未提供」，保留協助入口，不偽稱已有交付 |
| 快取與本地流程 | frontend/src/companyDashboardCache.ts，backend/workspace_projection.py:158 | 快取不等於 fake，但舊身分或模擬紀錄誤用可污染正式觀感 | session epoch 隔離，stale 與 origin 可見，未知數值用 null |
| 唯讀試讀 | backend/lark_pilot/sample.py:41、frontend/src/LarkPilotPanel.tsx:55、58 | transport 注入才 mock，正式是 bounded sample。單次樣本不證明整表完成 | 移到資料來源診斷。標示取樣及完整性，不能取代首頁工作讀取 |

可重跑 `rg -n 'DEMO_MODE|seed\(|fixture|simulated|mock|source_kind.*demo' backend frontend/src`。測試檔、fixtures、CSS 類名及輸入 placeholder 要分別檢查，不將命中清單直接當成事故清單。

## 5. 首頁呈現全部受指派工作

### 5.1 資料與版面

第一屏標題為「我的工作總覽」，下方是本人工作列表。使用者最先需要知道工作名稱、所屬案件、期限、目前狀態與下一步。不要先顯示公司總數、連線表數或系統維護紀錄。

| 面板 | 首先顯示 | 資料與點擊 |
| --- | --- | --- |
| 指派給我 | N 與 T 分列，案件案號及名稱、節點、截止日、狀態、可做或等待原因 | N 負責人含本人或 T 負責人為本人。點擊由穩定 case ID 與 record ID 進節點詳情 |
| 代理給我 | 本人代理工作、委託者、有效期間與範圍 | 只採 L 的已驗證有效代理，N/T 沒有代理欄位，不能從姓名推測 |
| 待我確認 | 真實待本人覆核或交接，需顯示角色與前提 | 沿用 home_queues 的授權結果，新增 N 待審核項的實際權限投影。排除停用申請 |
| 我交辦的 | 指派人、現任負責人、狀態、期限 | T/N 指派人與 local assignment_history 分來源。無 timestamp 時不說「最近交辦」 |
| 已完成 | 預設收合，查最近完成紀錄 | T 完成時間或 N 完成時間，取消與略過另標，不算完成 |

「全部」指本人可見的所有已指派工作，不是全公司的工作。主管另有「同組」視角，由 backend 授權。每面板第一頁 25 筆，可切到完整表格。預設 tab 為未完成，已完成仍可找得到。範本定義、無負責人節點、不適用項目不混入本人清單。沒有任務時使用真實 empty state，不產生展示任務。

同一 N 與其 T 同時指派本人時，保留兩種工作身份，以節點列可展開子任務。摘要分開顯示「節點責任 2 項、任務 4 項」，不能相加宣稱六個獨立任務。key 使用 kind、base、table、record。多筆相同指派鍵標 duplicate，不任意選第一筆作可寫記錄。

節點 deadline 來自關聯 T 的有效截止日最大值，沿用 `node_assignment/views.py:47、58` 的 aggregate 語意。另顯示最早未完成任務期限作 next_due。節點自身沒有截止日欄位，不新增假的原始期限。`original_deadline` 必須有已保存的不可變歷史或核定來源，否則 null 並顯示「未提供」。

列展開後呈現 T 內容、指派方式與人員、工程確認單來源、前置節點、退回原因、原始與現行期限的來源說明，以及原先首頁有用的代理與交辦資訊。詳細欄位不全部塞進第一屏。鏈結失效時顯示原因及回案件列表入口，不用純案號猜另一案件。

### 5.2 排序與狀態

未完成列表使用 overdue desc、有效 deadline asc、status priority、case code asc、kind、record ID。null deadline 放末尾，並有「未排期限」篩選。狀態同日優先退回修正、進行中、待處理、未開始。待審核放待確認面板，仍可在全部工作找到。

等待工作保留在未完成列表，有清楚「等待前置節點」「尚未到開始日」「來源待核對」文字。若 deadline 已過但不可執行，標示「期限已過，等待條件」，不要當作本人可執行逾期統計。到期日先用台北日曆日期比較，若聲稱工作日或當日截止時刻，必須引用已核定班表與既有 cutoff 規則。沒有班表時不能假設 17 時。

## 6. 暫停兩個功能的所有入口

server feature flags 命名為 `change_extension` 與 `routines`，本版 production 預設 false。不要刪 code，不改審批歷史，也不要把財務核准、node_skip、任務完成、出勤或真實 mentions 一起關掉。

| 入口 | 定位 | 停用處理 |
| --- | --- | --- |
| 左側導覽 | frontend/src/AppShell.tsx:12 | 隱藏 approvals 與 routines |
| 行動導覽 | frontend/src/AppShell.tsx:36、49 | tabs 排除 approvals，更多導覽同步排除 |
| topbar Bell | frontend/src/AppShell.tsx:42 | 移除，不導向已停用申請 |
| 頂層 hash routes | frontend/src/App.tsx:114、140 | #view=approvals、#view=routines 顯示「尚未開放」及回首頁，不能空白 |
| 首頁申請數、待審列、更多 | frontend/src/DailyHome.tsx:100、104、130、147、155 | 排除 change/extension，保留節點覆核、交接、財務真實確認 |
| 案件重大審批摘要 | frontend/src/ProjectDetail.tsx:62、85 | 分類 gate，保留 financial/node_skip，change/extension 顯示尚未開放且不可點 |
| 案件設計變更按鈕 | frontend/src/ProjectDetail.tsx:72、88、165 | 不掛開啟 modal 事件，旧 focus 或 modal 深連結也 gate |
| 任務展延與關聯申請 | frontend/src/ProjectDetail.tsx:85、86，App.tsx:145 | 隱藏建立、送審、套用、撤回、恢復按鈕。保留歷史唯讀紀錄 |
| 旧案件 tab alias | frontend/src/api.ts:59、60 | operations 與 approvals 經 normalizeRoute 後，仍要對 section gate。不能被 alias 繞過 |
| 案內 routines tab | frontend/src/Operations.tsx:61、73、101 | 隱藏 picker，section=routines 顯示尚未開放，不再掛 RoutineList |
| 全域 RoutineList | frontend/src/Operations.tsx:110 | 不再進入，可供歷史唯讀匯出但不能操作 |
| 日曆與例行設定 | frontend/src/Operations.tsx:139 | 追蹤頻率、review_weekday、monthly_workday 顯示停用，不可儲存成暗中啟用 |
| 通用 action API | backend/app.py:779，workflow.py:92、200、219、269 | 在入站 dispatch 前拒絕 approval_create 的 change/extension、對既有此類申請的 approval_*、change_resume |
| 例行 action | backend/operations.py:779、804 及 recurring_* branches | recurring_create、recurring_complete、recurring_review 返回 disabled，禁止產生新 history |
| 原生審批 API | backend/native_routes.py:133、208 | confirm-line 與 /{kind}/{request_id}/{operation} 的 change/extension 回 disabled。financial、node_skip 保持原 gate |
| 觀測與套用背景 | backend/native_poller.py、native_requests.py、sop_execution.py:298 | 停用範圍不可背景自動套用或開新輪次。已送外部審批可由只讀 observer 保存外部狀態，但不寫業務效果 |
| 例行建立與摘要通知 | backend/jobs.py:62、69、94、104、255 | 不產生停用種類、不排入新 digest。舊待發 job 在 dispatch 前重查 flag，標 blocked_feature，不假裝發送成功 |
| 收付款衍生追蹤 | backend/operations.py:779 | 保留財務核定本體，不建立 recurring 提醒 |
| SOP 完成後追蹤 | backend/sop_deadlines.py:19、135 | 含報價回簽等 followup。本版不自動產生可操作追蹤入口，保留歷史與必要 SOP 本體 |
| home/backend counters | backend/home_queues.py:33，my_work.py:113，shell.py，company_dashboard.py:117 | 排除停用 action 與計數，不能返回尚未開放的可點連結 |
| 通知深連結 | backend/jobs.py、mention_notifications.py，frontend/src/MentionInbox.tsx | 導向停用功能的歷史連結落在 disabled 頁。一般案件與討論仍可開 |

被停用 mutation 在完成身份驗證後、讀寫業務資料前回 HTTP 503，body 使用穩定 `code=feature_disabled`，不是無意義的 404 或成功空列表。詳見 API 範例。已存在凍結中的變更不擅自解凍，可能使部分工作繼續等待，需在案件顯示歷史原因並列入風險。

feature flag 由 server 發送，前端只控制呈現。單靠 hidden button 不構成停用。既有測試可在 test config 顯式打開兩個 flags，保留原流程測試，再新增 production default off 的行為測試。不要大批修改 expected status 讓測試失去原保障。

## 7. 載入策略與 API 能力

### 7.1 已有與待核實能力

官方頁最初無法由 web extractor 取得內文，後續透過 T3 preview 的頁面文字成功查證 Search、Batch get、List records 與 Rate limits。以下限制是 2026-10-14 讀取的官方正文，不採第三方搜尋摘要。Search 頁更新日為 2025-05-08，Batch get 為 2025-07-21，List 為 2024-09-18。

- [Search records](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/bitable-v1/app-table-record/search)。
- [Batch get records](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/bitable-v1/app-table-record/batch_get)。
- [Rate limits](https://open.feishu.cn/document/server-docs/api-call-guide/frequency-control)。
- [List records](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/list)。官方標為歷史介面，建議使用 Search。

| 能力 | 本輪證據 | 使用規則 |
| --- | --- | --- |
| search、page_size=500、page_token | 官方 Search 正文確認預設 20、最大 500、以 page_token 分頁。backend/sources.py:60、115 與 node_assignment/lark_table.py:334 已有實作 | 背景讀取用 500，UI 回應 25 或 50。不因 page_size 大而整表首屏阻塞 |
| field projection | 官方 Search 接受 field_names 陣列，最大 200 個名稱。backend/sources.py:100、109、115；CLI 本輪投影成功 | 每個面板用白名單 field_names。schema 另快取，姓名、數字、關聯 ID 分型保存 |
| filter pushdown | node_assignment/lark_table.py:277、462 | 本人 owners/assignee、case relation、狀態與日期能映射成真實欄位時推到 search，不用 string 拼 filter |
| sort | 官方 Search sort 陣列最多 100 項。CLI 包裝 sort-json 最多 10 項，兩者不能混淆；pm-ref 一般 table 為 client sort | search body 使用 field_name、desc。UI sort key 由 server 白名單映射。複合 overdue 排序需本地 materialized projection，不只對第一頁排序 |
| view_id | CLI help、pm-ref/lib/lark.ts:434 | 只有使用者選定的 view 才套用。已排序視圖可能限制來源範圍，回傳 scope，不視為全表 |
| batch_get | 官方 Batch get 正文確認最多 100 record_ids。node_assignment/lark_table.py:291 與 pm-ref/lib/lark.ts:386 每批 100 | 已知 relation IDs 用 batch，保留 ID，不以顯示文字 join。檢查 absent_record_ids、forbidden_record_ids，不能以空 records 證明來源真的空 |
| record count | 官方 List records response 範例含 total，今日 +table-list 回 records_count。pm-ref search 讀 total | 顯示 count_scope 與 counted_at，不能把表總數當篩選後數量。total 缺失則 null |
| app QPS | 官方 Search、Batch get、List records 均標示 20 次每秒。Rate limits 的一般策略按 API、app、tenant 計算，Base 另屬特殊處理 | 不把 20 當所有 API 相加的單一總額，也不把 50 當已核實的讀取上限。限流鍵保留 endpoint、app、tenant，依實際 response header 收斂 |
| per-table QPS | 已讀的官方端點頁沒有另列每表讀取 QPS 數值，錯誤 1254291 明確表示同表不支援併發 write 接口 | 不能宣稱每表讀取 20 或 50 QPS。每表寫入序列化是併發限制，不是讀取配額。實際租戶特殊 quota 仍須平台確認 |

官方端點 QPS 已核實，但 Base 的特殊 app/table 配額沒有在已讀頁另列，實際租戶配額仍是工程查證項目。官方指南也沒有提供 Base 自助提高頻控能力，不能假設換 token 就能增加配額。採既有 `live_read/config.py:16` 的 5 RPS 作本系統讀取總預算，`rate_limit.py:33` 的 process bucket 可重用。新增每表 2 RPS 保守內部預算及最多 3 個來源讀取並行，以上 5 RPS、每表 2 RPS 與 3 個並行均是保守設計值，不是官方上限。多 process 或多 replica 需共享限流，不能每個 instance 各自花完整 app 配額。所有 Lark client 包括 node_assignment、sources、avatars 的相關 metadata 讀取應共用預算。Batch get 官方另提醒進階權限下需 manage 權限，否則可能成功而回空。這不是擴大讀取權限的理由，應保留原身份並顯示不完整或無權限，必要時用合法的 search 讀取已知關聯。

### 7.2 實作流程

1. 先讀 session，再讀 shell。使用同身分同工作區上次成功快照 first paint，沒有快照顯示骨架，不顯示零值。
2. 首頁只優先讀 assignments。個人確認、交辦與最近案件各為獨立請求，面板可完成即顯示。失敗面板保留 lastGood 並標「上次資料，更新失敗」。
3. 未展開 detail、history、finance、people directory 不讀。IntersectionObserver 提前一個 viewport 預取，hover 或 keyboard focus 150 ms 後預取 case summary。saveData 或慢連線停用額外 prefetch。
4. UI 表格每頁 50，首頁每面板 25。排序、篩選重置 cursor。server cursor 綁 query hash、身份、snapshot version，不把 Lark page_token 暴露作任意跨查詢游標。
5. filter、sort 對單一來源能下推即下推。跨 N/T、overdue、derived_status 使用授權後 materialized read model，完整排序後再切頁。來源仍讀取中回 partial，不能宣稱前 25 就是全公司最急 25。
6. snapshot 快取鍵包含 tenant、identity app、open_id、workspace、authz version、projection、filter、sort、view。新 session、登出、權限或角色切換清除，不共用他人結果。
7. 同 key 同時讀取共用一個 promise 或 server lease。schema TTL 起始 30 分鐘，關聯標題 10 分鐘。工作資料 60 秒，名冊 120 秒，出勤 300 秒。TTL 過期後保留快照標 stale，最長保留時間依現有 stale_max 與來源權限核對。
8. GET 的 ETag 包含 query、snapshot 與 authorization context。回 private、must-revalidate。If-None-Match 命中回 304 且仍需授權。frontend api 沿用 epoch gate，freshness 欄位不能被 304 永久凍結。
9. visible panel 每 60 秒可背景 refresh，隱藏 tab 停止。資料使用 stale 標籤與資料時間，server receipt time 不冒充 Lark 更新時間。回前景只刷新可見與已過期面板。
10. dirty drafts 或 mutation 中不覆蓋編輯值。successful mutation 只 invalidates 受影響 case、assignment panel、counts，版本回讀後再更新，不把 optimistic UI 當 Lark 已成功。
11. 429、既有可重試讀取錯誤採有上限 exponential backoff 與 jitter，優先 Retry-After。401、403 不重試成空表，partial cursor 不斷線假裝 complete。維持重複 cursor、重複 record、缺失下一頁與頁數上限檢查。

ETag 是工作台 endpoint 的機制，未查證 Lark Bitable 原生支援 conditional GET，不能把工作台 304 的改善當作 Lark request 已省略。即時也不是每次重拉所有來源。源快取需獨立 freshness，避免某一來源成功掩蓋其他來源過期。

### 7.3 頭像

延續 `Avatar.tsx` 的安全 URL、lazy img 與錯誤首字 fallback。定義 28、32、40 px 尺寸，img width、height 固定，object-fit=cover，decoding=async。同個 open_id 的頭像 URL 由名冊或 OAuth 更新，不在每一列獨立查 user detail。採 browser HTTP cache，未驗證 CDN cache header 前不宣稱 immutable。URL 更新時清除 failed state，404 短期負快取避免反覆請求。

保留 HTTPS host allowlist，不為了顯示更多照片直接允許任意 URL。官方 Search 的示例頭像 host 為 internal-api-lark-file.feishu.cn，List 示例為 internal-api-lark-file.larksuite.com。現有 feishucdn-only allowlist 可能拒絕有效 Lark 頭像，這是靜態可見風險，尚未確認本租戶實際 URL。實作先驗證真實 OAuth 與 P 回應，再將這些明確官方 host 加入共用 backend/avatar.py 與 frontend allowlist，不允許任意 feishu 子域。字首是 fallback，不是假的已載入頭像。與姓名並排時 img alt 可空，由父元素提供姓名，避免重複朗讀。

### 7.4 驗收目標

以下是目標，不是本輪測量結果。同資料規模、同角色與同權限，區分 cold、warm cache 與背景更新。

- warm 首頁主要文字與首批工作在 1 秒內可用，cold shell 在 2 秒內可互動。外部 Lark 不達標時仍要獨立顯示面板等待狀態。
- 切頁不觸發全來源同步，首次 N/T 面板不讀財務表。收合 detail 沒有額外 request。
- 快取相同查詢同時 10 位 caller 只產生一組 upstream 分頁讀取。部署多 process 時也核對。
- 斷線、403、空表、部分讀取、兩身分切換、排序跨頁、草稿未儲存各自驗證，不只驗證 happy path。

## 8. Topbar 與設定頁

### 8.1 Topbar

`AppShell.tsx:42` 目前顯示 breadcrumbs、DataFreshness、正式或測試 badge、workspace as_of 日期、refresh button、導向 approvals 的 Bell。`:38` 還有 route-progress。`App.tsx:107` 的 recovery header 也掛 DataFreshness。

改版只保留 mobile menu、當前頁 breadcrumbs。案件頁 breadcrumbs 可帶清楚案號。身份、role 與 appearance control 留側欄底部與身份選單。測試環境警示放側欄或頁內常駐提示，不消失。

移除 topbar 的 DataFreshness、載入進度、資料時間、無關統計、refresh 與 Bell。每個資料面板自行顯示更新時間、stale、partial、retry。來源與設定頁提供同步診斷。初次登入的等待內容可留在 login main，頁內 loading skeleton 可留。不能為滿足 topbar 要求而隱藏讀取失敗。

### 8.2 設定頁為何可能沒有內容

| 路徑或 gate | 程式證據 | 可確定的事 |
| --- | --- | --- |
| #view=admin | App.tsx:114，Operations.tsx:132 | 預設 tab=people，不是 settings。點管理設定未必已進日曆與連線 |
| shell workspace | appCommon.tsx:84 | admin 要 FullWorkspaceGate 成功後才 render。整包讀取慢或失敗可擋全部設定 |
| RuntimeHealthPanel | RuntimeHealthPanel.tsx:15、16、17 | 只在 lark、production、manager 時顯示，其他情況 return null |
| 原生審批設定 | Operations.tsx:139 | NativeDefinitionPanel 同樣需正式 manager |
| 連線設定表單 | Operations.tsx:139 | manager 才看得到，無角色者只剩較少內容 |
| OpsFlowPanel | OpsFlowPanel.tsx:20、23 | 404 時整個面板 return null，feature 未啟用時不顯示 |
| production 設定路由 | backend/app.py 與 runtime-health | 無登入未驗證 response，不能確認部署旗標、角色或 API 故障 |

可推論多個 gate 會讓非 manager 設定頁非常稀疏，但這些條件不足以證明 staging 空白的唯一原因。實作人員須用已授權登入核對 route、role、scope、network status 與 empty rendering。

新增所有登入者可讀的 settings overview，獨立於整包 workspace。首屏呈現本人的姓名與角色、目前工作區、有效權限、三個工作來源連線狀態、最近成功同步及 feature flags。來源表逐列顯示 source name、as_of、last_success_at、last_attempt_at、readState、loaded_count、total_count、complete、missing_scopes。未設定顯示「尚未設定」，沒有資料顯示「尚無成功同步」，不能默認綠色正常。

manager 才能看 worker、backup、directory 維護細節與設定表單。一般成員看自己 permissions 與該角色可見來源，不洩漏隱藏表名、他人角色映射、app secret、tokens、原始 env、內部 host 或 stack trace。名冊展示最近成功、有效人數、缺失 ID 數與授權缺口，不因 worker 心跳而更新名冊有效時間。

## 9. 逐頁首屏與預設排序

路由全集來自 `App.tsx:107、114`、`AppShell.tsx:12`、`p2RouteNames.ts:4`。`sources` 是側欄底部入口，`project` 與三個 P2 detail 是深連結。`learning` 為 alias，不是獨立 top-level page。每列列出 3 至 6 個先看項目，來源代號對應第二節。

| route | 用途與先看項目 | 移除或移到次層 | live 欄位與本地來源 | 預設排序及理由 |
| --- | --- | --- | --- | --- |
| 登入 | 公司帳號登入。品牌、登入方式、授權失敗原因、重試 | 不顯示 demo 切換或工作 KPI | session 與 OAuth L，沒有 Bitable 查詢 | 不適用 |
| recovery | 處理公司名冊或帳號資格不足。本人、原因、可採取動作、重新登入 | 系統維護詳情移設定。topbar 無讀取指示 | P 在職與識別核對、session L | 先阻斷原因後補充，不猜本人仍在職 |
| dashboard | 本人全部指派。工作、案件、期限、狀態、等待理由、待確認 | 公司統計、趨勢、來源連線移各專頁 | N 節點及負責人，T 標題與截止日，C 案名，L proxy 與 queue | 逾期、期限、狀態，沒有日期末尾 |
| pm-glance | PM 快速掃描。本人工作、待核對接案、案件風險、真實確認、資料缺口 | 不作所有人的強制 landing，避免重複首頁摘要 | PmGlance.tsx:31 至 :34 讀 my-work、projects、source-health、confirmations。N/T/C/Q 與 L | 有效風險優先，其次到期日，未知風險獨立 |
| company | 公司可見案件概況。成案數、待確認接案數、組別風險、工程狀態、異常案件 | 本人任務與每表 sync diagnostics 移出。財務金額需權限 | C 工程確認單編號與狀態，Q 待確認，N/T 執行資料，L lifecycle mapping | 異常類別優先、最近有效期限、案號。保留來源狀態與工作台進度兩欄 |
| projects | 找案件。案號、案名、PM、來源狀態、目前節點、最近期限 | 大型 KPI、所有節點 mini cards 改展開 | C、Q、S 目前節點、N 負責人、T 截止日，L execution admission | 有逾期工作在前、期限 asc、案號 asc。不以報價建立時間作預設 |
| overview | 主管處理確認單與案件。待核定案件、確認單版本母體、執行歸屬、阻斷、資料完整性 | 金額、未證明進度 KPI、混合母體統計移除 | C SourceID 與 record version，L admission 與 authorized population。manager_overview.py:143 | 待核定、受阻、有效期限、案號。未知日期保留 null |
| confirmations | 工程確認單清單。編號、案名、來源版本、PM、歸屬狀態、資料警示 | 原始所有成本欄與長 PDF URL 移 detail | C 工程確認單編號、工程名稱、SourceID、建立時間、資料警示，Q version，L admission | 待核定歸屬在前、來源期限 asc、建立時間 desc、record ID。不同版本不合併 |
| confirmation | 案件與確認單詳情。身份與版本、案名、來源狀態、關聯工項、有效責任人、執行入口 | 長 history、raw fields 與 finance 收合 | C 工程確認單 PDF、合約明細（日報關聯）、S、N，L execution gate | 版本 newest first，明細合約項次 asc，缺項次末尾 |
| contract | 合約明細詳情。項次與名稱、數量單位、原始與報出值、來源確認單、各組工作量 | 成本計算、raw metadata、歷史移次層 | D 合約項次、合約工作項目、合約數量、合約單位、分項金額兩欄、各組預估工天，C/W links | 工項依項次與 record ID。數值用數字比較，不字串排序 |
| workitem | 填報工項詳情。名稱與類別、基準量、標準點數、來源明細、關聯日報、資料缺口 | 每日私人成本、所有公式拆解移次層 | W 工項名稱、工項類別、工項細碼、基準數量、標準點數、來源合約明細，O/I | 日報按業務日期 desc、工作單號、record ID；不能用建立時間代替 |
| work | 完整本人工作。任務、節點、案件、期限、負責人、可執行原因 | legacy board/time axis 作 optional tab，不首次讀整包。mentions 收合次層 | N/T/C 與 L proxy，my_work.py:160。T 正式截止日需新增投影 | 同首頁複合排序，server 分頁；看板同 priority |
| people | 找人與安排人力。姓名頭像、組別、在職、該週出勤、出差、來源缺口 | 工資成本與私密審批內容不出現 | P 姓名、Lark帳號、所屬組別、在職，A 出勤與出差，L work schedule | 組別、在職、姓名 zh-Hant、open_id。出差按開始日 asc |
| schedule | 排程與人力。時間範圍、工作責任人、案件、開始與截止、衝突、未排工作 | 不把計點等同工天，未核實容量不畫滿載百分比 | T 截止日與負責人，N 開始時間，L 已核定 start/cutoff/班表。工作預排表尚未核欄位 | 日期 asc、組別、姓名。未排期列表按案件與任務 |
| project | 執行單案。案號案名、SOP 進度、真實節點負責人、當前任務、最近期限、阻斷 | change/extension 停用，評論與說明次層，不讓範本 count 蓋過 T | C/S/N/T，沿用 node_assignment/views.py 的 derived_status 與 warnings，L legacy 歷史 | 九節點固定 CHAIN，節點內 T 逾期優先與 deadline asc |
| approvals | 現階段只提供停用落點。頁名、尚未開放、回首頁 | 不顯示可操作 pending queue 或新建 CTA | L flag，不讀私人申請列表 | 不適用 |
| routines | 現階段只提供停用落點。頁名、尚未開放、回首頁 | 不顯示例行結果表與完成按鈕 | L flag | 不適用 |
| sources | 來源狀況。來源名、連線授權、完整性、最近成功、已載入範圍、重試 | 取樣試讀與 raw 欄位移 manager diagnostic，demo reset 僅隔離 | C/D/W/O/I/OC/IC/N/T 的同步 metadata，L source-health | 失敗、部分、stale、fresh，各組再按來源名 |
| admin | 查看設定。本人身份、工作區、權限、三表狀態、flags、名冊狀況 | mock、secrets、無權限表單不顯示。default overview 取代空白 | P 名冊，N/T/S table metadata，L session/runtime | 系統阻斷先，逐表失敗優先 |
| learning alias | 舊連結進 admin people。人員、權限、名冊狀況 | 不當獨立路由。Learning.tsx 的存在不代表目前有導航入口 | api.ts:56 normalize，P 與 L | 同人員頁 |

### 9.1 案件頁子頁與既有深連結

| tab 或 section | 先看 3 至 6 項 | 移動及資料對應 | 預設排序 |
| --- | --- | --- | --- |
| overview | 案名案號、狀態、負責人、最近期限、目前節點、資料警示 | C/S/N/T，長說明與來源原文收合 | 阻斷與最近期限先 |
| flow | 九節點狀態、各組負責人、目前工作、截止日、前置條件、退回原因 | N/T。範本只在 legacy 區有 origin。comments 放底部 | CHAIN，任務同首頁 |
| daily | 業務日期、工作單號、組別人員、作業內容、公布點數、檢核 | O/I 與 OC/IC，原始、修改後、最終值可展開並明確分列 | 工作日期 desc |
| data basic | 案號、業主、PM、來源、合約、原始與現行期限 | C/Q 與 L。未知業主或期限不推測 | 單案不適用 |
| data quotes | 報價編號、工程編號、金額、共同確認、來源版本 | Q 本輪未核，C 報價單 PDF 只作附件來源 | 版本 desc、報價編號 |
| data contracts | 合約項次、工作項目、數量單位、確認單、工作量 | C/D/W，進 P2 detail 保留返回上下文 | 合約項次數字 asc |
| data family | 母子案身份、子案 PM、狀態、合約來源、彙總完整性 | L 經核實的 explicit relations，不以案號後綴配對 | 子案 code、stable ID |
| data participants | 節點、責任人、指派方式、指派人、任務人員 | N/T/P，不能將姓名當 unique identity | CHAIN、姓名 |
| data files | 檔名、類別、版本、上傳時間、Drive 狀態、來源 | L files，C PDF、O/I 附件。remote receipt 證明保存狀態 | 最新版本與上傳時間 desc |
| logs | 操作、操作者、時間、範圍、前後值、來源 | L audit，N/T 實際版本與應用寫入 audit | created_at desc，穩定 event ID |
| flow review | 工作完成、必交成果、待覆核角色、缺失原因 | L delivery/evidence，N 核准欄位。不得把 N 狀態 alone 當核准證據 | 待本人覆核優先 |
| flow batches | 交付數量單位、工項、證據、版本、覆核狀態 | L delivery batches，W 對照。財務核准仍保留 | 未核准先，version desc |
| flow roles | 現任責任人、有效代理、期間、交接狀態、資格缺口 | P/N/T 及 L delegation/handover，出勤無法自行授權代理 | 有效及待接手優先 |
| flow finance | 來源金額、預估與實際成本、核定狀態、來源版本 | C/D 與 L financial requests，權限分開 | 未核定先，版本 desc |
| flow inputs | 必交內容、已提供佐證、來源欄位、缺失、保存狀態 | L input mappings/revisions 與可追溯 C/W，未知來源不顯示成功 | 缺失先，required 定義順序 |
| flow issue | 確認單版號、收件人、核定、發出時間、真實回執 | C 與 L confirmation issue/jobs | 最新有效版本先 |
| flow deadlines | 事件日期、來源、影響工作、有效期限、待核對差異 | L event deadlines、T 截止日。不能使用此頁繞過停用展延 | 未處理衝突先、事件日期 desc |
| flow routines | 尚未開放、功能名稱、回案件 | 停用，保留歷史 | 不適用 |
| flow approvals | 真實財務與 node_skip、版本、狀態、可做動作 | change/extension 尚未開放，舊申請歷史只讀 | 待本人處理先，created_at desc |

`quotes`、`family`、`basic`、`participants`、`files` 舊 tab 經 `api.ts:58` 正規化為 data section。`operations` 經 :59 進 flow section，`approvals` 經 :60 進 flow approvals。新 disabled gate 必須在正規化後套用，task、focus、completion 仍需原有 case visibility 與 action authorization。

### 9.2 管理設定子頁與 legacy 頁

| 入口 | 先看項目 | 移動與資料 | 排序 |
| --- | --- | --- | --- |
| admin overview 新增 | 本人、角色、工作區、permissions、flags、來源狀態 | L 新設定 API，P 名冊摘要 | 阻斷先 |
| admin people | 姓名、組別、在職、role、capabilities、來源有效性 | P 與 L role map。能力訓練資料保留，但不得硬造候選人 | 在職與未核對分組，姓名 |
| admin sop | 已用版本、發布狀態、節點任務定義、適用條件、缺口 | policy/sop_contracts 的 L，不是 T live records | published 使用版先、draft version desc |
| admin settings | 連線健康、每表時間、日曆、名冊、flags、維護狀態 | L，表單限 manager。例行設定停用，mock 隱藏 | 失敗與 stale 先 |
| admin daily | 未配對原因、原案號、日期、原始紀錄、提案、核對狀態 | O/I、OC/IC 與 L daily mapping | 待核對、日期 desc、record ID |
| admin jobs | 工作種類、狀態、最近嘗試、失敗原因、真實回執 | L jobs。停用功能 job 標 blocked_feature，不再送出 | failed/blocked/unknown、queued、done，再時間 desc |
| work tab=legacy | 指派、案件、節點、期限、waiting、執行资格 | 原 table/board/timeline 保留入口，N/T 整合後不作第二套權威 | 與新列表同排序 |
| sources tab=legacy | 來源表、完整性、最近成功、警示、原始連結 | SOURCES 與 L source snapshots，不設假數字 | 同來源健康頁 |

## 10. Liquid Glass 樣式契約

### 10.1 現況與檔案責任

| 檔案 | 現有用途及衝突 | 改版責任 |
| --- | --- | --- |
| frontend/src/design/tokens.css:3、9、14、31 | light/dark 色彩、glass 20px、spacing，已有 20、44、64 等值 | 單一 token 定義。新增必要 aliases，內容排版只用 4/8/12/16/24/32 |
| design/glass.css:2、6、7、8 | glass、bar、flat，nested blur 與 reduced transparency fallback 已有 | card、bar、fallback 的唯一 owner |
| design/primitives.css:24、28 | ds-button 有 variant、active scale 與 disabled | ds-button 的 primary/secondary/ghost 與 focus-visible |
| design/controls.css:3 | 對 .button 與 .ds-button 共通控制尺寸，含 !important | 控制尺寸一致，減少後來覆寫，不改互動 handler |
| design/shell.css:5、20、50 | sidebar、topbar、mobile tabs 外觀 | page padding、shell glass，避免多層固定 blur |
| polish.css:68、71、110 | 後段把 cards 改 opaque、backdrop none，legacy button 自訂；首頁 hero opaque | 移除與新 token 相反的覆寫，保留必要 layout，不能再疊一輪更高 specificity |
| styles.css、workbench.css、brand-workspace.css、company-workspace.css | legacy 基礎樣式與 shell/layout 補丁 | 舊 selector 轉 token alias。不要新建全域 button 規則破壞外部 widget |
| Avatar.css、polish.css:49 | Avatar 尺寸與背景有競爭，polish 把 width 改 auto | Avatar.css 為唯一 avatar 外觀 owner，取消變形覆寫 |
| DailyHome.css、ProjectsList.css、ProjectDetail.css、ProjectPanels.css、NodeAssignments.css | 專頁卡片與排列 | 只控制該頁 grid、密度、溢出，不重新定義品牌 tokens |
| CompanyCockpit.css、pm-glance.css、my-work-table.css、MyWorkBoard.css、TaskTimeline.css | 管理、工作與時間軸 | 採既有 tokens，表格 rows 不 blur |
| Sources.css、source-health.css、freshness-view.css、owned-screens.css、people-attendance.css | 狀態、資料品質、維護與出勤 | status badge 採共用對比 token，頁內 freshness 保留 |
| operations.css、Approvals.css、NativeApproval.css、ops-sync.css、p2-case.css、p2-detail.css、p2-lists.css | 作業表單、審批與 P2 | 視覺統一，disabled gate 不由 CSS 代替 |
| DailyRecords.css、audit-trail.css、discussion.css、mentions.css、file-workspace.css、file-category-settings.css、drive-file-storage.css、deadlines.css、ExecutionAdmission.css、lark-pilot.css、celebration.css | 局部資訊與互動 | 使用共用色彩、spacing、radius，保留語意與可見性 |
| design/skeleton.css、design/tabs.css | loading 與 tabs | 頁內 skeleton、focus與 overflow，reduced-motion 無動態 shimmer |

### 10.2 Token 起始值

以下是實作規格，尚未在畫面量測。RGBA glass 底色只用於 cards，大表文字區採不透明 surface。既有 token name 可 alias，避免改 TSX 行為。

```css
:root {
	--space-1: 4px;
	--space-2: 8px;
	--space-3: 12px;
	--space-4: 16px;
	--space-6: 24px;
	--space-8: 32px;
	--page-padding: 32px;
	--radius-control: 12px;
	--radius-card: 16px;
	--radius-dialog: 24px;
	--bg: #eef2f7;
	--surface: #ffffff;
	--label: #152333;
	--label-2: #465569;
	--accent: #174f8c;
	--on-accent: #ffffff;
	--glass-fill: rgb(255 255 255 / .86);
	--glass-bar-fill: rgb(248 250 252 / .92);
	--glass-blur: saturate(120%) blur(12px);
	--glass-border: rgb(21 35 51 / .14);
	--glass-highlight: inset 0 1px 0 rgb(255 255 255 / .85);
	--glass-shadow: 0 8px 24px rgb(21 35 51 / .08);
	--focus-ring: #174f8c;
	--status-ok-fg: #14532d;
	--status-ok-bg: #dcfce7;
	--status-warn-fg: #713f12;
	--status-warn-bg: #fef3c7;
	--status-error-fg: #991b1b;
	--status-error-bg: #fee2e2;
	--status-info-fg: #1e3a8a;
	--status-info-bg: #dbeafe;
	--status-unknown-fg: #334155;
	--status-unknown-bg: #e2e8f0;
}
:root[data-theme="dark"] {
	--bg: #101820;
	--surface: #18232e;
	--label: #f1f5f9;
	--label-2: #cbd5e1;
	--accent: #b8d8ff;
	--on-accent: #102c49;
	--glass-fill: rgb(24 35 46 / .92);
	--glass-bar-fill: rgb(16 24 32 / .96);
	--glass-border: rgb(255 255 255 / .16);
	--glass-highlight: inset 0 1px 0 rgb(255 255 255 / .09);
	--glass-shadow: 0 8px 24px rgb(0 0 0 / .24);
	--focus-ring: #b8d8ff;
}
@media (max-width: 767px) {
	:root { --page-padding: 16px; }
}
```

status badge 採不透明背景，以上 fg/bg pairs 在 light/dark 都維持同一組配對，不把深色 foreground 單獨放 dark glass 上。若另外定義 dark badge 必須重測。WCAG AA 一般文字至少 4.5 比 1，大字至少 3 比 1，focus、圖示及控制邊界至少 3 比 1。驗收以實際 composited background 與最差底圖取色計算，token 看起來深不代表已通過。狀態必有文字與圖示，不只紅綠。

### 10.3 Component classes 與互動狀態

| class 或 variant | 外觀 | interaction |
| --- | --- | --- |
| .glass、.glass--card | glass-fill、12px blur、1px border、inner highlight、soft shadow、16px radius | hover 僅可點卡才改 border。普通 card 不假裝可點 |
| .glass--bar | bar-fill、單層 blur，邊界清楚 | topbar 純導航，不載入狀態 |
| .glass--flat、.table-scroll | opaque surface 或高不透明 fill，無 blur、細 border | 表格 row hover 用實底，不增添 blur layer |
| .ds-button[data-variant=primary]、.button.primary | accent 背景、on-accent 文字、細 highlight、44px min height | hover 亮度微調、active 降低 shadow，不改 layout |
| .ds-button、.button | secondary glass-fill、label 文字、邊框 | hover 提高填色至實底，active 同上 |
| .ds-button[data-variant=plain]、.text-button | ghost 透明底、accent 文字 | hover 有低色填底，不能只改 opacity |
| :focus-visible | 2px focus-ring、2px offset | 清楚 keyboard focus，不用 outline none |
| :disabled、[aria-disabled=true] | 明確禁用文字與填色，不只透明變淡 | 無 hover transform，禁止觸發。aria-disabled 仍需原 JS gate |

focus 的 edge contrast 應對實際背景測量。disabled 可依法免文字對比仍建議可讀，附可理解原因。primary 使用既有 `--on-accent`，不要同時維護含義不同的 accent-fg。button radius 一律 12px，avatar round，badge pill。不要同一頁混用大圓膠囊與方形按鈕而沒有語意差異。

頁 padding 桌面 32、手機 16，panel gap 24，小面板 gap 16，文字與 icon gap 8，表格 cell block 12、inline 16。header 與內容 gap 24，頁內章節 gap 32。控制高度 44 是觸控尺寸，不是新增內容 spacing 階。

`prefers-reduced-motion` 下移除 transform、animated gradient、shimmer 與平滑自動捲動，transition-duration=0。保留可見 focus。`prefers-reduced-transparency` 與無 backdrop-filter 下用 opaque surface，移除 blur，保持同樣邊框、文字與資訊層級。

每頁只讓外層少量 cards 有 blur，不在每列、cell、button 內再次 backdrop-filter。sticky header 及大表採 opaque，modal 外層可 blur，但內 card 平面。不得使用全頁 will-change，避免大量 GPU layers。驗收手機長表捲動與 low-power fallback。CSS worker 不改 routes、action handler、API、來源 mapping 或權限。

## 11. API 增補契約

以下 endpoint 與欄位均為提案，不是已存在的 wire response。既有 endpoint 能承接就擴充它，避免另建第二套授權。公用 field definitions 由 integration owner 統一。

### 11.1 工作讀取

擴充 `/api/my-work` 支援 `kinds=node_assignment,task`、`scope=mine`、`status=open`、`sort=urgency`、`limit=25`、`cursor`。另新增 `/api/home-panels` 回個人面板的 independent state 與 counts。不要讓 home endpoint 等完財務與出勤才回。

```json
{
	"readState": "partial",
	"snapshot_version": "opaque-version",
	"as_of": "2026-10-14T15:00:00Z",
	"freshness": {"status": "stale", "last_success_at": "2026-10-14T14:59:00Z", "refreshing": true},
	"counts": {"node_assignments": 2, "tasks": null, "count_scope": "viewer_visible", "complete": false},
	"items": [{
		"id": "node_assignment/record-id",
		"kind": "node_assignment",
		"origin": "lark",
		"source": {"table_id": "tblcPZPmezkyeVb7", "record_id": "record-id"},
		"case": {"id": "stable-case-id", "code": "C115264", "name": "來源案名", "relation_state": "verified"},
		"node_key": "control",
		"title": "控制",
		"status": "not_started",
		"source_status": "未開始",
		"assignment_state": "assigned",
		"assignees": [{"id": "opaque-user-id", "name": "來源姓名", "avatar_url": null}],
		"deadline": null,
		"next_due": null,
		"original_deadline": null,
		"deadline_basis": "related_tasks_max",
		"can_execute": false,
		"blocked_reasons": ["previous_node_not_done"],
		"target": {"view": "project", "project": "stable-case-id", "tab": "flow", "node_key": "control"}
	}],
	"next_cursor": null,
	"has_more": false
}
```

這是 shape 範例，不是本輪真實指派或筆數。node_key 跟 legacy node_id 分開。要能直接開啟 NodeAssignments 的真實 node detail，integration owner 定義 hash key，例如 `assignment_node=control` 與 `assignment_task=record-id`，不要拿 record ID 塞 legacy task ID。未配對 case 的 row 保留「案件關聯待核對」，無可點 target，不憑案號造 URL。

來源類型列舉採 `lark`、`local_workflow`、`sop_definition`、`simulation`。正式工作 endpoint 排除 simulation。sop_definition 不作任務列，只有正式生成的 local workflow 實例且有指派才能加入，仍與 Lark T 分開計數。`complete=false` 與 `has_more=false` 可同時存在，代表來源尚未完整，不是沒有下一頁就已完整。

### 11.2 表格查詢

既有 projects、confirmations、company-dashboard、my-work 增加一致的 sort、direction、limit、cursor 與 query_echo。server sort 白名單以產品欄位命名，不接受任意 Lark formula。現有 `p2Routes.ts:94` 的 query-bound cursor history 保留。offset endpoint 若仍保留，標成舊契約，不混用同一下一頁按鈕。

每個 response 包含 count_scope、filter_scope、complete、snapshot_version、source_as_of。total_count 未核實則 null。穩定排序最後加 record ID。cursor 過期回 409 `cursor_expired`，前端回首頁保留 filters 與 sort。

### 11.3 設定讀取

新增 `/api/settings/overview`，所有已登入者可讀自身的 sanitized summary。manager 專用 `/api/admin/runtime-health` 保留，逐表來源狀態可由 `/api/source-health` 組合。

```json
{
	"user": {"name": "來源姓名", "role": "member", "permissions": ["read_own_work"]},
	"environment": "production",
	"features": {"node_assignment": true, "change_extension": false, "routines": false},
	"sources": [{
		"name": "任務",
		"readState": "complete_empty",
		"last_attempt_at": "2026-10-14T15:00:00Z",
		"last_success_at": "2026-10-14T15:00:00Z",
		"source_as_of": null,
		"loaded_count": 0,
		"total_count": 0,
		"count_scope": "viewer_visible",
		"complete": true,
		"missing_scopes": []
	}],
	"directory": {"status": "unknown", "last_success_at": null},
	"manager_details_available": false
}
```

所有數值為示例。沒有授權的來源不回名稱、table ID 或 count。可見表身份可以回，但 secret、token 與全量設定不得回。`source_as_of=null` 不以 API 查詢時刻補值。

### 11.4 停用 response

```json
{
	"code": "feature_disabled",
	"feature": "change_extension",
	"message": "變更與展延尚未開放",
	"retryable": false
}
```

HTTP 503、Cache-Control=no-store。routines 同樣回對應 feature 與訊息。已驗證身份後回 disabled，不用讀取 request 指向的私人申請來決定是否停用。前端收到 code 即顯示停用落點，沒有自動 retry。背景 jobs 對此 code 轉 blocked_feature，不能無限重試。

## 12. 依賴順序與互不重疊的工作分流

每個檔案只有一個寫入 owner。下表為下一輪實作建議，不是本輪已啟動的 workers。未列檔案先由 integration owner 分配，不自行擴大 allowlist。測試新增用專屬檔名，避免共改 fixture 與 package 設定。

| stream | 優先與依賴 | 可碰檔案 | 不可碰檔案 | 可獨立驗收結果 |
| --- | --- | --- | --- | --- |
| I 契約與整合 | P0，先定 DTO 與 flags。各 stream 合入後最後接線 | backend/app.py、frontend/src/App.tsx、AppShell.tsx、api.ts、types.ts、appCommon.tsx、pmGlanceConfig.ts、integrationRoutes.ts、p2Routes.ts、p2RouteNames.ts、新增 shared feature contract | 其他 worker 的 module 及全部 CSS | session features、routes、topbar、disabled 落點與首屏只讀 shell 正常 |
| D 停用與資料真相 | P0，依 I flags contract | backend/workflow.py、operations.py、jobs.py、native_routes.py、native_poller.py、native_requests.py、sop_deadlines.py、sop_execution.py、policy.py、sop_contracts.py、ops_sync/routes.py、ops_sync/flags.py、frontend/src/Operations.tsx、OpsFlowPanel.tsx、NativeApprovalControls.tsx、ChangeConfirmationLines.tsx、新增 test_ux_disabled.py | backend/app.py、home/my_work、node_assignment、ProjectDetail、CSS、seed 與既有 fixtures | disabled mutation 無 side effects，production mock 不可見，隔離測試 opt-in 保留 |
| R 來源讀取與限流 | P1，核實 Base 特殊配額，依 I query DTO | backend/sources.py、live_read/client.py、live_read/rate_limit.py、live_read/coordinator.py、live_read/config.py、node_assignment/cache.py、node_assignment/lark_table.py、node_assignment/config.py、新增 test_ux_read_cache.py | backend/app.py、node_assignment/domain.py、operations.py、service.py、views.py、frontend 與 CSS | 投影、分頁、合併請求、跨身分快取、429 行為，沒有新增寫入 |
| H 工作與首頁 | P1，依 I DTO、D origin、R 讀取介面 | backend/home_queues.py、home_details.py、my_work.py、shell.py、workspace_projection.py、新增 backend/home_panels.py、frontend/src/DailyHome.tsx、IntegratedPages.tsx、MyWorkTable.tsx、myWorkView.ts、executableTasks.ts、新增 useHomePanels.ts、test_ux_home_panels.py | sources、live_read、App、ProjectDetail、NodeAssignments、CSS、shared DTO | N/T 全部指派含等待可讀，source origin 分開，停止申請不入 queue |
| C 案件與節點詳情 | P1，依 I deep link contract、R | frontend/src/ProjectDetail.tsx、NodeAssignments.tsx、useNodeAssignments.ts、nodeAssignmentApi.ts、backend/node_assignment/views.py、routes.py、frontend/src/DailyRecords.tsx、FileWorkspace.tsx、AuditTrail.tsx、新增 test_ux_assignment_projection.py | node_assignment service/operations/domain、app.py、Operations、home、CSS | 首頁 target 可定位 node/task，原流程權限與回讀不變，範本標示正確 |
| S 設定健康 | P1，依 I DTO 與 R metadata | 新增 backend/settings_overview.py、frontend/src/SettingsOverview.tsx、frontend/src/RuntimeHealthPanel.tsx、PeopleDirectoryPanel.tsx、SourceHealth.tsx、sourceHealthView.ts、backend/source_health.py、新增 test_ux_settings.py | Operations.tsx、App、backend/app.py、people_directory.py、CSS | member 有真實摘要，manager 有維護資訊，無 secret 或他人表洩漏 |
| P 各列表與管理視角 | P2，依 I query contract、R、H provenance | frontend/src/ProjectsList.tsx、CompanyCockpit.tsx、PmGlance.tsx、P2Pages.tsx、ConfirmationList.tsx、CaseDetail.tsx、ContractDetail.tsx、WorkItemDetail.tsx、managerOverviewView.ts、companyDashboardCache.ts、backend/company_dashboard.py、manager_overview.py、confirmation_list.py、新增 test_ux_table_sort.py | backend/app.py、App、home、ProjectDetail、CSS、DTO | 跨頁排序、null/數字日期處理、count 母體明確、P2 返回上下文 |
| G 純樣式 | P2，可在 I 定 class 後與後端並行 | frontend/src 全部既有 .css | 全部 .tsx/.ts/.py、package/lock、API、routes、permissions、mapping | Glass、buttons、spacing、dark、focus、reduced motion、fallback 通過視覺驗收，行為完全不變 |
| A 頭像載入 | P2，依 R 名冊與真實 host 核查 | frontend/src/Avatar.tsx、backend/avatar.py、新增 test_ux_avatar.py | 全部 CSS、people_directory、App、routes、所有業務授權 | 明確官方 host、URL 更新、lazy、固定 img 尺寸與錯誤回退，保持原姓名與身份 |
| V 驗證 | P3，依全部合入 | 新增 docs/UX_REDESIGN_VALIDATION.md、專用 e2e/ux-redesign.spec.ts 或依 repo 實際 test 目錄指定新檔 | 實作程式與既有 fixtures，不以改 expected 迴避問題 | 真實已授權登入驗證、cold/warm requests、停用深連結、匿名與多角色 |

部分 file names 為新建提案，若 repo 沒有同名模組，不新造平行 domain，先由 I 決定既有 owner 的位置。例如列表 endpoint 的查詢接線在 app.py，只能由 I 寫。S 的 SettingsOverview 要掛到 Operations 由 D 合入，D 只做 import 與 render，不能另寫 S 的內容。I 的所有接線採小 commit，其他 stream 回報明確 integration patch brief，由 I 實作，不能並行改 app.py 或 App.tsx。

先完成 P0 的 flag 與資料真相，避免新漂亮首頁放大舊假統計。再完成 R 與 H/C/S 的資料契約。G 可以平行做純視覺，但要移除 polish 反向覆寫。P 最後統一表排序與母體。V 要逐個 verifiable unit 檢查，不能等全部完成才發現兩套任務身份不相容。

## 13. 驗收與風險

驗收必須能證明以下行為。

- production 零任務只顯示零或已核實空態，不渲染 seed 人員、seed 案件或 fake approvals。
- N 有指派而 T 空表時，首頁仍能顯示節點責任。N 未指派時不因角色把節點算給本人。
- node status、source_status、derived_status 與審核狀態分開。S lookup 缺值不造成假的進度百分比。
- disabled nav、mobile tabs、hash alias、modal、action API、native API、queued digest 與 background apply 全部一致。任何停用 mutation 不產生業務寫入。
- settings 在 member、pm、manager 與 test/production 都有可理解內容或明確無權限說明。404 不造成整頁空白。
- 日期、數字與空值跨頁排序一致，query cursor 不可跨身份或篩選重用，欄位 projection 不搬入無需的財務人事資料。
- 頭像 lazy、fallback、URL 更新、slow network 正常。keyboard focus、200% zoom、手機 viewport、dark theme、reduced motion、無 backdrop-filter 都可操作。

| 風險 | 影響 | 處理 |
| --- | --- | --- |
| 任務 T 目前零筆 | 無法核實現行非空 task response 與 deadline 使用方式 | 使用 metadata 契約，未來隔離資料做真實形狀驗收，不能寫正式測試任務 |
| N 截止日是 max(T) | 節點最後期限與下一件最急期限可能不同 | deadline 與 next_due 分列，缺值不猜 |
| FORMAL_DUE_FIELDS 為空 | 新首頁與舊 my-work 的期限顯示不一致 | 先核實 T 對應與 provenance。L 舊日期不自動升格為正式期限 |
| 案號文字可能不唯一 | 錯開案件或跨案誤配 | 用 base/table/record relation 及穩定 case ID，mapping ambiguity 明示 |
| 本地 SOP 與 Lark 任務並存 | 重複工作與虛增完成率 | origin 與 count grain 分開，無實例定義不入首頁工作 |
| 停用現有 frozen change | 案件可能繼續等待，不能自動解凍 | 顯示歷史原因，保留 audit。處理方式需擁有人產品決定 |
| mock flag 啟於正式環境 | 假名冊、核准人或日期可能出現 | production server gate，不只 UI notice |
| Base 特殊 per-table quota 未明列 | 不能把端點 20 QPS 當每表可額外獨立使用的配額 | Search、Batch get、List 的 20 已核，實際租戶特殊限制再確認，採 conservative shared limits |
| 快取跨 scope | 權限調整後仍露出舊資料 | cache key 加 authz version，每次讀入站授權，403 清除敏感快照 |
| stale counts 被看成現況 | 管理決策建立在過期資料 | 每面板顯示資料時間與完整性，unknown 不顯示零 |
| CSS 多檔覆寫 | Glass 無效、頭像變形、按鈕 contrast 失敗 | G 單一 owner 與 token aliases，先處理 polish 尾段 |
| 大表 blur 與多層 fixed glass | 手機 GPU 記憶體與捲動成本 | flat tables、有限外層 blur，驗收 low-power 裝置 |
| staging 無登入與部署版本未核 | 無法證明設定空白根因或實際速度 | 文件明列限制，V 用授權帳號驗收，不將靜態推論寫成實測 |

## 14. 擁有人真正需要決定的產品問題

1. 多人同任 N 節點責任是否每人都算一項節點責任，還是要指定一位主責。本文預設每位在該欄位者都看得到，任務完成權限仍由原規則決定。
2. 暫停期間已送審且凍結中的變更，是否保留凍結直到另行人工處理。本文預設保留，不取消外部審批，不自動恢復。
3. 本地已實體化且明確指派的 SOP 工作是否繼續出現在首頁，或首頁只保留 N/T。本文預設保留但分來源，不重複計數，也不聲稱為 Lark 任務。
4. 公司駕駛艙與管理總覽是否保留兩個導覽項目。本文保留兩者，前者看全局來源狀況，後者處理案件歸屬與確認單版本。
5. 無明確期限的任務是否仍容許開始作業。本文只改善顯示，不改原執行規則，將「未排期限」獨立提示。

欄位名稱、API 可用性、角色 gate、QPS、設定頁 network failure 都是工程可查事實，不列作擁有人問答。這份文件不要求先回答所有產品問題才能完成資料來源與停用工作。
