# AI 助理（問進度、問出勤、用量儀表板）

這份文件是前後端共同遵守的合約。實作若要改合約，先改這裡。

## 範圍

- 同事用自然語言查詢：今天誰沒到、誰遲到、某案件進度、某案件負責人。
- 助理只能看到發問者本人原本就看得到的資料。
- 模型只有兩個選項：`claude` 與 `gpt`。使用者不能選型號或 effort。
- 每次提問都記錄 token 用量與費用。儀表板只能用網址 `/token_dashboard` 進入，導覽列沒有按鈕，僅 `manager` 角色可看。
- 不記錄問題與回答的內容，只記錄用量。

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
| `error` | `code`, `message` | `ai_unconfigured`、`ai_quota`、`ai_busy`、`ai_upstream`、`ai_forbidden` |

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
