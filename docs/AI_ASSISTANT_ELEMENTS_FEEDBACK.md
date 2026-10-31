# AI 助理：結構化結果與回覆評分

這份文件補充 `docs/AI_ASSISTANT.md`。範圍是兩件事：用 assistant-ui 的 elements（data-table、chart 等）呈現工具回傳的結構化資料，以及讓使用者對每則回覆按讚或倒讚，並在 `/token_dashboard` 顯示。

## 設計原則

- 表格與圖表由伺服器依「已投影、已通過權限的工具結果」產生，與模型看到的資料同一份、不會更寬。模型不負責排版這些資料。
- 模型的文字回答只摘要重點，不重複貼整張表。這同時讓輸出更短、回答更快。
- 不儲存問題與回答內容。評分只記 `usage_id`、評分人、評分值與選填的原因代碼。
- 前端不引入 Tailwind 或 shadcn。assistant-ui elements 的原始碼只當作參考，移植成本專案 design tokens 的純 CSS。

## SSE 事件變更（`POST /api/ai/chat`）

`start` 增加 `usage_id`：本次提問在 `ai_usage` 的列 id，由伺服器在串流開始時產生，並於 `finish` 寫帳時沿用。前端以它來送評分。

`tool` 事件在 `status` 為 `done` 時可附 `displays`（陣列，可省略）。每個元素是下列聯集之一。

```json
{ "kind": "table", "title": "今天遲到與未打卡", "caption": "截至 09:30",
  "columns": [ { "key": "name", "label": "同事" }, { "key": "state", "label": "狀態" } ],
  "rows": [ { "name": "王小明", "state": "遲到" } ],
  "rowKey": "name", "truncated": false, "note": "尚無打卡紀錄不代表缺席" }
```

```json
{ "kind": "chart", "title": "今天出勤標籤", "variant": "bars", "unit": "人",
  "headline": { "label": "有紀錄", "value": "38" },
  "points": [ { "label": "到班", "value": 31 }, { "label": "遲到", "value": 2 } ] }
```

限制：每個 `table` 最多 8 欄、50 列；每個 `chart` 最多 12 個點；格值為字串、數字或 null；`truncated` 為 true 時前端顯示「僅列出部分」。`displays` 一律由伺服器從投影後的工具結果建立，不使用模型輸出。

各工具的 displays：

| 工具 | displays |
| --- | --- |
| `search_cases` | 表格：案號、案名、狀態、PM、交期 |
| `case_owners` | 表格：職務或節點、負責人；節點指派不可用時以 `note` 說明 |
| `case_progress` | 長條圖：各階段完成百分比，`headline` 為整體百分比與資料基礎（規則推算或來源證據） |
| `attendance_today` | 長條圖：各出勤標籤人數；表格：非「到班」的同事與其標籤 |

## 評分

### `POST /api/ai/feedback`

```json
{ "usage_id": "…", "rating": "down", "reason": "wrong" }
```

- `rating`：`up`、`down` 或 `none`（取消）。
- `reason`：僅 `down` 可帶，選填，限 `wrong`（答錯）、`incomplete`（不完整）、`slow`（太慢）、`other`。
- 只有該提問本人可以評分；其他人或不存在的 `usage_id` 回 404。帳列可能尚未寫入，伺服器最多等待 3 秒再判定不存在。
- 對同一 `(usage_id, actor_id)` 重複送出是覆寫，不會累加。`none` 刪除該列。
- 回應 200：`{ "usage_id": "…", "rating": "up", "reason": null }`。
- 需要和 `/api/ai/chat` 相同的登入與准入規則。

### 資料表 `ai_feedback`

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `usage_id` | str | 與 `ai_usage.id` 對應，與 `actor_id` 組成主鍵 |
| `actor_id` | str | 評分人，必須等於該列的 `actor_id` |
| `rating` | int | `1` 或 `-1` |
| `reason` | str NULL | |
| `created_at`, `updated_at` | datetime UTC | |

## `GET /api/ai/usage` 變更

僅 `manager`，與原本相同。新增查詢參數 `rating`（`up`、`down`、`none`，省略為全部）。新增欄位：

- `totals.feedback`：`{ "up": 0, "down": 0, "rated": 0, "up_rate": 0.0 }`，沒有評分時 `up_rate` 為 null。
- `by_person`、`by_provider`、`by_day` 每列增加 `up`、`down`。
- `recent` 每列增加 `rating`（`up`、`down` 或 null）與 `reason`。
- `reasons`：`{ "wrong": 0, "incomplete": 0, "slow": 0, "other": 0, "unspecified": 0 }`（區間內倒讚原因分佈；`unspecified` 為未填原因，總和等於 `totals.feedback.down`）。

## 儀表板呈現

- KPI 增加「滿意度」：`up_rate` 與 👍／👎 數，無評分時顯示「尚無評分」。
- 依人與依供應商的表格增加 👍／👎 欄；供應商區塊直接比較 Claude 與 GPT 的滿意度。
- 最近提問增加評分欄；可用 `rating` 篩選只看倒讚。
- 倒讚原因分佈以小型長條圖顯示。
- 因為不儲存內容，管理者看不到倒讚對應的問題文字，只能看到人、時間、供應商與耗時。若之後需要內容，要另行決定並取得使用者同意。

## 伺服器查詢與顯示語意

查詢在 PostgreSQL 使用 REPEATABLE READ，在 SQLite 明確 BEGIN，讓姓名、總計與分組共用同一份快照。
`rating` 篩選先限制提問集合，再計算 totals、by_person、by_provider、by_day、recent 與 reasons。
`none` 表示沒有評分列，包含功能上線前的帳列。people 仍不受 actor 篩選影響，但遵守日期、provider、rating 篩選。
評分每個 workspace 與使用者每分鐘最多 60 次提交，超過回 429；此限制在單一 web process 內有效。

進度圖使用已投影的階段與節點資料。節點有 percent 時使用該值；否則已完成為 100，已知且未完成為 0，未知階段不畫點。
整體百分比為已知階段百分比的算術平均，是衍生摘要，不是來源提供的整案完成率。
headline 明示已知階段平均、規則推算或來源證據，以及未知階段數，避免把未知視為零。
出勤同事可有多個標籤；人數是投影後名單中的標籤計數。名單截斷時圖表亦標示 truncated。
顯示格值字串最多 240 字；表格超過上限時刪除完整列。顯示只從送給模型的最終投影產生。

部署時重跑 `python scripts/migrate_ai_usage.py`，會以 additive migration 建立 ai_usage 與 ai_feedback，保留既有資料。
