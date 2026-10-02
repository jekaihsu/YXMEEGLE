# 正式 Input 登錄 Base 建立及 schema 核實

已於 2026-09-29 以專用 app cli_aa3cab98b2789e17、隔離 `.runtime/lark-input-cli` 配置，執行原版 CLI 一次建立「詠翔專案工作台作業資料登錄」。沒有修改全域 CLI 設定；沒有改動 V4、報價或薪資 Base。

- 正常回應 rc=0、created=true。
- 新 Base 的平台預設表被此 shortcut 替換為指定九欄表；只刪了這次新建 Base 的空白預設表。
- 兩次唯讀回核：唯一資料表「作業資料登錄」，九個唯一且名稱相符的 text 欄，真實欄位 ID 完整；資料筆數 0。
- 原版 shortcut 在此次六項新增權限配置下成功，未要求另開 table:update 或 permission.member:create。
- `permission_grant` 明確 skipped：專用 CLI 沒有 current user open_id，沒有替公司同事自動授予 full_access。**不能宣稱同事已可直接打開此 Base。** root 需依正常協作權限將此新 Base 授予適當管理員；尚未代做授權。

## 私密回執及交付設定

- `.runtime/lark-input-cli/formal-create-checkpoint.json`：schema_readback_verified；建立器遇到既有 checkpoint 即停止，不盲重送。
- `formal-create-receipt.json`：原版 CLI 完整建立回應。
- `formal-tables-readback.json`、`formal-fields-readback.json`：真實唯讀結果。
- `formal-input-config.json`：環境變數 LARK_INPUT_BASE_TOKEN、LARK_INPUT_TABLE_ID、LARK_INPUT_REGISTRATION_FIELDS_JSON，以及 workspace input_base/input_table。均使用讀回的真實 ID。

程式：`scripts/create_input_base_once.py`、`scripts/readback_input_base.py`。敏感配置只存 gitignored .runtime；沒有將密鑰放進命令列或輸出。

尚未部署環境設定、尚未修改正常工作台設定、尚未透過工作台送出任何真實 Input、尚未建立測試用 Base。因此這是正式目的地與 schema 已核實，不是 Input 端到端登錄已通過。
