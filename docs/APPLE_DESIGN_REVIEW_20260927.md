# Apple Design 獨立介面複查 — 2026-09-27

本輪由未參與原始介面實作的 agent，在整合後依使用者指定的 [apple-design SKILL.md](https://github.com/emilkowalski/skills/blob/main/skills/apple-design/SKILL.md) 進行獨立檢查、修正及重測。另依本機 Playwright skill 操作真實 Chromium。這是依該技能進行的設計與可用性審查，不是 Apple 認證或完整無障礙認證。

## 範圍與環境

- 已讀 `docs/HANDOFF_20260927.md`，保留本對話核定的案件、報價、訓練、正常班表及資料真實性規則。
- 僅使用 `http://127.0.0.1:8791`、隔離資料庫 `.runtime/review-20260927.db`、Playwright session `apple20260927`。
- 測试資料為明確標示的虛構案件、兩筆報價、能力目錄及本機新增的訓練／事件。此審查沒有寫入正式 Lark、寄出通知或操作正式案件。
- 實看桌面 1440×900、手機 390×844；驗證鍵盤操作、200% 文字、減少動態及提高對比。

## 發現與處理

| 等級 | 問題與影響 | 修正及重測 |
| --- | --- | --- |
| 高 | 對話框與任務側欄沒有完整焦點圈限，鍵盤可進入背景 | 共用 `useDialogFocus`：初始焦點、Tab／Shift+Tab、Escape、返回來源及背景滾動限制；真瀏覽器通過 |
| 高 | 案件／任務表格只有整列滑鼠點擊可開啟 | 案件改原生連結、任務提供原生按鈕；Enter 開啟成功 |
| 中 | 關閉任務會離開原流程頁，焦點來源消失 | 任務直達路由保留 `tab=flow`；Escape 後原任務按鈕仍獲焦點 |
| 中 | 低高度桌面側欄下方身份入口被擠出 | 側欄可獨立捲動且內容不被壓縮；已實際切換示範角色 |
| 中 | 手機關閉導覽仍可能被鍵盤走訪，缺少明確关闭控制 | 關閉時 visibility 隱藏；開啟採對話框語意、有關閉按鈕與焦點圈限，Escape 返回開啟按鈕 |
| 中 | 大量 8–10px 小字與低對比次要文字 | 內容文字改 rem、次要內容最低 12px 等效值，系統字體；深化淡色文字，保留語意色。裝飾性品牌英文／頭像縮寫例外 |
| 中 | 手機操作目標小、縮放與長文可能擠壓 | 主要手機操作目標至少 44px，表單字體 16px，標題／工具列可換行；390px 與 200% 文字無整頁水平溢位 |
| 中 | 通用 verified 標籤直接稱「已核實存入 Lark」，可能讓本機收付核對被誤讀為遠端成功 | 改為通用「已核實」；訓練仍獨立顯示認定與遠端存回狀態 |
| 中 | 節點檢核資料缺少時可能顯示已齊備 | 明確顯示結果尚未取得並停用送交按鈕 |
| 低 | 部分控制沒有按下即時回饋；缺少高對比與減少透明度分支 | 增補 :active 顏色回饋、高對比邊框、實色替代；保留減少動態規則 |

保留業務工作台的清楚表格、層級及狀態。未加入多餘玻璃、彈跳、手勢或音效。

## 整合時補齊的操作入口

- 案件「審核與交付 → 事件與期限」：9 種 SOP 事件、佐證、日期、組別、版本更正、主管期限核對與計算依據。既有契約與已開工限制由後端驗證；UI 不提供直接強行覆寫。
- 管理設定增加測試連線模式：預設全模擬，或僅 Input／文件的隔離真實測試。說明專用 Base／Drive 與伺服器設定須一致，通知、訓練及能力仍維持模擬。

## 實測結果

| 檢查 | 結果 |
| --- | --- |
| `frontend/npm run build` | TypeScript 與 Vite 通過；最後 bundle `index-yAng1eNW.js`、`index-CFHhWgIQ.css` |
| 對話框初始焦點、Tab／Shift+Tab、Escape 返回 | 通過，5 項桌面断言全為 true |
| 任務鍵盤開啟、圈限、關閉返回 | 通過 |
| 單一「報價 2」入口與兩筆報價 | 通過；未以兩筆報價新增兩案 |
| 手機頁面不整頁水平溢位 | 通過；資料表及分頁列保留自身水平捲動 |
| 200% 使用者文字設定 | 訓練頁通過；內文字體與版面一起放大 |
| 減少動態／提高對比 | 減少動態下 animation=none；高對比 header 邊框為 rgb(57,67,85) |
| 訓練實際表單 | 本機新增→提交成果→講師通過→能力核准，4 次 API 操作成功 |
| 訓練狀態真實性 | 顯示「認定核准、待存回」「寫入目的待設定」；未稱已更新正式能力地圖 |
| SOP 事件實際表單 | 本機 POST 成功，產生工作及期限依據並顯示於頁面 |
| 瀏覽器 console | 最後 session 查詢 0 errors、0 warnings |

審查過程另修正一個測試定位器：事件下拉改用其明確 name；一次腳本失敗是 locator timeout，後續表單送出與讀回畫面已通過。200%／任務側欄測試找出上述回到错误分頁問題，修正後重跑全數通過。

## 留存證據

- [桌面修正前](../output/playwright/apple-before-desktop.png)、[桌面修正後](../output/playwright/apple-after-desktop.png)
- [兩筆報價集中同案](../output/playwright/apple-quotes-desktop.png)
- [期限桌面](../output/playwright/apple-deadline-desktop.png)、[期限手機](../output/playwright/apple-deadline-mobile.png)、[事件送出後](../output/playwright/apple-deadline-saved.png)
- [訓練核准待存回](../output/playwright/apple-training-status-desktop.png)、[手機狀態](../output/playwright/apple-training-final-mobile.png)
- [200% 文字](../output/playwright/apple-text200-mobile.png)、[減少動態／高對比](../output/playwright/apple-accessibility-mobile.png)
- 可重跑腳本：`output/playwright/apple-review-desktop.js`、`apple-review-mobile.js`、`apple-review-forms.js`、`apple-review-sop.js`、`apple-review-final.js`。Forms／SOP 腳本只應對隔離示範環境執行，會新增本機測試資料；不應對正式環境執行。

## 獨立結論及界線

本次覆查範圍內的主要鍵盤、手機與狀態誤導問題已修正，已實際重測。桌面與手機主要流程可繼續驗收。

本報告不證明正式來源權限已開通、Lark／Drive 已寫入成功、正式審批／通知已串接，亦不代替後端資料去重、角色授權與完整 SOP 測試。主 agent 正另行處理正式連線驗證，須以其遠端讀回證據為準。未以真實手機、Safari、螢幕閱讀器或實際員工進行完整使用者測試；減少透明度分支已做程式檢查，未列為真實裝置驗證。
