# 發布封裝檢查與回執界線（2026-09-29）

本次確認並重現的缺陷是部署白名單漏掉執行期資料：`backend/sop_contracts.py` 會直接讀取同目錄的 `sop_source_contracts.json`，但先前打包只自動納入 Python 檔案。來源工作區測試通過及 `/api/health` 正常，都不能證明封裝後的 SOP／展示工作區能正常讀取。

根代理已在 `scripts/deploy_prepare.py` 加入該 JSON 的明確白名單；本次封裝審查沒有修改該腳本、雲端設定或正式資料庫。

## 已驗證證據

| 檢查對象 | 結果 |
| --- | --- |
| 舊 stage `1ab2ebb6` | 有 `sop_contracts.py`、缺 JSON；隔離檢查以 exit 1、`missing_sop_source_contracts` 失敗 |
| 修正版 stage `540a8906` | catalog、policy template、health、demo session、workspace、projects、daily-reports、sources、僅 staged imports 共 9 項通過 |
| `backend/test_stage_package.py` | 2 passed；正向測試使用真正 staging 白名單，負向測試在 checkout 仍有 JSON 時確認缺檔不能偷偷回退讀取 |

本機安全回執為 `.runtime/stage-smoke-1ab2ebb6.json` 與 `.runtime/stage-smoke-540a8906.json`。這些是指定 staging 目錄的封裝驗證，不是本審查代理對雲端 deployment 的獨立確認，也不代表 PostgreSQL、worker、正式 OAuth 或外部整合驗收。

## 每次發布前

1. 完成相關單元測試與前端 build；來源測試不取代以下封裝檢查。
2. 執行 `python -B scripts/deploy_prepare.py staging`。現在此命令會自動執行下述隔離 smoke，失敗即以非零碼停止；成功才輸出 runtime_smoke_passed=true。同時保存以 stage 名稱命名的獨立 manifest／smoke 回執，避免通用 manifest 被後續 staging 覆蓋。
3. 對**將實際上傳的那個目錄**執行以下命令。任何非零 exit code 都停止上傳；修正後建立新的 stage，不在已驗證 stage 裡臨時修改檔案。

```powershell
python -B scripts/verify_stage_package.py .runtime/zeabur-stage-<id> --receipt .runtime/stage-smoke-<id>.json
```

4. 將相同 stage 上傳。保留 deployment ID、stage、manifest、smoke receipt 的對應；不得以另一個 staging 的成功結果代替。
5. 部署 RUNNING 後，另外核對 runtime 檔案 hash、frontend asset bytes、健康狀態及新匿名 demo session／workspace。`scripts/verify_release_runtime.py` 目前只核對 manifest 已列出的檔案，不能單獨發現白名單漏檔。

新增 JSON、schema、SQL、模板或其他 runtime 資料檔時，需同步修改打包白名單並讓隔離 smoke 實際走到讀取它的程式路徑。Docker `COPY backend/` 只能複製 stage 已有的內容。

## 隔離 smoke 的行為

`scripts/verify_stage_package.py` 用 `python -I -B` 啟動獨立程序，cwd 在臨時目錄；應用只由指定 stage 載入，並核對所有已載入 backend 模組的實際路徑。依賴套件仍使用本機 Python 安裝，因此不等同 Docker image 的依賴／作業系統驗收。Windows 使用者 site-packages 以明確路徑加入，不執行該目錄的 `.pth`。

子程序不繼承 Lark、資料庫或雲端憑證，只建立臨時 SQLite 與 uploads；在載入應用前封鎖網路連線，使用 ASGI 直接呼叫六個 GET endpoint。Windows event loop 初始化所需的本機 socket pair 在封鎖前建立。完成後關閉引擎並移除臨時資料。stage 不會新增 DB、uploads 或 bytecode。回執只含檢查結果、版本與 stage 路徑。

## 舊文件與舊回執的解讀

- `DEPLOYMENT_RECEIPT.md` 是 2026-09-25 歷史回執；其「最新部署」、19 檔白名單、當時 asset hash 不代表 2026-09-29 最新部署。勿刪除歷史數據或將其改成尚未驗證的新結果。
- `CLOUD_DEMO_ACCEPTANCE_20260929.md` 綁定 deployment `6abb58fbb57ea4921d62bd90`、stage `1520832c`；其中 12 項通過不能沿用成後續 `540a8906` 的雲端驗收。
- `RELEASE_OBSERVATION_PLAN_20260929.md` 的 `ieKSvLZ6` 是當時 frozen dist 的預期值；新發布需重新凍結並綁定該發布資產，不將舊 hash 當永久標準。該文件明確說尚未建立 24h scheduler／證據，本次封裝檢查沒有改變此狀態。
- `DEPLOYMENT_READINESS_20260928.md` 的「本次 18 passed」是當時備份／runtime 專項結果；它已記錄另一宗 `backup_live_legacy.py` 漏打包事故，但不能覆蓋本次 SOP JSON 漏檔。套件 manifest hash 相符只代表已列檔案相符。
- `scripts/deploy_verify.py before` 會在 demo 新增留言與附件；需要純 GET 觀測時不要拿它代替唯讀驗收。所有 `.runtime` 檔案均先按檔名／必要欄位最小化读取，不直接輸出環境或憑證快照。
