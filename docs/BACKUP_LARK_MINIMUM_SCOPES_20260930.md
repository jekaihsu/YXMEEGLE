# 獨立備份應用最小權限核查

對象：`cli_aa361fea3678de13`。本文件審查工作僅讀取證據；主線另已在實際 Lark UI 開通 `drive:file:upload` 和 `drive:drive:readonly`，尚未發布、尚未通過真實 API 驗收。UI 證據：`.runtime/workbench-lark-inspect.txt`。

## 實際 UI 的較細權限

實際應用身分權限 UI 已顯示 `drive:file:upload`（上傳文件，含 upload_all 與分片）及 `drive:file:download`（下載雲空間下的文件）。因此本次採用更小組合 **`drive:file:upload` + `drive:drive:readonly`**；後者依官方文件已涵蓋 list 與 download。以下官方 markdown 的 upload 權限列表未同步呈現這個細分 scope，不能以舊文件斷言細分 scope 不存在。最終有效性仍需以發布後真正 upload/list/download 成功驗收。

## 現行程式所需

| 呼叫 | 官方接受的最小 scope | 本次用途 |
|---|---|---|
| POST `/drive/v1/files/upload_all` | `drive:file` | 上傳加密備份分片 |
| GET `/drive/v1/files` | `drive:drive:readonly` | 列出備份資料夾，核對同名、原 token、未知上傳結果 |
| GET `/drive/v1/files/:file_token/download` | `drive:file:readonly`，也接受 `drive:file` 或 `drive:drive:readonly` | 下載密文重新核對 SHA-256 |
| POST `/drive/v1/metas/batch_query` | `drive:drive.metadata:readonly` | 目前備份程式未呼叫，不需額外開啟 |

僅依上述 markdown 可推得的聯集為 `drive:file` + `drive:drive:readonly`；但實際 UI 已提供更細上傳權限，實際配置採上一節組合。`drive:drive.metadata:readonly` 不能替代 list 所需的 `drive:drive:readonly`。

目前程式使用預先配置的備份資料夾，不自行 create_folder；資源層需授予該資料夾上傳及讀回所需權限，API scope 不會自動授予任意公司檔案存取權。

## 刪除與不可變性限制

官方 DELETE `/drive/v1/files/:file_token` 只列 `drive:drive` 為必要 API scope。另有資源條件：應用為檔案所有者且具父資料夾編輯權，或非所有者但擁有父資料夾所有權／full access。兩層条件不能混為一談：檔案所有者身分不等於文件已證明能繞過缺少 API scope。

此部署應保持 `drive:drive` 未授予，遠端 retention 刪除保持停用。這縮減現有應用憑證的 API 刪除能力，但不是物件鎖定／WORM：公司管理員、資料夾所有者或後續取得較大權限的應用仍可能刪除。未做真實拒絕刪除驗收前，只能記錄「依官方 API scope 限制」，不能宣稱已實測不可刪除，也不能宣稱備份抗所有管理權限或勒索攻擊。若要平台強制保留，需另用有不可變保留能力的儲存與分離管理權限。

## 官方來源

- [上傳文件](https://open.larksuite.com/document/server-docs/docs/drive-v1/upload/upload_all.md)
- [取得資料夾清單](https://open.larksuite.com/document/server-docs/docs/drive-v1/folder/list.md)
- [下載文件](https://open.larksuite.com/document/server-docs/docs/drive-v1/download/download.md)
- [取得文件 metadata](https://open.larksuite.com/document/server-docs/docs/drive-v1/file/batch_query.md)
- [刪除文件／資料夾](https://open.larksuite.com/document/server-docs/docs/drive-v1/file/delete.md)

本次官方文件副本：`.runtime/backup-scope-docs/`。程式依據：`scripts/backup_offsite.py` 的 listing／replicate，以及 `backend/lark_adapter.py` 的 upload／verify_file。
