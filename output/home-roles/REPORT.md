# 今日工作台角色視圖驗證

本次修改僅在目前 worktree。沒有推送，沒有建立 PR，沒有修改後端。

## 行為與資料

- `role` 為 `pm` 或 `manager`，或部門符合 `專案|PM|業務|管理`，預設「全公司」，可切換「分配工作」與「我的工作」。
- 其他使用者在 `manager_view_available === true` 時預設「分配工作」，可切換「我的工作」。
- 其餘使用者僅顯示「我的工作」，不顯示視圖切換器。
- 初次個人 panel 尚在讀取時先顯示「我的工作」。已儲存的有效選擇優先，不因背景讀取而改動。
- 細節調整。PM 與管理部門在首次 panel 請求結束後，即使來源因未連線而持續回傳 null，仍依已知 session 角色開啟公司視圖。原因是這些使用者的公司 persona 不依賴 Lark 主管名冊；若永遠等待 null 變成布林值，demo PM 將永遠停在個人視圖。一般成員的主管預設仍必須由 true 證實。
- 設定使用 `yx.home.v2` 身分 key。選擇的視圖與三份配置分別保存。v1 安全忽略，不刪除原資料。還原只影響目前視圖，所有卡片包含工作摘要都可排序或隱藏。
- 個人工作與待確認資料各讀一次並共用。公司 hook 僅在公司視圖掛載；team scope 僅在分配視圖掛載。預覽最多五筆，來源有更多項目或未完整時不把預覽數當作完整總數。
- 說明按鈕有展開狀態、依視圖切換的內容、Esc 關閉與焦點返回。亮色與深色使用既有 token。

## 來源限制與未完成的來源能力

- `backend/home_panels.py` 的 selector 只讓有 assignees 的管理項目進入一般 team assigned 清單。一般未指派節點不可由此查詢取得，因此「待分配」顯示待核對，並說明資料尚未完整。
- Session 與出勤來源沒有權威管理組員名冊，不能把全公司請假總數當成「今日請假組員」。此 KPI 顯示待核對，今日請假與出差名單仍可查看。
- CompanyDashboard 沒有本週到期 aggregate，也沒有所有任務期限，故本週到期顯示待核對。
- 公司總數與圖表只使用 dashboard 回傳值。`complete !== true` 明確標示「資料尚未完整」。本週期限以臺北週一至週日計算，七日分布另從今天起算。

## 修改檔案

- `frontend/src/homeLayout.ts` 定義視圖、卡片 registry、預設配置、persona 與 v2 解析。
- `frontend/src/UnifiedHome.tsx` 組合視圖、共用資料、切換與自訂。維持 83 行。
- `frontend/src/homeCards.tsx` 保留既有工作列、期限、出勤與 demo fallback。
- `frontend/src/homeCharts.tsx` 提供無套件圖表與可讀的文字數值、ARIA 標籤。
- `frontend/src/homeHelp.tsx` 提供說明與焦點操作。
- `frontend/src/homeViews/MineCards.tsx`、`AssignCards.tsx`、`CompanyCards.tsx`、`shared.tsx` 提供各視圖卡片與資料提示。
- `frontend/src/useHomeCompany.ts` 共用一次公司請求。
- `frontend/src/useHomePanels.ts` 區分 403 權限不足與一般讀取錯誤。
- `frontend/src/UnifiedHome.css` 處理圖表、標頭、說明、自訂與手機版。
- `frontend/test-home-layout.mjs` 新增 literal expected values 的 persona、視圖權限、v2 解析與預設配置測試。
- `frontend/test-unified-home.mjs` 更新合法設計差異並增加互動驗證。
- `frontend/package.json` 將新資料模型測試接到 `test:unified-home`。

## 測試

通過。

- `cd frontend && npx tsc -b`。
- `npm run build -- --outDir ../output/home-roles/runtime/dist`。沒有寫入 frontend/dist。
- `npm run test:unified-home`，包含新 persona 與 v2 literal 測試。
- `npm run test:home-executable`。
- `npm run test:home-review-regressions`。
- `npm run test:work-assigned-visibility`。
- `npm run test:pm-glance`。
- `git diff --check`。

額外檢查失敗，已證實為既有問題。

- `node test-home-panels.mjs` 在第 48 行的 cached ShellDashboard 內容斷言失敗。
- 將修改前 `c8cd932` 的 frontend 用 git archive 匯出至 `runtime/baseline`，連接同一套 node_modules 後重跑，同一行同樣失敗。該測試沒有修改。

既有測試只調整 `test-unified-home.mjs`。移除舊 v1 與角色平面配置斷言，改由新資料模型測試涵蓋；成員不再要求案件卡片；摘要卡片可以排序；檢查 v2 per-view hidden；期限文字維持既有相對日期格式。保留重新讀取、出勤、精確工作連結、demo fallback、全隱藏還原與儲存失敗測試。另增加逐視圖還原隔離、選擇保存、team 查詢延遲載入、team 403、公司 403、組員圖表文字、團隊 ctx 連結、出勤卡片排序、初始 pending 不切換以及說明面板焦點測試。其餘四份指定測試未修改。

## 實際畫面

使用指定隔離流程。API 為 18765，Vite 為 localhost:15199，SQLite、uploads、Vite config 與 dist 均在本目錄 runtime。設定 `PUBLIC_ORIGIN=http://localhost:15199`，以允許代理下的 demo 角色切換。透過 T3 preview 操作，沒有使用正式資料。

- 成員 `u-field`。通過。預設 mine，沒有切換器；看得到本人 demo 工作、期限與精確連結。桌面與手機沒有水平溢出。
- PM `u-pm`。通過。預設 company，可切換三視圖；公司來源與出勤不可用狀態明確。桌面與手機沒有水平溢出。
- 經理 `u-manager`。通過。預設 company，可切換 assign 與 mine。assign 的個人工作預設收合。
- 已核實外業主管、真實組員工作量、真實請假組員。無法執行。demo Lark 未連線，`GET /api/home-panels?panel=assigned&scope=team&limit=100` 實際回傳 403，內容為「無法核實同組工作權限」。實機只驗證到權限不足 UI；有資料的主管預設、圖表與 team 查詢由合成 fixture 的 DOM 測試驗證。
- 實際點擊自訂排序後，讀取 DOM 順序與 localStorage，確認工作移至待確認之後，再還原配置。
- 說明面板在手機檢查，修正不存在的間距 token 與透明背景後重新截圖。桌面按鈕拉高問題已修正，量測操作按鈕均為 44px。

截圖均保存在本目錄，PNG 與 runtime 不納入 git。

- `member-desktop-1280.png`。
- `member-mobile-390.png`。
- `pm-desktop-1280.png`。
- `pm-mobile-390.png`。
- `manager-desktop-1280.png`。
- `manager-mobile-390.png`。
- `assign-desktop-1280.png`。
- `assign-mobile-390.png`。
- `customize-desktop-1280.png`。
- `customize-mobile-390.png`。
- `help-mobile-390.png`。
- `manager-dark-desktop-1280.png`。

## 套用的原則

Model the Domain 讓視圖、卡片與配置集中為資料 registry。Type System Discipline 使用既有 HomeItem 與 CompanyDashboard 型別，讓卡片與視圖 ID 由 registry 推導。Prove It Works 讓驗證包含實際 demo API、DOM、鍵盤操作與儲存值，而非只檢查編譯。
