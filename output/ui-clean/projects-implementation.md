# 案件頁面精簡實作

Branch: `t3/ui-projects`

## 案件總覽

- 保留頁首單一搜尋，移除重複搜尋與說明段落。
- 所有零筆群組隱藏；整體零筆結果仍保留單一空狀態與清除篩選。
- 指標僅顯示已知統計，未知 SOP／進行中／已完成不冒充零。
- 頁尾合併成一行，使用清單的資料日期與符合條件筆數。
- 保留釘選、群組展開、篩選、排序、清單／卡片切換、九階段步驟列。

## 案件詳情總覽

- 待辦直接接在九階段步驟列下方。
- 指標僅保留真實回報日期、外業關聯工項、已指派待辦及可核實的待核對事項；缺值合併成一行。
- 保留任務／工項深連結、權限、載入、錯誤重試與過期提示。
- 隱藏無文件的卡片；無工項改一行入口；右欄省略無值的來源欄位與日期。
- 不把日報活動、不同單位計畫量或任務完成數當工程實際完成率。

## 驗證

11 組相關測試通過：
`test-projects-list-model.mjs`、`test-projects-list-ui.mjs`、`test-overview-dashboard-model.mjs`、`test-report-links.mjs`、`test-project-overview-model.mjs`、`test-project-flow-round2.mjs`、`test-project-flow-ui.mjs`、`test-project-flow-model.mjs`、`test-project-disabled-reasons.mjs`、`test-project-progress.mjs`、`test-case-detail-view.mjs`。

`npx tsc -b`、`npx vite build --outDir /tmp/ui-projects/dist` 通過。Impeccable detector 回傳空清單。

瀏覽器實測 1440px 與 390px：單一搜尋、隱藏空群組、釘選／取消、清單／卡片切換、搜尋、待辦順序、空卡隱藏均通過；兩頁無整頁橫向溢出。

修改後截圖：`projects-after.png`、`project-after.png`、`projects-after-390.png`、`project-after-390.png`。修改前：`/tmp/ui-projects/projects-before.png`、`/tmp/ui-projects/project-before.png`。

## 既有問題與驗證限制

額外的 `test-ux-case-detail.mjs` 為 5 通過／5 失敗；用 HEAD 原始頁面與模型重跑同樣結果。它仍引用不存在的 `NodeAssignments` 元件及舊路由，不屬於本次頁面精簡回歸，未修改此舊測試。

基底後端的 `home_panels.py` 匯入不存在的 `backend.node_assignment.bulk`。為啟動指定 demo，僅在 `/tmp/ui-projects/run_demo.py` 載入既有 Git 物件 `c56c738:backend/node_assignment/bulk.py`；未修改或交付後端。示範資料 API 使用 8811，Vite 使用 5811。
