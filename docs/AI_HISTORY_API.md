# AI history HTTP contract

All requests use the session cookie. Every read and deletion is scoped to caller actor and workspace, including managers. Responses use `Cache-Control: no-store`. Content is redacted and retention-filtered.

## List

`GET /api/ai/conversations?scope=global&limit=30&before=<cursor>`

`scope` defaults to global, accepts global|project. Optional `project_id` filters project history. `limit` is 1–100, default 30. `before` is the opaque next_cursor from a previous response. Invalid cursors return 422. Order is latest retained activity then ID descending. Titles use the first retained question, whitespace collapsed, maximum 60 characters. Turns count retained exchanges.

```json
{"history_available":true,"items":[{"id":"chat-1","title":"這週誰遲到？","scope":"global","project_id":null,"updated_at":"2026-11-01T03:00:00+00:00","turns":2}],"next_cursor":null}
```

Disabled storage returns `{"history_available":false,"items":[],"next_cursor":null}`. Enabled empty history returns history_available=true.

## Read

`GET /api/ai/conversations/chat-1`

```json
{"id":"chat-1","title":"這週誰遲到？","scope":"global","project_id":null,"messages":[{"role":"user","content":"這週誰遲到？","at":"2026-11-01T03:00:00+00:00","usage_id":"usage-1"},{"role":"assistant","content":"王小明有一次遲到。","at":"2026-11-01T03:00:00+00:00","usage_id":"usage-1"}]}
```

Messages sort by exchange time then usage ID, user before assistant. Empty assistant messages are omitted. Missing, expired, deleted, disabled-content and other-caller IDs return identical HTTP 404 `{"detail":"找不到對話"}`.

## Delete

`DELETE /api/ai/conversations/chat-1`

HTTP 204, no body, including nonexistent and other-caller IDs. Deletes only caller exchange content. Accounting and feedback remain. Works when storage is disabled.

## Resume

`POST /api/ai/chat` accepts the same conversation_id with client-supplied prior messages. The server does not inject history. Existing limits remain, 20 messages, 4000 characters per user message and 20000 per assistant message. Project requests also supply project_id. Conflicting scope/project reuse within the same caller returns 422. Another caller using the same ID has independent history.

```json
{"model":"gpt","conversation_id":"chat-1","messages":[{"role":"user","content":"這週誰遲到？"},{"role":"assistant","content":"王小明有一次遲到。"},{"role":"user","content":"上週呢？"}]}
```

## Display payload

A `tool` SSE event with `status: "done"` may contain `displays`, an array of display objects. The title is the dataset's human title. Tables use `columns` and `rows`, with an optional `caption` containing the source time. Charts and stats use `points`; a stat has at most one point. Optional `series` on a point groups chart values. `as_of` is a source timestamp or null. `limitations` are source caveats. `truncated` includes source pagination and display caps. Bar and line cap at 24 points, pie at 12, table at 50.

Table example.
```json
{"kind":"table","title":"資產使用","columns":[{"key":"name","label":"名稱"},{"key":"uses","label":"使用次數"}],"rows":[{"name":"車1","uses":4}],"truncated":false}
```
Bar example.
```json
{"kind":"bar","title":"資產使用","result_id":"r123","points":[{"label":"車1","value":4}],"truncated":false,"as_of":null,"limitations":[]}
```
Line example.
```json
{"kind":"line","title":"資產使用","result_id":"r123","points":[{"label":"車1","value":4,"series":"外業"}],"truncated":false,"as_of":null,"limitations":[]}
```
Pie example.
```json
{"kind":"pie","title":"資產使用","result_id":"r123","points":[{"label":"車1","value":4}],"truncated":false,"as_of":null,"limitations":[]}
```
Stat example.
```json
{"kind":"stat","title":"資產使用","result_id":"r123","points":[{"label":"車1","value":4}],"truncated":false,"as_of":null,"limitations":[]}
```

## Completion visibility

The server finishes the ledger write before emitting SSE `done`. With content storage enabled and a successful write, the exchange is committed and queryable when the client receives `done`; clients may refresh history immediately. Disabled storage, retention, deletion, or a database write failure can leave no content. A deletion increments a server-side generation for this caller and conversation. Runs started before that deletion retain usage accounting but cannot restore content, including after cancellation. A newly started run may reuse the ID.
