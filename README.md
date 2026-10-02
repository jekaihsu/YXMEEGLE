# 詠翔專案管理 prototype

最新範圍裁示：[暫停訓練／能力／考評及薪水 Base 回寫](docs/LEARNING_DISABLED_DECISION_20260927.md)。班表、報價認定與人員名冊唯讀同步保留；舊文中的完整學習流程暫不啟用。

2026-09-27 接續入口：[核定決策與交接](docs/HANDOFF_20260927.md)、[來源真實驗收](docs/LARK_SOURCE_ACCEPTANCE_20260927.md)、[備份與遷移](docs/CLOUD_BACKUP_EVIDENCE_20260927.md)。目前九張來源表已可讀，重複同步不增案測試通過，日報仍有待配對資料。使用者已要求[首頁與案件頁明顯視覺改版](docs/VISUAL_REDESIGN_DECISION_20260927.md)，正在本機實作；舊雲端部署回執不代表本輪已上線。

獨立 Web 工作台，採 React／TypeScript＋FastAPI，提供九大節點、SOP 子任務、排程、組日、日報證據、文件、留言，以及展延和設計變更示範流程。UI 參考 Meego，資料目標前接報價、後接 V4 日報。

本地示範使用 SQLite；Zeabur 容器使用 PostgreSQL 與附件持久化 volume。示範案件按瀏覽器隔離，真實 Lark 登入者使用所屬公司的工作區。示範角色不能讀取或同步真實來源。

此文件是啟動與交付說明，不代表雲端部署、真實 OAuth 或原生審批已驗收。實際測試結果請另看交付時的驗收紀錄。

已部署的隔離 preview：https://yongxiang-projects-20260925.zeabur.app 。部署與重啟持久性實測結果見 [部署回執](docs/DEPLOYMENT_RECEIPT.md)；真實登入、來源讀取及審批能力分別驗收。

## 快速啟動：Windows PowerShell

在 `meegle` 目錄執行，需要 Python 3.12 相容環境與 Node.js 22。若使用虛擬環境，先建立並啟用，再安裝套件。

```powershell
python -m pip install -r backend/requirements.txt
Set-Location frontend
npm.cmd ci
npm.cmd run build
Set-Location ..
.\scripts\start_local.ps1 -Port 8000
```

開啟 `http://127.0.0.1:8000`。啟動腳本以前端已完成 build 為前提，使用同網域提供前後端，預設資料庫為 `data/prototype.db`，附件為 `data/uploads`。腳本會設定 development 與 demo 模式，適合本機展示；不能用它啟動正式環境。

腳本未預先指定 SESSION_SECRET 時會產生暫時密鑰；重啟後原 Cookie 會失效，新的示範瀏覽器工作區看起來會重新建立。要持續使用同一 session，啟動前自行設定固定且保密的 SESSION_SECRET；既有資料庫不會因 Cookie 失效被刪除。

`.env.example` 僅是設定範本，程式與啟動腳本不會自動讀取 `.env`。請使用 PowerShell `$env:名稱`、容器環境參數或 Zeabur 變數設定。

## 測試與文件

```powershell
python -m pytest backend/test_backend.py -q
```

前端型別及正式建置檢查使用 `frontend` 內的 `npm.cmd run build`。Word PRD 可執行 `python scripts/generate_prd.py` 重建，另需 `python-docx`。

- [PRD v0.4](docs/PRD_v0.4.md)：需求與驗收規格。
- [Word PRD](output/doc/詠翔專案管理系統_PRD_v0.4.docx)：可分享文件，原 v0.3 保留。
- [技術實作計畫](docs/IMPLEMENTATION_PLAN.md)：狀態、資料及驗收設計。
- [來源對應](docs/SOURCE_MAPPING.md)：報價、V4、V3 角色與證據日期。
- [部署及備份](docs/DEPLOYMENT.md)：Zeabur、Lark 環境變數與恢復程序。
- [API 契約](API_CONTRACT.md)及[後端整合說明](backend/INTEGRATION.md)：接口與實作限制。
- [Word 文件檢查紀錄](output/doc/文件檢查紀錄.md)：結構驗證與視覺審核限制。

## Lark 與示範界線

真實登入需設定公司 OAuth 應用、回呼網址、tenant 白名單及角色對應，來源查詢使用登入者的 user access token，不能直接沿用本機 CLI 登入。來源設定範例見 `deployment/source-tables.json`；目前列報價與 V4 表，V3 用於既有填報參考，不納入新工作區的正式匯入清單。

來源同步唯讀 Lark，可在隔離的公司工作區帶入案件及工項，不改正式 Base。日報只提供案號與日期的作業證據，不直接完成 SOP。正式審批送出目前未接實際提交 adapter 時會阻擋；讀取既有 Lark 審批的外部狀態，不等於已驗證案件和影響範圍，也不自動授權執行。

本機及明確啟用的雲端 preview 可使用示範核准。正式工作區不能手動假造 Lark 核准，也不會由示範角色取得來源權限。

## 雲端部署摘要

根目錄 `Dockerfile` 以 Node 22 編譯前端，使用 Python 3.12 執行 FastAPI；預設監聽 `PORT=8080`，健康檢查 `/api/health`。Zeabur 建立應用容器及 PostgreSQL，將附件持久 volume 掛在 `/data/uploads`，並配置資料庫持久化與備份。

正式服務設定 `APP_ENV=production`、`DEMO_MODE=false`、PostgreSQL `DATABASE_URL`、至少 32 字元 `SESSION_SECRET` 及 HTTPS `PUBLIC_ORIGIN`。需公開雲端示範時，明確設定 `DEMO_MODE=true` 且 `ALLOW_CLOUD_DEMO=true`；仍使用 PostgreSQL，示範身分無法存取真實來源。建議 preview 與正式服務分開資料庫、volume 及密鑰。

未設定 OAuth 時，正式服務不會自動切回示範角色。其他環境部署取得網域後，依 [部署文件](docs/DEPLOYMENT.md)完成各自回呼設定及驗收；不能直接沿用此 preview 的回呼設定。
