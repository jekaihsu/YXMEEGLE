# AI 助理（問進度、問出勤、用量儀表板）

這份文件是前後端共同遵守的合約。實作若要改合約，先改這裡。

## 範圍

- 同事用自然語言查詢：今天誰沒到、誰遲到、某案件進度、某案件負責人。
- 助理只能看到發問者本人原本就看得到的資料。
- 模型只有兩個選項：`claude` 與 `gpt`。使用者不能選型號或 effort。
- 每次提問都記錄 token 用量與費用。儀表板只能用網址 `/token_dashboard` 進入，導覽列沒有按鈕，僅 `manager` 角色可看。
- 預設保存最後一則問題與串流回答，供主管調整提示詞。內容經遮蔽且有保存期限。

## 模型目錄（伺服器端固定，前端不能覆寫）

| id | 供應商 | 型號 | effort | 單價（USD / 百萬 token） |
| --- | --- | --- | --- | --- |
| `claude` | Anthropic | `claude-sonnet-5-5` | `medium` | 輸入 2.00，快取讀取 0.20，快取寫入 2.50，輸出 10.00 |
| `gpt` | OpenAI | `gpt-6.1-terra` | `medium` | 輸入 1.00，快取讀取 0.05，輸出 5.00 |

GPT 單價來自第三方報導（2026-10-31 查詢），尚未對照 OpenAI 官方價目頁。單價放在可由環境變數覆寫的表內，並帶 `price_version`。型號沒有單價時，費用記為 `NULL`，儀表板顯示「未計價」，不自行猜測。

環境變數：`ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`AI_PRICE_TABLE_JSON`（選用，覆寫單價）、`AI_DAILY_TOKEN_LIMIT_PER_USER`（預設 400000）。沒有金鑰的供應商在 `/api/ai/models` 顯示 `available:false`。

## 資料形狀

`ai_usage` 一列代表一次使用者提問（含多步工具迴圈的總和）。

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `id` | str PK | uuid |
| `created_at` | datetime UTC | |
| `day` | str `YYYY-MM-DD` | 以 Asia/Taipei 切日，建索引 |
| `workspace_id` | str | |
| `actor_id` | str | 登入者 open_id（`user['id']`），建索引 |
| `actor_name` | str | 寫入時的姓名快照 |
| `conversation_id` | str | 前端產生 |
| `provider` | str | `claude` / `gpt` |
| `model` | str | 實際型號 |
| `effort` | str | |
| `scope` | str | `global` / `project`，既有列預設 `global` |
| `project_id` | str NULL | 案件範圍的案件 id |
| `input_tokens` | int | 含快取在內的輸入總量 |
| `cache_read_tokens` | int | `input_tokens` 的子集 |
| `cache_write_tokens` | int | `input_tokens` 的子集 |
| `output_tokens` | int | 含推理 token |
| `cost_micro_usd` | int NULL | 百萬分之一美元，NULL 表示未計價 |
| `price_version` | str | |
| `steps` | int | 模型呼叫次數 |
| `tool_calls` | int | |
| `latency_ms` | int | 全程 |
| `first_token_ms` | int NULL | 第一個文字 delta |
| `status` | str | `ok` / `error` / `aborted` |
| `error_code` | str NULL | |

## HTTP 合約

所有路徑都走既有 session cookie 與 `identity(request)`。

### `GET /api/ai/models`

```json
{ "default": "claude",
  "models": [ { "id": "claude", "label": "Claude", "available": true },
              { "id": "gpt", "label": "GPT", "available": true } ] }
```

### `POST /api/ai/chat`

請求：

```json
{ "model": "claude", "conversation_id": "c-123",
  "messages": [ { "role": "user", "content": "今天誰遲到？" } ] }
```

限制：`model` 必須是 `claude` 或 `gpt`；最多 20 則訊息，`user` 每則最多 4000 字，`assistant` 每則最多 20000 字；最後一則必須是 `user`。多餘欄位一律 422。

回應 `text/event-stream`，每個事件一行 `data: <json>` 加空行。型別如下。

| type | 欄位 | 說明 |
| --- | --- | --- |
| `start` | `conversation_id`, `provider`, `usage_id`, `scope` | |
| `tool` | `id`, `name`, `label`, `status` = `running` / `done` / `error` | `label` 為給使用者看的繁體中文，如「查詢今天出勤」 |
| `text` | `delta` | 答案文字片段 |
| `done` | `usage: {input_tokens, output_tokens}`；`manager` 另含 `cost_usd` | 結束 |
| `error` | `code`, `message`，僅 manager 可收到選填 `detail` | `ai_unconfigured`、`ai_quota`、`ai_busy`、`ai_upstream`、`ai_forbidden` |

錯誤事件之後串流結束。配額與設定錯誤在串流開始前以 HTTP 狀態回傳（503 `ai_unconfigured`、429 `ai_quota` / `ai_busy`），本文為 `{ "code", "message" }`。

### `GET /api/ai/usage`（僅 `manager`，其他人 403）

查詢參數：`from`、`to`（`YYYY-MM-DD`，含頭尾，預設近 30 天，含頭尾最多 366 天，超過回傳 422）、`actor`（`actor_id`，可省略）、`provider`（可省略）、`scope`（`global` 或 `project`，省略為全部）。

```json
{ "range": { "from": "2026-10-01", "to": "2026-10-31" },
  "totals": { "questions": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "unpriced_calls": 0 },
  "by_person": [ { "actor_id": "", "name": "", "questions": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "unpriced_calls": 0, "last_at": "ISO" } ],
  "by_day": [ { "day": "2026-10-31", "questions": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0 } ],
  "by_provider": [ { "provider": "claude", "questions": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "unpriced_calls": 0 } ],
  "people": [ { "actor_id": "", "name": "" } ],
  "recent": [ { "created_at": "ISO", "actor_id": "", "name": "", "provider": "claude", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "latency_ms": 0, "status": "ok" } ] }
```

`scope` 篩選套用於所有聚合、評分原因、people 與 recent；recent 每列含 scope。`people` 不受 `actor` 篩選影響，供下拉選單使用。`recent` 最多 50 筆，依時間新到舊。`cost_usd` 是各列 `cost_micro_usd` 加總除以 1,000,000；`NULL` 列不計入並累加到 `unpriced_calls`。

## 權限原則

工具不直接讀資料庫。每個工具以發問者本人的 cookie，從行程內呼叫既有唯讀 API（ASGI transport）。可見性、遮蔽、`HR_VIEWERS` 等規則因此只有一份實作。工具回傳在送給模型前先裁成小而必要的欄位，不含金額。

## 工具（v1，全部唯讀）

| 工具 | 底層既有 API | 回傳重點 |
| --- | --- | --- |
| `search_cases` | `GET /api/projects?q=` | 最多 8 筆案件 id、編號、名稱、狀態、PM id、到期日及總筆數；來源有 `as_of` 時保留 |
| `case_progress` | `GET /api/projects/{id}/progress` | 階段與 `basis` 證據強度、節點完成數與百分比、`as_of`、缺口 |
| `case_owners` | `GET /api/case-detail/{id}` 與啟用時的節點指派 API | PM id 與姓名；無姓名為 `name_unavailable`；案件來源時間為 `as_of`，節點指派讀取時間另列 `node_assignments_as_of`，缺少時間時省略欄位；節點未啟用、無權限或讀取失敗時 `nodes:null` 並明示 `node assignment data unavailable` |
| `attendance_today` | `GET /api/people/attendance` | 今天（Asia/Taipei）的遲到、早退、缺卡、免打卡、補卡／修正、請假／出差／外出、無紀錄名單，加 `as_of` 與資料是否完整 |

出勤只有「遲到、缺卡、請假、出差、外出、到班」等證據標籤，沒有明確的缺勤判定。助理必須說「尚無打卡紀錄」，不可斷定「缺席」。

## 執行與資料限制

每日配額與每人同時兩個提問是軟限制。併發限制只在單一 web process 內有效；每日用量讀取 ledger，但檢查與寫入不保留額度，多個 process 或同時請求可能超額。

整題期限預設 120 秒，可用 `AI_QUESTION_TIMEOUT_SECONDS` 設定。逾時回傳 `ai_upstream` 並說明逾時。中止、錯誤或逾時且該步無最終用量時，以序列化 system、tools、messages 字數除二向上取整估算輸入，以已串流文字字數估算輸出；不低於已有用量。保留供應商已回報的快取讀取與寫入量，只將輸入估算的不足量加到未快取輸入。中止或沒有既有錯誤碼時，ledger 的 `error_code` 為 `usage_estimated`；錯誤或逾時保留原有錯誤碼。費用照估算量計算。先釋放併發名額，再於背景執行緒寫入 ledger；寫入不受請求取消影響，失敗重試一次，每題僅一列。

中止與錯誤時的 token 估算只是近似值，不含隱藏推理 token，且可能高估精簡輸入。每日配額是軟限制，不是供應商費用的硬上限。

模型回答仍可能包含使用者可點擊的外部連結，這是殘餘風險。前端永不渲染圖片。

兩個模型輸出上限皆為 16000 token，含推理。因長度截斷時仍是 `ok`，最後追加「（回答太長，已截斷）」。

所有 `/api/ai/*` 權限拒絕均為 HTTP 403 的 `{code:"ai_forbidden", message}`。不擴大 tenant 讀取 allowlist。

`by_person`、`by_provider` 亦回傳 `unpriced_calls`。姓名取查詢範圍內該人最新一列，不取字典排序最大值。

`attendance_today` 的 `labelled_arrival_count` 只計算標籤「到班」，不代表實際在場人數。`early_leave`、`exempt`、`supplemented` 分別為早退、免打卡、補卡／修正。任何人無紀錄均為 `incomplete:true`。工具過長時刪除完整項目並回傳 `truncated:true`，助理必須說明名單僅部分資料。`basis=rule` 是規則推導，不代表經查證完成。

上游錯誤的 `detail` 僅提供給 `role == "manager"` 的提問者，與 `done.cost_usd` 使用相同權限判斷。例如 `OpenAI 404 model_not_found`。其他角色不會收到此欄位。`detail` 最多 200 字元，僅含供應商、HTTP 狀態及已清理的錯誤代碼或類型。伺服器以單行 warning 記錄供應商、模型、步數、耗時、例外類別、HTTP 狀態、上游代碼、類型、參數、request id、最後事件類型及最多 200 字元的清理後訊息。清理會遮蔽已知的提示詞、工具資料、金鑰及 bearer token。

兩個供應商均停用 SDK 自動重試，並使用明確的 HTTP timeout。connect、write、pool 各 10 秒，read 為 60 秒，整題仍受 120 秒期限限制。OpenAI 回報 `input_tokens_details.cache_write_tokens` 時，若模型目錄有大於零的快取寫入單價，會拆分並按該單價計費；否則歸入未快取輸入，輸入總量不變。

### 案件脈絡建置錯誤

| 情況 | HTTP | code | 行為 |
| --- | --- | --- | --- |
| 基本案件路由 401、403、404 或案件不存在 | 403 | ai_forbidden | 相同的拒絕本文，不洩漏案件存在與否 |
| 基本案件路由 5xx、逾時或非預期例外 | 503 | ai_upstream | 可重試，顯示「助理暫時無法回答，請稍後重試」 |

兩種建置失敗都發生在模型呼叫及帳本註冊之前，因此沒有模型呼叫與 ledger 列。503 產生結構化 warning `ai_context_failed`，只含案件 id 雜湊、狀態碼、例外類別與耗時，不含 cookie 或內容。次要區段不可讀時仍以 unavailable 交代缺口。

## 部署

啟動時會自動補齊 `ai_usage` 在首次部署後新增的 `scope` 與 `project_id` 欄位。既有資料的 `scope` 預設為 `global`，`project_id` 為 `NULL`。`scripts/migrate_ai_usage.py` 仍可作為選用的手動遷移工具。

執行真實 PostgreSQL 回歸測試（需非 root 帳號及 PostgreSQL 工具）使用 `PATH=/opt/homebrew/bin:$PATH /tmp/ai-backend-venv/bin/python scripts/test_action_audit_postgres.py --ai`。runner 建立暫存 cluster、私有 Unix socket 與隨機 port，結束時清除。測試逐一隔離 schema，同時執行 SQLite 與 PostgreSQL，並比較相同資料的用量 JSON。整個後端測試使用相同命令加上 `backend -q -ra`。未設 `AI_TEST_POSTGRES_URL` 的一般 pytest 會明確跳過 PostgreSQL 案例。


## 問答內容與提示詞調整

`AI_STORE_CONTENT` 預設為 `true`，在啟動時解析並保存於 app.state。去除前後空白並轉為小寫後，`true/1/yes/on` 啟用，`false/0/no/off` 停用。其他值一律停用並記錄啟動 warning，設定修改後需重新啟動。`ai_exchange` 以 `usage_id` 對應每題用量，只保存最後一則使用者訊息，最多 4000 字元，以及串流處理時累積的助理文字，最多 20000 字元。最後一個 delta 會先累積再嘗試送出，因此失敗或中止時，保存的部分回答可能包含尚未送達使用者的最後一段。另保存 workspace、actor、時間、工具名稱清單，以及主管可見的已清理上游錯誤摘要，例如 `OpenAI 401 invalid_api_key`。不保存工具參數、工具結果、system prompt、案件脈絡 JSON、較早對話、cookie、金鑰或 displays。回答若引用工具資料，引用文字會是回答的一部分。

保存前會移除 NUL 與其他控制字元，保留換行與 tab。請求訊息含 NUL 時直接回傳 422。遮蔽規則涵蓋有單字邊界且後綴至少 16 字元的 `sk-` 金鑰、JWT (`eyJ...`)、Google (`AIza...`)、GitHub (`ghp_...`)、Slack (`xox[bapr]-...`)、`password=`、`token=`、`secret=` 的值、Bearer token、台灣手機號碼（可含空白或連字號）、身分證字號形狀（`[A-Z][12]\d{8}`）、至少 13 位連續數字及四組四位數卡號。9 至 12 位訂單號與 PO 號保留，但符合手機或身分證形狀者仍遮蔽。`risk-based`、`task-force`、`disk-usage` 等一般文字保留。這些規則只比對文字形狀，不驗證證號或卡號，也無法辨識所有秘密與個資。格式不同可能漏遮，符合形狀的普通文字也可能誤遮。

只有同一 workspace 的主管可透過 usage API 讀取內容。一般成員收到 403。明細對不存在或其他 workspace 的 usage_id 一律回傳相同 404。`AI_STORE_CONTENT=false` 停止新增內容，且所有 usage API 隱藏既有內容，文字欄位為 null，工具清單為空。

`AI_CONTENT_RETENTION_DAYS` 在啟動時驗證為非負整數並保存於 app.state，預設 90 天。無效、空白或負值會退回 90 並記錄 warning。依 UTC created_at 計算期限，過期內容立即從讀取結果隱藏。寫入完成並通知 feedback 等候者之後，背景執行緒清除過期內容；讀取 usage（含 export）時也觸發清理。每個 process 成功清理後一小時內不再執行，失敗可重試。每批最多刪除 500 筆，各批獨立交易，刪除期間不持有排程鎖。停用內容保存時，以 0 天期限清除所有既有內容，仍受每小時限制。用量及評分仍保留。啟動時 `ledger.ensure_schema` 自動建立 `ai_exchange`，既有資料庫不需手動遷移。用量先以獨立交易寫入，失敗重試一次；內容再用另一個交易寫入並獨立捕捉失敗，因此內容問題不會回滾用量。

`GET /api/ai/usage` 的 recent 新增 `usage_id`、`question_preview`、`answer_preview`、`tools`、`error_detail`。preview 最多 120 字元，沒有內容或關閉保存時為 null。新增 `q` 查詢參數，最多 200 字元，以不區分大小寫的文字子字串比對問題或回答。`%`、`_`、反斜線都當作一般文字。`q` 與 actor、provider、rating、scope、from、to 可同時使用，也套用到聚合。

`GET /api/ai/usage/{usage_id}/exchange` 回傳 `usage_id, created_at, actor_id, name, provider, scope, project_id, status, rating, reason, question, answer, tools, error_detail, latency_ms, input_tokens, output_tokens, cost_usd`。

`GET /api/ai/usage/export` 使用相同篩選，依時間新到舊回傳最多 500 筆 JSON lines。每列只有 `usage_id, created_at, name, provider, scope, rating, reason, question, answer, tools`。內容類型為 `application/x-ndjson`，供主管挑選好壞回答並調整提示詞。匯出不計算 totals 或 by_* 聚合。`X-Export-Truncated` 回應標頭為 `true` 或 `false`，`X-Export-Row-Count` 為實際匯出的資料列數（不含 metadata）。結果超過 500 筆時，最後額外附上一行 `{"truncated":true,"limit":500,"row_count":500}`；消費端需辨識這一行 metadata，整份回應仍為有效 JSONL。

## Dataset registry 與依問題選擇呈現

全域對話模型現在只收到四個工具。舊有四個查詢名稱成為 dataset id，原來的讀取與投影沿用，不重複註冊模型工具。舊 execute 入口僅保留既有測試及內部相容用途。案件對話保持一次模型呼叫、零工具，以及原有預建脈絡。

`backend/ai/datasets.py` 的 Dataset registry 定義 id、標題、用途、Pydantic 嚴格參數模型、既有路由讀取函數、欄位白名單投影、欄位 metadata 與範例。模型提示詞只加入短用途索引，不放資料。所有資料讀取透過行程內 ASGI HTTP，傳入發問者 cookie。既有路由的權限、公司 workspace 與功能開關仍生效。401/403/404 一律回傳工具錯誤 `{"code":"ai_forbidden","error":"找不到或沒有權限查看資料"}`。不直接讀業務資料庫，不呼叫寫入路由。

| dataset id | 既有讀取路由 | 可回答 |
| --- | --- | --- |
| search_cases | /api/workspace 或 /api/projects?view=portfolio | 案件關鍵字、PM、狀態、逾期與分頁 |
| case_progress | /api/projects/{id}/progress、case-detail、既有指派與 SOP 讀取 | 完成／剩餘工作、階段證據、缺口 |
| case_owners | /api/case-detail/{id}、啟用時 node-assignments | PM 與節點負責人 |
| attendance_today | /api/people/attendance | 單日、指定週出勤標籤與排名 |
| report_review | /api/reports/review/rows | 日期、人員、案件與審核狀態 |
| report_sales | /api/reports/sales | 案件、業主、PM、狀態，不含金額 |
| report_progress | /api/reports/progress | 計畫量、完成量、剩餘量 |
| report_assets | /api/reports/assets | 車輛、儀器、使用次數、閒置天數，不含租金 |
| report_contacts | /api/reports/contacts | 人員聯繫日期、案件、跟進日與狀態 |
| contract_detail | /api/contract-detail?key= | 合約項目名稱、項次，不含財務與原始欄位 |
| dispatch_board | /api/v2/dispatch/board | 日期區間、組別、案名與派工狀態 |
| daily_reports | /api/daily-reports | 人員、日期、案件的日報紀錄 |
| sop_tasks | /api/projects/{id}/sop-tasks | 案件／節點 SOP 任務、適用性與逾期 |
| node_detail | /api/projects/{id}/node-assignments/nodes/{key} | 節點任務、負責人與期限 |

模型工具合約如下。

```json
{"name":"list_datasets","arguments":{}}
{"name":"describe_dataset","arguments":{"id":"report_assets"}}
{"name":"query_dataset","arguments":{"id":"report_assets","params":{"kind":"vehicle"},"limit":20,"offset":0}}
```

list 回傳 datasets 的 id、title、description 與參數名稱。describe 回傳完整 JSON schema、columns、example。query 的 params 是物件，拒絕額外欄位、錯誤型別與無效日期。limit 為 1–50，offset 為 0–100000。describe 的 schema 為各資料集唯一參數依據。

```json
{"dataset_id":"report_assets","result_id":"r0123456789abcdefabcd","columns":[{"name":"name","label":"名稱","type":"text"},{"name":"uses","label":"使用次數","type":"number"}],"rows":[{"name":"車1","uses":4}],"total":1,"totals":{"rows":1},"next_offset":null,"as_of":null,"truncated":false,"limitations":["金額與財務欄位不提供"]}
```

欄位 type 為 text|number|date|status。既有四個資料集另有 summary，保留原來的出勤人數、分母、流程證據與不可用狀態。result_id 由查詢與結果內容決定，同一題可重用。查詢結果只在該題的結果池中可用，不跨使用者共用。來源時間不可得時 as_of=null，不以請求時間冒充來源時間。報表快照的 stale 與缺口保留於 limitations。來源空值與部分資料不可解讀為沒有。

```json
{"name":"show_display","arguments":{"result_id":"r0123456789abcdefabcd","kind":"bar","columns":[],"mapping":{"x":"name","y":"uses"},"max_rows":24}}
```

kind 為 table|bar|line|pie|stat。columns 僅選表格欄位，最多 8 欄；空陣列使用前 8 欄。mapping 可用 x/y/series/label/value，所有值必須存在於該結果的欄位。圖表數值軸必須為 number 且為有限數值，pie 不接受負數。表格最多 50 列，bar/line 最多 24 點，pie 最多 12 點，stat 最多 1 點。不隱式聚合或補零。

show_display 的 SSE tool done 事件附 displays。表格沿用 `{kind:"table", title, columns:[{key,label}], rows, truncated}`。其他呈現回傳 `{kind:"bar"|"line"|"pie"|"stat", title, result_id, points:[{label,value,series?}], truncated, as_of, limitations}`。模型自己選擇呈現方式，不自動顯示預設圖表。前端不得顯示工具狀態晶片，工具事件只用於思考狀態及回傳的 displays。

每題最多 7 次模型呼叫，足夠 discover → describe → query → 第二次 query → display → answer。相同工具與參數在題內快取，不同讀取維持併發，讀取仍有 15 秒上限。params 與 mapping 有動態結構，因此 query_dataset/show_display 的供應商 strict=false；伺服器仍嚴格驗證所有參數與呈現欄位。其餘工具沿用 strict=true。

不支援月營收趨勢，既有業務路由沒有可用月份維度，且金額與財務禁止輸出。不支援合約即將到期清單，現有合約項目路由沒有合約到期日。日報只使用既有索引，沒有新增逐筆來源全文讀取。沒有新增 SOP 寫入、ensure、preview 或匯入路由。回答缺少資料時直接說沒有這項資料。

## 個人對話歷史

完整 HTTP request/response 範例見 [AI_HISTORY_API.md](AI_HISTORY_API.md)。每個已登入使用者可列出、讀取及刪除自己的全域／案件對話，不需主管權限。actor 與 workspace 都限制查詢與刪除。主管用量及 exchange API 的原有權限不變。

以 ai_usage.conversation_id 分組並 join ai_exchange，無 schema 變更。標題使用第一則保留問題，壓縮空白、最多 60 字；活動時間倒序，游標使用時間與 ID。停用內容保存時 list 的 history_available=false 且 items=[]，detail 為 404。保留期外內容立即隱藏。刪除僅移除 ai_exchange，不動用量及評分。

續聊沿用 conversation_id，client 傳入之前的 messages；server 不另外注入歷史。同一 caller 的 conversation_id 不可變更 scope/project，衝突為 422。不同 caller 的同名 ID 分開處理。

## 離線驗證

`python -m pytest backend/test_ai_*.py -q` 包含 registry 驗證、新資料集來源形狀投影、403/404、SSE discover/describe/query/bar，以及 history 分頁、續聊、刪除、actor/workspace、停用內容與保留期測試。

`python -m pytest backend/test_ai_question_eval.py -q` 的 18 個繁體中文問題逐題走 scripted provider 的 list → describe → query → answer，涵蓋逾期案件、我的案件、案號搜尋、負責人、未完成工作、今天出勤、週排名、退回審核、業務 PM、週進度、車輛、儀器、聯繫、日報、派工、SOP、節點明細及合約項目。另有月營收及合約到期兩個明示不支援的檢查。這驗證工具與目錄合約，不測量真實模型的自然語言選擇準確率，也不聲稱連線至正式 Lark 資料。

本分支驗證紀錄（2026-11-01）。一般 AI suite 為 322 passed、181 skipped。使用 `PATH=/opt/homebrew/bin:$PATH /tmp/ai-backend-venv/bin/python scripts/test_action_audit_postgres.py --ai` 後，SQLite 與 PostgreSQL 合計 501 passed、2 skipped；各資料庫 179 passed，其他單元測試 143 passed。兩個跳過項目都是 frontend parity 缺 esbuild，沒有修改前端安裝。離線 question eval 為 20 passed、18 skipped（未設定 PostgreSQL URL 的單獨執行）；PostgreSQL runner 已包含這些案例。正式供應商與正式 Lark 資料未連線驗證。

資料集參數修正（2026-11-01）。`daily_reports` 不接受 actor_id，人名使用 `q`。`search_cases` 提供 `id`，供案件明細的 `case_id` 與日報 `project_id` 使用。`contract_detail` 以 `case_id` 查授權案件明細的合約項目名稱與項次，不再要求模型填不透明的合約 key。節點參數使用 enum，不能自行編造 ID。進度週報僅提供預排、出工、符合預排與未預排的天數，不提供任何營業額點數或衍生比率。

資料集查詢合約。`query_dataset` 的 `limit` 預設 20，`offset` 預設 0。整個回傳 JSON 以約 6000 字元為上限，超出時裁切 rows，更新 truncated 與 next_offset。舊的重複 summary 不再回傳。每次查詢回傳 applied_params，包含實際採用的預設週一、日期範圍、分頁與篩選條件。describe_dataset 提供參數限制、非空查詢範例及欄位說明。路由 4xx 驗證失敗回傳 `{"error":"參數錯誤","detail":"路由訊息"}`；401/403/404 維持 ai_forbidden，5xx 與逾時標記 retryable。模型只能呼叫當前 scope 提供的工具。

本輪驗證（2026-11-01）。`/tmp/ai-backend-venv/bin/python -m pytest backend/test_ai_*.py -q` 為 341 passed、192 skipped。獨立離線 question eval 為 20 passed、18 skipped。新增 19 個通過的回歸案例，涵蓋真實週報計算的財務欄位阻擋、資料集欄名守衛、延後寫入與刪除、done 可見性、最新 200 則訊息、路由錯誤、實際參數、描述與 opaque ID、長度與分頁、未開放工具、各種顯示標題及 PM 標籤。未設定測試 PostgreSQL URL，未宣稱本輪執行 PostgreSQL 案例。
