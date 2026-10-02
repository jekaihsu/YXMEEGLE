# 最新決策：詠翔品牌 × 逐項工作引導

> 此段是最新核定，取代下方早期草綠方向。使用者明確指出希望參考 Duolingo 的重要功能，而非套用其配色；應使用詠翔官網色調。

## 品牌證據

2026-09-27 以獨立瀏覽器讀取 https://www.yxsurvey.com.tw/ ，頁面標題「首頁 - 詠翔測量工程有限公司」。實際 CTA 背景 `rgb(12,84,148)`，即 `#0c5494`；白色導覽、深藍區段與中性文字構成主要色調。

- [官網實際截圖](../output/playwright/yongxiang-official-reference.png)
- `brand-reference.js` 讀取實際 computed style，未猜測或複製第三方品牌色。
- `brand-workspace.css` 取代 `playful-theme.css` 的載入；早期綠色檔保留為歷程，未由 main 載入。主要按鈕、路徑、完成回饋已統一詠翔藍。

## 功能參考的落地

1. 首頁與案件概覽的「接續我的工作」依 server `can_execute` 選擇目前可操作的任務；優先接續已開始的工作，再按期限排序。新任務先查看內容，使用者自己按開始，導航不暗中寫開始紀錄。
2. 跳至指定任務的逐項完成視窗。實際作業說明／Input、成果輸入、附件與明確的開始／完成操作皆保留；成果成功保存後呈現回饋，轉下一項。不同生產節點可合法平行，不強制排成遊戲關卡。
3. 有前置成果、暫停、來源中止或外業證明阻擋時，首頁列明原因与案號，可進入對應的補件流程。後端仍在真正操作時重新驗證，前端判斷不是授權替代。
4. 階段路徑顯示已完成、待你處理、待他人處理、待補齊條件、待節點確認或核准跳過。`approved_skipped` 不算任務成果完成，待審與完成分開。
5. 同一節點內的成果草稿與跳過申請文字保留在記憶體；關閉再開視窗、前往附件或责任頁再返回仍可接續。跨節點、切身分或刷新會提醒未保存文字。沒有跨 session 自動儲存，未宣稱已具備。
6. 真正大節點從非 completed 轉成 completed 才播放一次完成回饋；待審、跳過、小任務完成、首次載入與刷新不播放。減少動態使用靜態成功卡。

## 本輪驗證範圍

隔離 8792 最新後端實測 9 項全過：投影存在、官方藍 computed style、首頁直達正確任務、導航零隱藏 mutation、實際 output 保存/任務 completed、明確完成 request、小任務不誤播、390px 流程與首頁無水平溢位。本次任務原本已開始，writes 只有 task_complete；明確開始按鈕的真實 task_start 已由前一輪 quick-node 測試驗證，未將本輪說成再次驗過開始。

- `output/playwright/brand-workflow-review.js`
- [首頁](../output/playwright/brand-dashboard-desktop.png)、[逐項操作](../output/playwright/brand-guided-desktop.png)、[階段路徑](../output/playwright/brand-flow-desktop.png)
- [手機首頁](../output/playwright/brand-dashboard-mobile.png)、[手機流程](../output/playwright/brand-flow-mobile.png)

| 項目 | 狀態 | 邊界 |
| --- | --- | --- |
| 首頁→指定任務→實際成果→下一項 | 本機後端＋瀏覽器通過 | 僅隔離示範資料 |
| 大節點真完成動畫 | 本機真 review_vote 通過 | 不代表正式 Lark 原生審批通過 |
| 跳過雙人確認與 PM 套用 | 8 項真 demo UI/API 通過 | 正式 Lark 送審仍 disabled，僅可草稿 |
| 任務代理身分 | 前端完全採 server can_execute | 有效/無效代理整合由 backend 專項測試驗證 |
| Apple 獨立 UX 驗證 | 持續複查最新版 | 以獨立 review 文件的問題矩陣為準 |
| 公司正式使用 | 未宣稱完成驗收 | 權限、正式審批、來源/人員同步仍由主代理追蹤 |

以下保留早期設計與驗證歷程，配色以本段為準。

---

# 進度導向的活力工作台

使用者在前一版留白改版後，進一步指定參考 Duolingo 的整體設計及節點完成動畫。本轮優先採用最新決策，同時保留已核定的資料真實性與案件工作流程。

## 設計主張

- 暖白工作面、清楚的草綠主動作、圓角互動項目與可感知的按壓回饋；狀態用文字與圖形一起表達。
- 將案件任務視為有目標的進度路徑，首頁仍以待處理工作為主，正式案件／接案分流及可讀表格保留。
- 完成回饋僅依伺服器回傳的節點 `status` 真正從非 completed 轉為 completed；送交審核 pending 或核准跳過 approved_skipped 不触發完成慶祝。
- 成功卡不搶焦點、不播放聲音、可關閉；短彩紙只播放一次。偏好減少動態時只顯示靜態成功卡。
- 使用自己的品牌符號與文案，不使用 Duolingo 商標、角色或吉祥物。

## 檔案責任

視覺 agent 持有 `App.tsx`、`workbench.css`、新增 `CompletionCelebration.tsx` 與 `celebration.css`。主 agent 維護 Learning／Operations 的補件導向；來源 agent 維護跳過審批後端；Apple agent 最後獨立驗證。

實作、截圖及測試結果完成後補記。

## 官方設計參考

主 agent 已查閱 [Duolingo 里程碑與動畫](https://blog.duolingo.com/streak-milestone-design-animation/)、[核心頁籤重設計](https://blog.duolingo.com/core-tabs-redesign/) 及 [官方圖像設計原則](https://design.duolingo.com/identity/imagery)。本輪採清楚目標、統一頁面語彙、可視進度、完成里程碑與精確回饋；未加入扣分、連續天數壓力或吉祥物。

## 實作狀態

- `playful-theme.css` 統一首頁、案件、流程、按鈕、表格、modal、逐項完成視窗的綠色與圓角設計，資料表仍保留可讀欄位。
- 主要綠按鈕採白字／`#46821f`，計算對比約 4.69:1；明亮的較淡綠色用於背景、進度與裝飾。
- `CompletionCelebration.tsx` 僅由 `App.run` 的成功 API 回傳比對呼叫。初始載入與 refresh 沒有呼叫完成偵測。
- 只有既有節點從非 `completed` 轉為 `completed` 才產生完成回饋；新匯入節點不觸發。`pending`／`approved_skipped` 不觸發。
- 成功卡不搶焦點、沒有聲音、可按 44px 手機關閉控制；9 秒後自動收起，完整成果仍在案件紀錄中。減少動態時無彩紙或彈跳。
- 未儲存成果與跳過草稿使用記憶體保存；離開不同節點、切換示範身份或刷新會提醒，未採用可能跨使用者混用的瀏覽器儲存。

初次整合建置通過：`index-_pFWSopn.js`／`index-BANjmBOi.css`。另一位 Apple Design agent 正獨立複查新版本，後續修正以最終建置為準。

## 已取得的實際證據

在 8792 隔離示範服務，先以既有後端 API 準備明確標示的任務及佐證，再於瀏覽器實際送出 `review_vote`：

- 伺服器回讀 `review.status=approved`、`node.status=completed`。
- 完成卡出現且焦點沒有被移入卡片。
- 關閉卡片後重新載入，同一已完成節點不再播放。
- [實際節點完成回饋](../output/playwright/playful-real-completion.png)。腳本 `completion-real-review.js` 修改隔離示範資料，不能對正式工作區執行。

新視覺的桌面首頁、案件清單、案件概覽、流程，以及 390px 手機首頁、概覽、流程共七頁均無整頁水平溢位；流程圖及資料表仍保留自身橫向捲動。

- [首頁桌面](../output/playwright/playful-dashboard-desktop.png)、[案件桌面](../output/playwright/playful-projects-desktop.png)、[案件概覽](../output/playwright/playful-case-desktop.png)、[流程路徑](../output/playwright/playful-flow-desktop.png)
- [手機首頁](../output/playwright/playful-dashboard-mobile.png)、[手機概覽](../output/playwright/playful-case-mobile.png)、[手機流程](../output/playwright/playful-flow-mobile.png)

以上是本機後端與瀏覽器實測；沒有正式案件或 Lark 審批寫入。待審／跳過不播放、減少動態、200% 文字與未儲存提醒由獨立 Apple agent 複查。

## 官網版本追加驗證

第二次使用新版首頁引導 pending 任務，實際瀏覽器錄到 task_start、task_complete 依次由使用者操作，9 項仍全過。導航階段未送 mutation；伺服器保留完成成果。左側『我的工作』數字另修為當前 can_execute 的逾期數，文字明示『逾期 N』，避免與接續工作的全部待處理數混淆。


最終官網品牌建置：index-BdOjy6A-.js / index-DQIchZA-.css。重取首頁、案件概覽、流程桌面與 390px 手機共六張截圖，三個手機頁皆無整頁水平溢位；使用減少動態模式擷取，避免進場中間影格影響文字清晰度。


## 標註後的可發現入口

我的工作新增 MentionInbox（主代理元件），只列目前可見資料中 mentions 含當前 user ID 的案件與任務留言。只稱『標註紀錄』，無未讀／外部推播承諾。點擊帶 comment 真實 ID，案件導向討論、任務直接開評論頁籤；使用 React ref 捲動定位並標示，不串接 CSS selector。8792 真 demo 新增兩筆標註後切換收件人，6 項通過：兩種直達與 viewport、任務頁籤、390px 無溢位。腳本 output/playwright/mention-inbox-review.js；截圖 mention-inbox-target-desktop.png、mention-inbox-mobile.png。整合建置 index-DxWZ6zNs.js / index-CkGG0Dbq.css。

