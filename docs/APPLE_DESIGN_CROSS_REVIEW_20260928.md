# Apple Design 獨立交叉審查 · 2026-09-28

審查者 `/root/finish_ui_audit`，與原介面實作者分開。採用使用者指定的 [apple-design SKILL.md](https://raw.githubusercontent.com/emilkowalski/skills/main/skills/apple-design/SKILL.md)，重點是操作回饋、層級、可預測導覽、焦點、文字放大與減少動態，不是 Apple 官方認證。

本次實際啟動獨立 demo `http://127.0.0.1:8794`，瀏覽器 session `finalcross28`，沒有修改遠端業務資料。前端 TypeScript 與 Vite 建置通過。

## 結論與修正

在本次範圍內，35 項本機瀏覽器布局／鍵盤檢查通過。另 19 項明確攔截 fixture 驗證狀態顯示與終態按鈕保護通過；不得當作 Lark 真實串接成功。

發現並修復一項缺口：財務申請已 rejected／withdrawn／invalidated／canceled，但殘留 `native_binding.status=prepared` 時，原介面仍顯示「送出至 Lark」。`NativeApprovalControls.tsx` 現在優先檢查申請終態與已套用時間，隱藏核對及送出入口。四種終態均重新實測：正確原因、無財務完成入口、無重新送出入口，共 12 項通過。這是介面防誤導修正，不能代替後端授權檢查。

本輪修正版 bundle：`index-BCoPSSh5.js`、`index-bMhteLtr.css`。主代理通知前一版 `index-CJvSUYKp.js` 已部署 demo；本修正尚待下一次整合部署，不能宣稱遠端已含修正。

## 可重跑證據

| 腳本 | 結果 | 驗證範圍 |
| --- | --- | --- |
| `frontend/qa/ui_independent_navigation_20260928.js` | 23 / 23 | 五分頁、舊深連結、單一報價入口、操作區移出任務外框、財務無直接帳务入口、900／390px 無水平溢出、200% 文字、文件分類及用途、Escape |
| `frontend/qa/ui_independent_keyboard_20260928.js` | 12 / 12 | 390px＋200% 文字、Enter 開任務、對話框無水平溢出、reduced motion、Tab 焦點留在對話框、Escape 返回原按鈕、手機導覽焦點約束 |
| `frontend/qa/ui_terminal_review_20260928.js` | 12 / 12 fixture | 四種財務終態不得完成或重送，混入舊 prepared binding 仍以終態優先 |
| `frontend/qa/ui_independent_attendance_20260928.js` | 7 / 7 fixture | 員工識別未核實明示、無成功回執不稱成功、跨日完整日期與 +1 天、Attendance／人工分別標示、查詢日期、demo 禁止正式同步 |

執行方式：啟動上述本機 demo，再用 `python scripts/browser_step.py <session> <script>`。前兩項使用本機 demo 真實 API，後兩項僅攔截 session／workspace／Attendance 回應，未向 Lark 提單或查班表。

200% 指 document 根字級 200%，搭配 390px 視窗重排，不等同所有作業系統顯示縮放／Safari Dynamic Type 均已測試。

## 視覺與互動檢視

已實際開啟檢視：

- `output/playwright/independent-cross-task-200percent-20260928.png`：任務日期可換行，手機對話框主操作仍可見，焦點外框清楚。
- `output/playwright/independent-flow-review-viewport-20260928.png`：工作內容選單、交付缺件卡、節點確認、案件討論各自有層級；沒有八個內層頁籤互相競爭。

另外留存 `independent-flow-desktop-20260928.png`、`independent-flow-390-20260928.png`、`independent-task-200percent-viewport-20260928.png`、`independent-attendance-status-20260928.png`，位於 `output/playwright/`。

詠翔藍色保持一致；此輪沒有增加無關裝飾或用動畫替代交付狀態。實測 reduced motion 下任務對話框 animation 為 none、transition 為 0s，仍保有靜態資訊與明確操作入口。

## 尚未驗收的邊界

- 真實 OAuth、人員名冊、Lark 原生審批核准／撤回、標註送達、Drive 上傳讀回、Attendance 員工班表，須由整合驗收取得真實回執。
- 本機 UI 通過不能代表正式環境权限／資料或部署已完成。
- 未進行完整 WCAG 對比稽核、螢幕閱讀器、所有瀏覽器與手機實機驗收；未據此宣稱全面無障礙合規。
- 使用者尚需以實際日常工作確認操作效率；本次沒有代替公司人員做業務驗收。
