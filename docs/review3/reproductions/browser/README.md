# 第三輪前端問題重現工具

這組工具匯入 repository 內**真正的 React 元件**，用 `fake fetch` 注入合成資料、延遲回應與錯誤。沒有複製待測元件的實作。`PRIVATE_CASE_A`、`ACTOR_A` 等皆為人工測試字串；即使 fixture 標記 `production`，也只是為了走正式環境的前端條件分支，並未連接正式後端。

這是功能與資料隔離重現，不是視覺驗收。建置刻意忽略 CSS，畫面會是瀏覽器預設樣式。所有 `fetch` 都由 fixture 截住；未知路徑回合成 404。來源連結由後端函式生成，但識別全部是 `synthetic`，測試不會點開來源。

## 已涵蓋的問題

| 腳本 | 元件／流程 | 缺陷存在時的斷言 |
|---|---|---|
| `epoch-proof.js` | 真正 App、延遲 task_start、手動 refresh | B 登入身分下重新顯示 A 案件，仍出現已儲存提示 |
| `draft-proof.js` | 真正 DraftForm，同頁兩筆同標題表單 | A 紀錄恢復並提交 B 的草稿 |
| `audit-proof.js` | 真正 AuditTrail，A→B、B 回 503 | B 頁仍顯示 A 的稽核紀錄 |
| `daily-proof.js` | 真正 DailyRecords、後端投影資料 | approved/returned 都顯示待查證；第3頁換到只有1筆的案，資料空白且翻頁鍵皆停用 |
| `comment-proof.js` | 真正 App 案件討論 | A 留言草稿切案後被提交到 pB；屬既有 #41 追加影響 |

共有 **5 項新缺陷**；日報兩項在同一腳本中驗證。留言是既有 #41 的補充，不是第6個新 issue。日報測試不要求核對舊系統移轉的未配對日報，也不把該歷史資料當作發布門檻。

腳本目前斷言「缺陷可重現」。因此成功回傳 JSON **不是修復驗收通過**；業務程式修正後，這些缺陷斷言應失敗，需另外更新成期望正確行為的回歸測試。

## 建置與啟動

以下命令從 repository 根目錄執行。需 Node.js、已安裝的 `frontend/node_modules`（React、esbuild 等），以及 Python。若尚未安裝前端依賴，先按 repository 的安裝程序處理；本工具不另行修改鎖檔或下載相依套件。

```powershell
node docs/review3/reproductions/browser/build.cjs
python -m http.server 8794 --bind 127.0.0.1 --directory .runtime/review3-public-browser
```

第二行持續執行，請另開終端操作瀏覽器。bundle 與 HTML 僅產生在 `.runtime/review3-public-browser/`；**不要提交產物**。8794 刻意與審查時使用的8793隔離。

合成日報資料已隨工具附上。若要驗證目前後端投影並重新產生 `daily-data.json`，先在具備本專案後端依賴的 Python 環境執行，再重建：

```powershell
python -X utf8 docs/review3/reproductions/browser/daily-contract.py
node docs/review3/reproductions/browser/build.cjs
```

`daily-contract.py` 真正呼叫 `backend.v4_sources.daily_review` 與 `backend.source_projection.daily_index`，只處理三筆合成來源資料，不啟動伺服器、不讀取正式案件、不呼叫 Lark。

## Playwright CLI 執行

先開啟獨立 session，避免污染日常工作的瀏覽器：

```powershell
npx --yes --package @playwright/cli playwright-cli -s=review3public open "http://127.0.0.1:8794/?mode=draft"
npx --yes --package @playwright/cli playwright-cli -s=review3public snapshot
```

首次使用 `npx` 可能需要下載 Playwright CLI 與安裝瀏覽器。若環境已有 CLI，可以直接使用已安裝的 `playwright-cli`。所有頁面測試只指向 localhost。

本 repository 的 Windows 輔助工具 `scripts/browser_step.py` 會讀取 UTF-8 JS 並透過 Node 參數呼叫 Playwright CLI，避免 PowerShell 改寫 JS 引號；它會從 Windows npm cache 尋找 CLI。建立上述 session 後，逐一執行：

```powershell
python scripts/browser_step.py review3public docs/review3/reproductions/browser/draft-proof.js
python scripts/browser_step.py review3public docs/review3/reproductions/browser/audit-proof.js
python scripts/browser_step.py review3public docs/review3/reproductions/browser/daily-proof.js
python scripts/browser_step.py review3public docs/review3/reproductions/browser/comment-proof.js
python scripts/browser_step.py review3public docs/review3/reproductions/browser/epoch-proof.js
```

每個腳本自行導航至所需模式，不依賴上一項測試的頁面。成功結果印在 `### Result` 後；腳本會對預期缺陷作明確斷言，失敗則回報錯誤。若在其他作業系統，可直接將腳本內容交給已安裝 CLI 的 `run-code`，例如 Bash：

```bash
npx --yes --package @playwright/cli playwright-cli -s=review3public run-code "$(cat docs/review3/reproductions/browser/epoch-proof.js)"
```

三個腳本會產生合成截圖：

- `output/playwright/review3-session-race.png`
- `output/playwright/review3-draft-collision.png`
- `output/playwright/review3-audit-stale.png`

它們會覆寫同名檔案；需要保留舊結果時，先另存副本。重現完成後可關閉 session，並在 HTTP server 的終端按 Ctrl+C：

```powershell
npx --yes --package @playwright/cli playwright-cli -s=review3public close
```

## 驗證範圍

涵蓋實際 React state、表單事件、sessionStorage、UI路由與非同步結果接收。HTTP 回應由 fake fetch 控制，因此沒有宣稱已重現正式 OAuth 換人流程、後端越權寫入、真實通知送達或正式 Lark 審批。第三輪主報告、JSON 證據與截圖由上一層文件索引提供。
