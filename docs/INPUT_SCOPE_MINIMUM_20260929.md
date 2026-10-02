# Input 權限最小集合核對

## 已核實 API 層 N 選 1

| API | 可沿用／需新增 |
| --- | --- |
| bitable/v1 list tables、list fields、list records | 已發布 bitable:app:readonly 足夠；不是每個 granular read 都必須加 |
| drive/v1 permission members create | 已發布 drive:drive 或 drive:file 任一已足夠，server 不必另加 docs:permission.member:create |
| bitable/v1 app create | base:app:create 或 bitable:app；readonly 不足 |
| bitable/v1 table create | base:table:create 或 bitable:app |
| bitable/v1 table delete | base:table:delete 或 bitable:app |
| bitable/v1 record create（正式 Input runtime） | base:record:create 或 bitable:app；readonly 不足 |

不建議為省 scope 數量開 bitable:app 全權。資料目的地仍須獨立資源授權，scope 不取代 Base ACL。

原文已保存 `.runtime/input-doc-*.md`，每份明載「開啟其中任意一項」。來源為 [Lark 官方 Base API 索引](https://open.larksuite.com/llms-docs/zh-CN/llms-docs.txt) 指向的各 API .md；permission member 另由本機官方 `schema drive.permission.members.create` 核實 `_meta.scopes`。

## CLI v3 的額外限制（不能用 v1 文件推論）

以專用 app 隔離配置實際唯讀執行，`base +table-list` 回 app_scope_not_applied 缺 `base:table:read`；`base +field-list` 缺 `base:field:read`。證據 `.runtime/input-scope-read-probe.json`。因此這兩個讀 shortcut 不能只假定 bitable:app:readonly 已覆蓋。沒有遠端寫入。

若使用此次 CLI --fields 建立路徑，實際會用 app create、table list/create/delete；沒有 table PATCH。最小 API 操作集合因此需新增：base:app:create、base:table:create、base:table:delete、base:table:read、base:field:read、base:record:create。若另用 +base-get，還需核對 base:app:read；可用既有 v1 metadata 讀回避免擴大。

但官方 [shortcut 定義](https://github.com/larksuite/cli/blob/v1.0.85/shortcuts/base/base_create.go) 的 BotScopes 另含 table:update、docs:permission.member:create。[runner.go](https://github.com/larksuite/cli/blob/v1.0.85/shortcuts/common/runner.go) 的 checkScopePrereqs 在 token 含 scope 資訊時會逐項要求整份宣告，token 無 scope 資訊時才交 server 判定。這是 CLI 預檢與 server N 選 1 的差別。

若要一次發布並確保原版 shortcut 的完整預檢集合，應涵蓋上述六項加 base:table:update 與 docs:permission.member:create（共八项），其中後兩項是此版本 CLI 的相容性成本，不應描述為本次 server API 工作必需。若堅持 API 最小六項，需接受 CLI 前置檢查仍可能阻擋，再核對失敗階段；不可繞過預檢或盲重送建立。

本輪僅查文件、身分與唯讀 metadata；沒有新增 scope、發布版本或建立 Base。

後續執行更新：root 發布上述六項最小新增權限後，原版 +base-create --fields 已真實成功，沒有再要求 table:update 或 docs:permission.member:create。此應用／token 路徑可採六項；不再以八項作為此次必要條件。完整建立回核見 INPUT_BASE_CREATED_20260929.md。
