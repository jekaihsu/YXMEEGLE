# Apple Design：明顯改版後獨立複審

> **最新功能停用**：使用者後續要求訓練、能力認定與考評整塊停用。新前端 `index-y50n3cec.js` 移除相關入口和操作，Learning 模組不載入，舊 learning 深連結落到管理設定。下方訓練功能驗收僅保留歷史紀錄，不表示現在仍開放。班表與報價管理保留，能力地圖禁止回寫。

停用後 `npm run build` 通過；`apple-learning-disabled-final.js` 十項 UI 斷言通過：三個舊頁籤深連結及刷新不能進學習頁、導航及授權選項移除、能力／訓練背景重試移除、其他工作重試及班表管理保留、沒有發出 learning API 請求。背景工作列表使用明示 fixture；未寫正式資料。[停用後管理畫面](../output/playwright/apple-learning-disabled-management.png)。另以無網路 transport 獨立檢查 8 條 adapter 寫入路徑及 6 個環境政策全阻擋，GET／records search 仍允許，實際 transport 呼叫為 0。

> 最後版本補充：使用者最終核定詠翔官網藍色色調，參考逐步任務引導與真正完成回饋；不採 Duolingo 綠色外觀。2026-09-27 最後獨立 UI 複測為 `index-RusOTACw.js`／`index-CkGG0Dbq.css`（本機 8792），結果見本文件末段與公司準備度矩陣。以下較早版本記錄保留供追溯。

日期：2026-09-27。依據使用者指定的 [apple-design SKILL.md](https://github.com/emilkowalski/skills/blob/main/skills/apple-design/SKILL.md)，由未負責本次主要視覺改版的 reviewer 實際操作新版瀏覽器，並將發現交由實作者修正；最後由 reviewer 修正手機放大文字的局部欄寬與日期空狀態文案。

這份記錄補充[第一輪審查](APPLE_DESIGN_REVIEW_20260927.md)。第一輪主要修正可操作性與無障礙；本輪另明確檢查使用者要求的「簡潔留白、清楚層級、重整首頁與案件頁」是否有可見改變。這是依設計原則的專案審查，不是 Apple 認證。

## 視覺判斷

本輪有顯著的版面重組。首頁從四張指標卡與案件表格，改成「需要關注」工作清單優先、下方案件進度、右側正式案件／待確認接案分流與日報。案件頁新增預設概覽，先呈現任務完成度、有效期限、PM 與合約金額，再提供審核交付／流程任務入口及案件活動。側欄改為中性灰，藍色集中於操作與選取狀態；留白、分隔線、字級建立閱讀順序。沒有為模仿外觀添加無必要的玻璃或動態效果。

實際看過 1440px 桌面及 390px 手機截圖。手機主要內容依序排列，頁籤保持可橫向滑動，案件表格仍使用其內部捲動容器。

## 本輪發現與處理

| 等級 | 發現 | 結果 |
| --- | --- | --- |
| 中 | 首頁「今日」實際使用資料日期，示範資料 9/25 並非檢查當日 9/27 | 改成「工作總覽」、明列「資料日期」、使用「當日」及資料日期內空狀態 |
| 中 | 公司全量逾期工作入口開到「指派給我」，可能隱藏其他人的任務 | 全量入口帶 `tab=all`，MyWork 初始化所有任務；待審超過兩筆另有全部待審入口 |
| 中 | 新樣式部分主要中文說明退回 11px 與較淡顏色 | 提升至 12px 等值 rem，主要說明加深；高對比模式另有覆寫 |
| 中 | 390px、200% 文字下，案件完成百分比碰到右欄期限；整頁 overflow 指標仍為零 | 改為兩個可縮放等寬欄，重新實看截圖確認分離；不單靠 overflow 自動判斷 |

## 最终驗證

- `npm run build` 通過；最終產物 `index-CgxaXOQw.js`、`index-DgVupFJi.css`。
- 獨立本機 Chromium session `applevisual20260927`，`http://127.0.0.1:8791`，使用隔離示範資料。6 個正式案件、1 筆待確認接案；一個「報價 2」按鈕顯示同案兩筆報價。
- 15 項操作／狀態断言通過：資料日期、接案分流、Enter 開啟案件、單一多筆報價入口、任務初始焦點／焦點限制／Escape、首頁與案件 200% 文字無整頁溢位、收起導覽不可聚焦、手機導覽焦點限制／Escape、減少動態、高對比、所有任務範圍。
- 1440px 桌面、390px 手機重新截圖；正常文字首頁與案件整頁水平 overflow 均為 0。200% 文字另外人工查看截圖，修正欄位相碰後重驗。
- 新版來源狀態 fixture 重驗通過：535 筆日報、0 已配對、403 缺關聯、132 無法解析、182 確認單缺碼，六個數值及核對深層連結正確；首頁依結構化 mapping 顯示待核對。這是瀏覽器路由 fixture，不代表本輪重新讀取真實 Lark。測試結束清除 route 攔截。
- 最終瀏覽器 console：0 errors、0 warnings。

## 可查看證據

- 首頁：[改版前](../output/playwright/apple-after-desktop.png)、[改版後桌面](../output/playwright/apple-redesign-dashboard-desktop.png)、[改版後手機](../output/playwright/apple-redesign-dashboard-mobile.png)。前後均為示範資料，資料填充及頁面高度可能不同。
- 案件：[9/25 歷史流程頁](../output/playwright/meegle-project-desktop.png)、[新版預設概覽桌面](../output/playwright/apple-redesign-case-desktop.png)、[新版手機](../output/playwright/apple-redesign-case-mobile.png)。前圖是歷史流程入口，並非相同時間與資料的同頁截图；用途為辨認預設進入頁的結構改變。
- 放大文字：[首頁 200%](../output/playwright/apple-redesign-dashboard-text200.png)、[案件 200% 修正後](../output/playwright/apple-redesign-case-text200.png)。
- 可重跑腳本：`output/playwright/apple-redesign-inspect.js`、`apple-redesign-final.js`。只操作本機展示資料與頁面，不新增業務記錄。
- [來源待核對 fixture](../output/playwright/apple-source-mapping-fixture.png)，腳本 `output/playwright/apple-review-source-mapping.js`。

## 結論與限制

在本輪實測範圍內，首頁與案件頁已符合使用者要求的明顯重整，主要操作、閱讀順序與鍵盤／手機行為未因改版退步。此次沒有發現尚未修正的阻擋性介面問題。

未以這次本機 UI 驗證宣稱正式來源完成同步、原生審批串接完成或部署完成。正式來源仍須依主流程的 API／資料回放與部署紀錄判斷。未測試實體手機、Safari、螢幕閱讀器與完整 WCAG；顏色與動態檢查也不等於全站無障礙認證。

本報告完成後，使用者追加「大節點逐項補件完成／跳過節點審批」需求，由另一實作者接續處理；本輪 bundle 與測試結果只代表追加功能之前的視覺版本。新增功能須另行驗收。

### 追加流程獨立複查（新 Duolingo 風格之前）

在 8792 獨立 demo 瀏覽器 `appleux20260927`，對 `index-okhdmi88.js` 版本範圍的補件入口與快速完成流程進行檢查：

- 路由 fixture 八項通過：訓練設定入口、Input 指定節點／子頁、文件、能力設定、連線設定、班表人員與日期預填。沒有正式 API 寫入。
- 實際 demo 七項只讀操作通過：任務 Input 內容、空成果禁完成、附件 Output 預設、巢狀對話框焦點限制／Escape 返回、同節點附件返回保留草稿、390px 無整頁溢位。
- 實際刷新會丟失未送出成果文字，已重現並列 P1；不能將暫留本頁說成已保存。
- 快速完成的實際 task mutation 與雙人 skip 核准另由實作者驗收；本 reviewer 不把 fixture 列為正式業務端到端證據。
- 新 Duolingo 視覺／真完成回饋尚待實作者最終 build，此處不預先通過。

詳見 [公司使用準備度矩陣](COMPANY_READINESS_UX_20260927.md)，並保留兩種驗證的邊界。

## 追加需求之只讀阻塞流程檢查

下列是靜態程式碼查核發現的下一步導覽缺口，已交主 agent 及實作者；未假定核准者或放寬權限，亦未將建議記為已修正。

| 位置 | 被阻擋時目前行為 | 建議 |
| --- | --- | --- |
| `Learning.tsx` 訓練計畫 pending_mapping | 重存按鈕禁用，設定在其他頁籤 | 加前往能力地圖／儲存設定；非管理者明列需有管理來源權限者處理 |
| `Operations.tsx` JobList | blocked／failed 僅提供重試 | 依工作類型顯示對應設定入口，保留實際錯誤原因 |
| `Operations.tsx` ScheduleDeadline | 截止待設定班表／班表衝突僅文字 | 前往正常班表並帶人員、日期；不把晚打卡當正常下班時間 |
| `App.tsx` TaskInspector 暫停提示 | 說明等變更審批，沒有相關申請入口 | 可查看對應變更詳情；由既有審批流程恢復 |
| `Operations.tsx` DeliveryBatches 空佐證 | 提示先提交覆核，但不能直接前往 | 連到交付與確認並選正確技術節點；仍須原覆核角色處理 |

## 官網品牌與跨功能最後複審

已實際查看藍色首頁、手機案件、200% 案件及引導視窗。首頁增加「接續我的工作」，以實際可執行任務引導，阻擋項目顯示案號／節點及處理入口。這一輪檢查以操作、權限與狀態真實性為主，沒有把換色當成流程完成。

- 39 個獨立斷言通過：草稿／標註 10、完成回饋 9、評論焦點與失敗保留 5、API 權限投影與手機 8、提及收件與正式限制 7。
- 額外 200% 手機視窗實際捲動檢查：能到任務內容及成果欄、整頁水平 overflow 為 0；[實際視窗畫面](../output/playwright/apple-brand-guide-text200-visible.png)。
- 重現並修正評論送出後焦點掉出 drawer。最新版本成功與注入 503 失敗都回 textarea；使用者主動移焦不被奪回，已卸載的對話框不重新取得焦點。
- 真正 `completed` 的 mutation 回應才產生回饋；pending、核准跳過、初次載入及刷新均無慶祝。減少動態時沒有動畫／彩紙，回饋可關閉。此為明確 response fixture；完整核准後 API 實際完成由實作者另驗。
- 同名同部門有 ID 輔助辨識，停用者不列候選，email 中 @ 不打斷輸入。選人 Escape 只關選單，第二次才關父視窗。標註明示不發 Lark 訊息；收件入口直達對應案件／任務留言並高亮。
- 未儲存節點草稿關閉重開及同節點補件返回保留。取消跨頁保留原頁文字、beforeunload 有取消旗標；跨頁 confirm 以測試返回 false 驗證，未冒稱實體手機崩潰或關頁恢复。
- 真實本機 API 所有 task 都有 `can_execute`；PM 不自動擁有他人執行權。正式 skip fixture 顯示僅草稿與未連線，計價不提供跳過。財務與原生審批完整規則由後端測試另驗。

這輪腳本為 `apple-dirty-mentions-final.js`、`apple-comment-focus-final.js`、`apple-celebration-fixture.js`、`apple-brand-access-final.js`、`apple-inbox-formal-final.js`、`apple-guide-text200-final.js`。fixture 未寫正式資料；焦點負面測試故意回 503，對應 console 網路錯誤不當作產品新異常。測試最初錯用高亮 class／未限定同頁兩個評論欄的 locator，修正工具定位後重跑通過，未混記為產品缺陷。

UI 本輪未留下新發現的阻擋性操作問題，但資料 agent 第二輪重現了新日報關聯、上游改案、撤權競態與 skip 範圍失效問題；**因此不能因這份 UI 審查通過就宣布全面正式上線**。最新界線與未解事項見 [COMPANY_READINESS_UX_20260927.md](COMPANY_READINESS_UX_20260927.md)。
