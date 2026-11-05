# 今日工作台角色視圖驗證

本次修改僅在目前 worktree。沒有推送，沒有建立 PR，沒有修改後端。


## 第二輪修正與驗證

第二輪以本節為準，後方保留第一輪紀錄。只修改此 worktree，沒有推送或建立 PR。

- `homeWorkSource.ts` 共用 demo fallback 的完整已載入工作清單與 queue。工作卡片只裁切顯示五筆，摘要先對全部已載入項目計數。完整來源顯示 N，partial 或 has_more 顯示 N+，沒有來源才顯示待核對。舊版 full workspace 未設定 scope，只有 shell 視為預覽。
- 工作摘要改成無卡片外框的窄列。四個數字各自連至工作、案件、確認或出勤頁，不再有「查看全部」。整列最多一段來源說明。
- 不可用的個別卡片隱藏副標並縮小留白，只留標題、單一訊息與操作。個人、團隊或公司整個主要來源不可用時，以頂端單一通知取代重複來源卡片。公司已回傳的 totals 仍保留。
- 視圖切換改成標題副標下方的頁籤。1280px 操作群組四個控制項的 y 坐標均為 144px，沒有換列。390px 頁籤文字保持單行，操作群組依空間換列。資料時間為 muted caption，移除橘色。
- 說明同步解釋 N+ 與待核對。修正既有不存在的 `--space-5` 引用，改用已定義的 `--space-6`。

第二輪測試通過。`npx tsc -b` 的同等本地 tsc 執行、`npm run build -- --outDir ../output/home-roles/runtime/dist`、`test:unified-home`、`test:home-executable`、`test:home-review-regressions`、`test:work-assigned-visibility`、`test:pm-glance` 與 `git diff --check`。最後一輪指定五組測試均再次通過。額外重跑 `test-home-panels.mjs` 仍為 FAIL，停在第 48 行 cached ShellDashboard 的 `/已核對案件/` 斷言，與第一輪已證實的 baseline 失敗相同，未修改此測試或相關頁面。

新增 `test-home-counts.mjs` 並接入 `test:unified-home`。Literal expected values 包含個人完整 `2/1/3/2`、預覽 `2+/1+/3+/4+`、沒有來源四個待核對、complete 但 has_more、disabled、demo 七筆且卡片只顯示五筆、shell N+、空 queue 的 0 與未提供 queue 的待核對、團隊完整與預覽，以及公司 totals `8/12/5/待核對`。DOM 回歸另驗證頁籤與操作分開、無來源時只有一個通知且不重複空卡片。

隔離環境依指定 memory 重新啟動。API 18765，Vite localhost:15199，SQLite、uploads、config 與 dist 沿用此目錄 runtime。啟動時舊 cookie 已失效，以隔離 demo session 重新登入。未使用正式資料。T3 preview 的觀測值另存 `runtime/round2-evidence.json`。

- 成員 `u-field`。PASS。本人已載入九筆逾期 legacy 工作，摘要 `9/0/0/0`，卡片顯示前五筆。1280 與 390 無水平溢出，成員沒有視圖切換。證據為 [桌面](member-desktop-1280.png) 與 [手機](member-mobile-390.png)。
- PM `u-pm`。PASS。預設全公司，保留 dashboard totals `0/0/0/待核對`。公司來源僅有一個頂端通知，組別、案件與狀態空卡不重複呈現。1280 與 390 無水平溢出。證據為 [桌面](pm-desktop-1280.png) 與 [手機](pm-mobile-390.png)。
- 經理 `u-manager` 全公司。PASS。預設全公司並提供三個頁籤。證據為 [桌面](manager-desktop-1280.png) 與 [手機](manager-mobile-390.png)。
- 分配工作。PASS，僅指不可用來源的實機 UI。team API 回傳 403，四個摘要均待核對，只有一個權限通知，allocation 與 workload 不重複出現，個人工作維持收合。證據為 [桌面](assign-desktop-1280.png) 與 [手機](assign-mobile-390.png)。真實組員工作量與請假總數仍為 COULD NOT RUN，demo 未連接 Lark；完整與預覽數字由合成 fixture 驗證。
- 自訂與說明。PASS。390px 無水平溢出。實際把我交辦的移至今日請假之後，DOM 順序變為 kpi、leave、delegated、trips、work，並還原。說明 Esc 關閉且焦點回到觸發按鈕。證據為 [自訂桌面](customize-desktop-1280.png)、[自訂手機](customize-mobile-390.png)、[說明桌面](help-desktop-1280.png) 與 [說明手機](help-mobile-390.png)。

上述十二張 PNG 均重新擷取並覆寫，PNG 與 runtime 不納入 git。第一輪額外的 dark 截圖未重新擷取。

套用 Model the Domain，把計數來源的 items 與 complete 放在同一個資料形狀。套用 Prove It Works，以 literal DOM assertions、隔離 API、實際頁面操作與 PNG 驗證。此為使用者指定的 implementation sub-agent 工作，探索、實作與驗證均在本執行緒完成，未再委派。

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
