# 專用 Input Base 建立前準備

本次只讀 CLI help、身分狀態及本地程式。沒有建立 Base、沒有擴權、沒有改 global config，也沒有存取或改動 V4／報價／薪資 Base。

## 核實結果

- 目前 `lark-cli config show` 的 app ID：`cli_a97716d3a15ede15`，**不是**工作台專用 `cli_aa3cab98b2789e17`。
- `auth status --json`：identity=none、user.status=missing、bot.status=not_configured。沒有輸出密鑰或 token。沒有可直接沿用的 user CLI 登入。
- `base +base-create --help` 支援 name、table-name、fields JSON array、time-zone、as、dry-run；可在同次建立 Base 時指定唯一初始表的九欄 schema。
- lark-base field JSON 規格：每欄 `{name,type:"text"}`；不能將 OpenAPI 的 field_name/type=1 混入 CLI 建欄輸入。

## 待 root 接手

1. 先以已核實的專用 app 隔離設定及憑證執行，不能覆蓋目前 global CLI config；若 CLI 隔離配置機制未核實，先由正常後台／專用憑證流程處理，不冒用其他 app。
2. 先查有無同名專用 Base，以及既有建立回執。查得多個不能隨意選；先核對 owner/schema。沒有既有資源才建立一次。
3. 使用 `INPUT_BASE_CREATE_COMMAND_20260929.json` 的 schema：Base「詠翔專案工作台作業資料登錄」，表「作業資料登錄」，九個 text 欄。argv_template 是參數陣列；`JSON_SERIALIZE(fields)` 需序列化替換，不能原樣執行。先保留 `--dry-run` 核對請求；移除它才會遠端建立。沒有指向任一來源 Base。
4. 真正建立後保存完整回執於私密 `.runtime`；取得真實 base_token、table_id，**記錄 permission_grant**。Bot 建立成功不表示使用者已能開啟；依 permission_grant 報告可見性，失敗需另外授予使用者此專用 Base 的權限。
5. 用專用 app 讀回 `base +base-get`、`base +table-list`、`base +field-list`。逐欄核對唯一名稱、真實 field_id 及 OpenAPI text type=1。新目的地 token 不得等於 V4／報價／薪資 token。
6. 將九個內部 key 映射真實 `{field_id,field_name}`，設定 `LARK_INPUT_REGISTRATION_FIELDS_JSON`；使用正常工作台管理設定寫 input_base/input_table。不要用欄名假作 field_id，也不要只配置 schema 就宣称連線已成功。
7. 確認沒有舊 blocked/unknown jobs 被自動重送。透過隔離測試案件的正常 Input 路由排入一次，再由專用 app 查回九欄完全相符與雜湊，才可認定實際登錄成功。未知結果只讀查回。

## 可替代的使用者建立路徑

使用者本人有有效 user CLI 授權時，可將建立命令 `--as user`，由使用者持有新 Base；但**目前沒有這個登入條件**。新 Base 建立後，仍須在此專用 Base 的協作／應用權限授予工作台專用 app 可讀欄位、讀紀錄與建立紀錄，不得把另一 CLI app 當成工作台 app。授權之後要用工作台專用身分讀回 schema，不能以建立者讀得見代替 app 可存取證明。

permission_grant 是 bot 建立對使用者可見性的回執，不是「另一個 app 已獲授權」的保證；user 路徑缺少該欄也不能推論專用 app 已可寫。

## 九欄後端映射 key

registration_key→登錄識別；workspace_id→工作區識別；project_id→案件識別；node_id→節點識別；revision_id→修訂識別；actor_id→提交人識別；submitted_at→提交時間；content_json→登錄內容；content_hash→內容雜湊。

依據：lark-base/SKILL.md、lark-shared/SKILL.md、lark-base/references/lark-base-field-json.md 與本機 CLI help。此檔是待執行準備，不是真實目的地建立收據。

## 隔離方式已核實並完成 dry-run

本機 CLI 為 1.0.85。官方同版本 [workspace.go](https://github.com/larksuite/cli/blob/v1.0.85/internal/core/workspace.go) 明確支援 `LARKSUITE_CLI_CONFIG_DIR`；[config.go](https://github.com/larksuite/cli/blob/v1.0.85/internal/core/config.go) 定義 apps/currentApp、`--profile` 選擇及配置讀取方式。

`python scripts/lark_input_isolated_dryrun.py` 已成功執行。僅子程序 env 指向 `.runtime/lark-input-cli`，載入既有私密憑證至該 gitignored 專用 config，使用 profile `workbench-input`。不修改 HOME、全域設定或預設 profile；密鑰不放命令列、不列印。wrapper 只提供 whoami 與 `--dry-run`，沒有真建立模式。

驗證：有效 app ID 為 cli_aa3cab98b2789e17，dry_run=true、identity=bot，九欄名稱正確。結果 `.runtime/lark-input-cli/base-create-dryrun.json`；另查未加隔離的 config，仍為 cli_a97716d3a15ede15。這只證明隔離与請求構造，不證明 scope 已發布或可真寫。

### 實際建表流程與 scope

官方 [base_create.go](https://github.com/larksuite/cli/blob/v1.0.85/shortcuts/base/base_create.go) 宣告 bot 所需 scopes：`base:app:create`、`base:table:read`、`base:table:create`、`base:table:update`、`base:table:delete`、`docs:permission.member:create`。這是此 CLI shortcut 宣告的最小集合，不是要申請整個 all domain；本輪未授權任何新增 scope。

實測 dry-run 不是單一原子 API：POST `/open-apis/base/v3/bases` → 若未回預設表 ID 則 GET tables → POST 新九欄表 → 等待後 DELETE **這次新 Base 的預設表**。建立部分失敗後必須先查回並使用原 created_base_token，不可以盲目重跑造成第二個 Base。它不應刪改任何既有來源 Base 表。

另外，後续 CLI schema 讀回需 `base:app:read`、`base:field:read`；工作台 runtime 使用原有 bitable/v1 欄位／紀錄 API，需再核實其讀欄、讀紀錄與建立紀錄 scope，以及新 Base 的應用資源權限。create dry-run 沒有驗證這些權限。

沒有 CLI user 身分，因此 bot 建立後的自動 permission_grant 可能 skipped；root 應查看實際回執，透過新 Base 的正常協作授權確保公司管理員能開啟。不得據此擴大三個來源 Base 權限。
