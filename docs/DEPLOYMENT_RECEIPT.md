# Zeabur 部署與驗證回執

日期：2026-09-25。本回執記錄實際部署與測試結果；最後部署及真實來源同步由主協調代理執行，唯讀瀏覽器效能驗證由前端代理執行。日報已有 1 筆透過暫填工編精確配對，仍有 534 筆待核對，不代表整體日報關聯已完成。

## 部署位置

- HTTPS：https://yongxiang-projects-20260925.zeabur.app
- Zeabur 專案：`6ab61680a4c05a5bcb57ace9`
- 環境：`6ab6168036d2a6cac409f0c6`
- 應用服務：`6ab61834a4c05a5bcb57ad69`
- PostgreSQL 服務：`6ab6182fa4c05a5bcb57ad63`
- 最新部署：`6ab6282110778e353136aa2b`，狀態 `RUNNING`
- 上傳目錄：`.runtime/zeabur-stage-833e2114`；19 個白名單來源檔，共 276,606 bytes。

## 非秘密設定

應用使用 `APP_ENV=production`、`DEMO_MODE=true`、`ALLOW_CLOUD_DEMO=true`，明確開放隔離的 preview。真實來源仍須租戶限定的 Lark OAuth，demo 身分不能讀取真實來源或送出正式審批。PostgreSQL 17 Alpine 的資料目錄掛載 `/var/lib/postgresql/data`，應用附件 volume 掛載 `/data/uploads`。

資料庫 private DNS 為 `yx-workspace-postgres.zeabur.internal`；TCP port forwarding 已設為 `DISABLED`。密碼、session 密鑰與 OAuth secret 均不列入本回執或上傳白名單。

專用 Lark App 為 `cli_aa3cab98b2789e17`，callback 為 `https://yongxiang-projects-20260925.zeabur.app/api/auth/lark/callback`，明確 scopes 為 `bitable:app:readonly approval:approval:readonly`。使用者 jekai 已以真實公司帳號成功登入，並依新 App 的明確身分映射為 manager；其他未配置身分預設 member。

`LARK_SOURCE_TABLES_JSON` 維持 8 表，內業來源新增欄位「可能的確認單工編(若暫無確認單才需填寫)」。僅在案號精確且唯一時使用暫填值配對，介面保留其暫填來源與待核對提示，未回寫 Lark。

## 驗證結果

| 項目 | 實測結果 |
| --- | --- |
| 後端測試 | 最新版本 25 項測試通過 |
| 上傳範圍 | 19 個白名單來源檔；未包含 .runtime、憑證、資料庫、附件、node_modules 或整個工作區 |
| HTTPS 與服務 | 最新部署 RUNNING，公開 HTTPS 可用，應用使用 PostgreSQL |
| 最新前端 | `index-C7V2E52H.js`、`index-Mf7O0Dmo.css`；包含暫填工編待核對標示及來源載入狀態 |
| 真實 OAuth | 主協調代理瀏覽器確認 `/api/session` 為 `mode=lark`，使用者 jekai，角色 manager |
| 真實來源同步 | 主協調代理以 manager 執行一次同步成功，耗時 33.869 秒；8 表、2,446 筆紀錄、280 個案件、280 個來源任務 |
| 日報配對 | 共 535 筆日報；暫填工編精確唯一匹配 1 筆，剩餘 534 筆未配對 |
| Workspace 壓縮 | HTTP 200、`Content-Encoding: gzip`，1.151 秒；傳輸 118,723 bytes，解壓 3,541,180 bytes |
| Sources 壓縮 | HTTP 200、`Content-Encoding: gzip`，1.145 秒；傳輸 94,413 bytes，解壓 1,663,984 bytes |
| demo 隔離 | 先前實測 demo 讀取 sources 為 requires_login，來源同步回傳 403 |
| 資料與附件持久化 | 先前實測寫入隔離 demo 留言與附件，容器重啟及重新部署後仍可讀取，附件 SHA-256 一致 |

上述 gzip 數值為前端代理在最新部署後、再次來源同步前，使用既有登入瀏覽器唯讀 GET 的單次實測，不作為效能保證。同步後數量由主協調代理回報。

## 尚未完成與驗證界線

剩餘 534 筆日報未能配對案件，應顯示來源待確認，不能據此判斷沒有作業。已匹配的暫填工編也保留待核對標示。日報證據只能支援案號、工作日期與控制組的活動確認，不能自動視為 SOP 或特定工作批次完成。

正式審批送出與事件回寫仍依整合計畫試辦，不能以 demo 模擬結果替代正式審批。先前持久化驗證涵蓋應用資料列與附件在容器重啟、重新部署後的保留；尚未實測整個雲端資料庫與附件的異地備份還原。

非秘密機器可讀回執存於 `.runtime/zeabur-deployment-receipt.json`。先前隔離驗證摘要為 `.runtime/zeabur-verification-before.json`、`zeabur-verification-after.json`、`zeabur-verification-config.json`；上傳清單與雜湊為 `zeabur-stage-manifest.json`。其他 `.runtime` 檔案可能含有憑證，不得直接提交或分享。操作方法見 [DEPLOYMENT.md](DEPLOYMENT.md)。
