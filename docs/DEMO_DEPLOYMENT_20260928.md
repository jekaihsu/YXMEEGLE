# 2026-09-28 Demo 新版部署回執

## 最新部署（台灣 23:12）

- Deployment `6aba8387cf055b5b04562ae2` 已查回 RUNNING，UTC 15:12:02 完成。
- 白名單 staging `zeabur-stage-6ab9d63f`，88 檔；前端 `index-BeVrXu_y.js` / `index-bMhteLtr.css`。
- 雲端資產與本地位元組相符，PostgreSQL 健康，UTC 15:14:37 demo 10 項驗收全部通過。
- 本輪包含設計變更三線確認與 PM＋主管共同核准、四類真實 Lark 審批對應、Drive 保存入口及重複送存防護、人員缺帳號在職狀態診斷、Attendance 正式舊工作區判定修正、專用 Input 雙重白名單。
- 環境設定完整合併為 19 個唯一鍵並逐值讀回一致。四張審批定義皆以專用應用真實讀取並驗證 ACTIVE；尚未真實提單、共同核准或驗收送達。
- 部署前六表備份回執 `.runtime/current-cloud-backup-20260928T144917Z-8b70c171/receipt.json`，下載校驗及本機 SQLite 逐列逐檔還原通過；非 PostgreSQL 災難還原。
- 驗收僅涵蓋已列證據；以下原始回執保留為歷史，不代表目前部署 ID。

## 原始部署回執

- 網址：https://yongxiang-projects-20260925.zeabur.app
- Zeabur deployment：`6aba419d30d837437e0b01c9`，查回 `RUNNING`。
- 完成時間：2026-09-28 10:30:40 UTC（台灣 18:30:40）。
- 部署來源：白名單 `.runtime/zeabur-stage-a91b1bef`，86 檔；未上傳私密設定、備份或本機 DB。
- 前端：`index-CJvSUYKp.js`、`index-bMhteLtr.css`，雲端資產已與本地核對。
- 保留既有 demo 環境設定與 Lark 登入入口；沒有藉本次部署宣稱正式串接全數完成。

## 備份與驗收

部署前唯讀備份位於 `.runtime/legacy-cloud-backup-20260928T102842Z-5165b615`，16 工作區、1 回執、1 來源快取、1 附件；SHA256 `a43757645837076dabaf3abd93173aa4c07cb93763771b6bf3e4bfc99cc5b592`。本機 SQLite 還原逐列與附件雜湊相符，未宣稱 PostgreSQL 災難演練完成。

發布重點 76 項測試通過；獨立雲端 10 項檢查通過，詳見 `DEMO_ACCEPTANCE_20260928.md`。健康檢查 PostgreSQL 正常，最新資產可下載，demo 案件與日報／稽核 API 可讀。

舊 `deploy_verify.py after` 使用先前保存的登入 cookie 收到 401，因此不能用該回執宣稱舊登入工作階段持續有效；新的隔離 demo 工作階段驗收已通過。既有資料的完整雲端遷移逐列比對仍未完成。

## 尚待正式驗收

真實動態名冊、四類審批共同核准、Drive 上傳讀回、Attendance 排班、通知送達、第二 Meegle 範本完整映射，以及獨立備份目的地與 PostgreSQL 還原仍須繼續。此版本供 demo，不等同全部公司正式使用條件已滿足。
