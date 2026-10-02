# 公司正式使用準備度：產品與 UX 獨立檢查

> **最新決策覆蓋**：訓練、能力認定與考評整塊停用，只保留管理；能力地圖禁止回寫。下方較早訓練流程與能力 E2E 缺口是歷史審查，不再列為目前須啟用的功能。前端 `index-y50n3cec.js` 已移除導覽與模組載入，舊 learning 深連結導向管理；班表／報價管理仍保留。詳見 [停用決策](LEARNING_DISABLED_DECISION_20260927.md)。

檢查日期：2026-09-27。依已核定需求、前後端契約、實際本機瀏覽器結果，以及資料 agent／視覺實作者交叉討論整理。本文件不把外觀改版、單元測試或模擬流程通過當作正式端到端驗收。

**末輪更新**：使用者最終方向是詠翔官網藍色色調，參考 Duolingo 的逐步任務、回饋與繼續操作功能，不採綠色配色。獨立複測 bundle `index-RusOTACw.js`／`index-CkGG0Dbq.css`，本機 8792。末輪 UI 新增 39 項断言通過（草稿與標註 10、完成回饋 9、評論錯誤／焦點 5、權限／手機 8、收件入口與正式限制 7）；其中明確分列 fixture 與真實本機 API 投影，沒有正式 Lark 寫入。

## 目前判斷

已有可操作的內部試用基礎，不能直接視為公司全面正式上線完成。正式資料的待核對量、原生審批未實作、正式能力／寫入回執未完成端到端，以及本輪查出的 API 資料投影問題，都是外觀無法解決的落差。建議採有限人員、有限案件的隔離試營運；正式流程不可依賴模擬核准或模擬回執。

P0 表示全面正式使用前阻擋，P1 表示試營運需補足或明確限制範圍，P2 表示後續品質改善。嚴重度依實際使用影響，並非開發工作量。

## 準備度矩陣

| 優先 | 項目與具體證據 | 影響／完成條件 | 本次狀態 |
| --- | --- | --- | --- |
| P0，已修復待部署確認 | 資料 agent 發現 workspace API 回傳非本人請假代理資訊與完整 migration archive；`Operations.tsx` 原本只有前端 filter | 前端隱藏不等於授權；正式上線須以伺服器 projection 隔離並補越權測試 | source agent 已修 GET／mutation／回執重播；67 項相關測試通過，見 BACKEND_READINESS_REVIEW；不等於線上部署完成 |
| P0（若要取代正式審批） | `backend/approval_capabilities.py` 的 native_submit 與三類 by_type.available 均為 false，blockers 明列功能未完成／映射未核／結果綁定未核／真實 E2E 未驗 | 變更、展延、跳過只能正式草稿；必須完成真實送審、正確案件版本核准回傳後才能接手公司正式審批 | UI 正確停用送審；功能缺口未消失 |
| P1，歷史遷移範圍 | 真實來源讀取 ready，但資料 agent 回報 535 舊日報中 0 已配對、403 缺關聯、132 無法解析，182 確認列缺工程確認碼；使用者已說明舊系統遷移背景 | 不能把零配對當作沒作業；應獨立定義舊資料回補範圍，不從這批數字推論新日報一定失敗 | 來源頁有結構化計數／核對入口；新日報正確性另看第二輪回歸 |
| P1，離開警告已補；持久恢復可後續改善 | `NodeCompletion` 草稿仍是頁面記憶體；新增 useDraftNavigationGuard | 關閉／同節點補件返回保留，離開或刷新需警告；仍不能稱自動保存或斷電恢復 | 末輪關閉重開、取消跨頁保留、beforeunload取消旗標通過；跨頁 confirm 以測試返回 false，非實體手機恢復測試 |
| P1，前端契約已修 | `NodeSkipPanel` 原 canRequest 比 `backend/node_skip.py` 寬；已投者仍有按鈕 | 逐動作對齊後端，已投票改顯示等待另一人 | 已拆 canCreate／canSubmit／canWithdraw，隱藏已投者再投；獨立正式 fixture 驗草稿限制及計價不可跳，實際雙人票由 visual 另驗 |
| P1 | 能力／訓練／Input／文件的假 HTTP 或 demo 成功不是正式回執；`Learning.tsx`／Operations 狀態目前分開 simulated、verified、pending_mapping | 限定試用；正式驗收需真實寫入後讀回、失敗重試與重複提交驗證 | UI 未見把 simulated 當正式成功；正式 E2E 仍未完成 |
| P1 | Attendance 有 punch，但正常班表尚未接妥；`ScheduleCutoff` 缺班表顯示待設定並提供補件 | 不得以實際晚打卡或固定 17:00 計截止；須取得排定班表或有核對依據的人工作法 | 補班表入口與人員／日期預填 fixture 通過；來源串接未完成 |
| 已通過 UI 回歸 | 逐步功能與真完成回饋、最後採官網藍色 | `pending`、approved_skipped、初次載入／重新整理不播；completed 回應才播 | 九項獨立 response fixture 通過，減少動態不播彩紙；實際完整確認 API 由 visual 另驗，不混成正式 E2E |
| P2 | `engineering_complete` 顯示工程完成、財務待結，可能包含核准跳過；節點本身另有核准跳過標籤 | 建議在總狀態旁註有幾個核准跳過，避免閱讀者以為所有技術成果都完成 | 已向 source agent 提出交叉挑戰 |
| P2 | 主介面已驗桌面／手機／200% 文字／鍵盤，但未測實體 iOS Safari、螢幕閱讀器與全站對比 | 專業使用需要真實使用者任務驗證、設備與輔助技術抽測 | 保留明確驗證範圍，不宣稱 WCAG 或 Apple 認證 |
| P2 | 備份已有人工一次性真實 backup＋restore 演練，但每日排程仍未設定；主 agent 指出排程工具尚未協調停寫一致性 | 分開顯示最近人工演練與自動排程狀態；不能把手動成功說成每日自動備份已驗收 | 現有「排程尚待設定」文案屬實，無需改成已啟用 |

## 已有實證的能力

- 前一輪明顯改版通過，見 [獨立視覺複審](APPLE_DESIGN_REDESIGN_REVIEW_20260927.md)：首頁重整優先工作與正式／接案分流，案件預設概覽，單一「報價 2」入口保留兩筆同案報價。這是示範資料驗證，不等於真實來源配對完成。
- `output/playwright/apple-readiness-fixture.js` 在獨立 8792 session 驗證八個導向斷言：訓練待設定 → 能力設定；背景工作 Input → 實際 project/node/inputs，file → files，capability → map，digest → settings；班表 → settings 預填人員與日期。使用瀏覽器路由 fixture，測後清除，沒有正式寫入。
- `output/playwright/apple-quicknode-readonly.js` 在 8792 獨立 demo 實際檢查任務內容、空成果禁完成、附件對話框 Output 預設、巢狀焦點限制／Escape 返回、同節點草稿往返與 390px 無整頁溢位。僅切換本機 demo 角色與輸入未提交文字，沒有送出完成任務或文件。
- 視覺實作者的 `quick-node-review.js` 與 `quick-node-submit-review.js` 另有實際本機三任務逐筆保存、缺交付禁送、補件返回、送審後 node 仍 in_progress 且 review pending 的證據，詳見 [逐項完成記錄](GUIDED_NODE_COMPLETION_20260927.md)。這部分是交叉讀取實作者證據，沒有誤標為本 reviewer 重跑全流程。

證據畫面：[班表預填 fixture](../output/playwright/apple-readiness-schedule-fixture.png)、[逐項完成草稿與手机](../output/playwright/apple-quicknode-draft-mobile.png)。

## 交叉挑戰結論

資料 agent 強調連線 ready 不等於配對 ready、模擬票不等於原生 Lark E2E、正常班表不能由打卡推算；UX reviewer確認現有 label 大致誠實，但仍要求對實際狀態、適用範圍與下一步保持一致。視覺實作者確認草稿只在同節點頁面記憶體保留，本 reviewer 用刷新重現資料清空，列為 P1，而不是以成功截圖掩蓋。

正式採用所差的重點是可靠性與可追溯的營運閉環：誰處理來源缺漏、如何確認原生核准、輸入丟失如何恢復、無權限時交給誰，以及收到成功訊息是否有真實回執。這些完成後才適合將更多正式案件與人員切入；不能從界面完成度推算一個看似精準的上線百分比。

## 第二輪跨 agent 挑戰：仍阻擋正式採用的資料問題

資料 agent 的 [第二輪後端審查](SECOND_BACKEND_REVIEW_20260927.md) 新增四個嚴格預期失敗案例；沒有把 xfail 計為驗收成功。本節為交叉收到的重現證據，修復狀態以該報告及後續全測為準。

- 混合有效與未知原生關聯被認為唯一配對；可能把新日報歸到錯案。上線前必須保守待核對。
- 上游合約改案但日報本身未變，既有人工配對未失效；需追蹤依賴變動。
- learning mapping 核實中撤除權限仍保存；正式操作應在提交時再次確認授權。
- 報價範圍變動未使既有 skip waiver 失效；正式 skip 目前被阻擋，因此是啟用前必要条件，不是已發生的正式跳過漏洞。

另有外業組長／組員原生 actor 映射漏接待 owner 修正；不能靠 UI 正確顯示原始資料就說角色指派正確。

## 最後 UI 驗收證據與限制

`apple-dirty-mentions-final.js`：十項通過，含兩次 Escape 的不同層級、同名同部門 ID 區分、停用人不出選項、email @ 不打斷。標註明示僅工作台內，不送 Lark 訊息；未將 demo 名冊視為正式人員同步驗收。

`apple-comment-focus-final.js`：五項通過。先重現送出後焦點掉出 drawer，root 修正後成功／503失敗皆回到 textarea，失敗留字；忙碌時主動移焦不搶回，已關閉視窗不復活。503 由測試刻意回傳，console 中對應網路錯誤屬注入案例。

`apple-celebration-fixture.js`：九項通過，驗證的是前端如何解讀回應，而非後端核准規則。`apple-inbox-formal-final.js`：七項通過，任務與案件提及都直達留言，任務留言高亮；正式跳過只顯示草稿與未連線、計價無跳過入口。

`apple-brand-access-final.js`：八項通過；真實本機 API 每 task 皆有 can_execute，PM 不因角色取得別人的執行權。UI 唯讀並提供責任交接入口。代理 fresh／撤回／停權等 46 項整合及 21 項專項由資料 agent 驗證，見其報告，並非本 reviewer 模擬代理即宣稱通過。

已實看[最後首頁桌面](../output/playwright/apple-brand-dashboard-desktop.png)、[手機案件](../output/playwright/apple-brand-case-mobile.png)、[200% 案件文字](../output/playwright/apple-brand-case-text200.png)。目前獨立新 session 是 7 個 demo 正式案／0 接案／0 報價；前一輪 6／1／2 是不同隔離 fixture，不拿不同資料做假同一驗收。既有多報價和分流實證保留在前輪報告。

另以 `apple-guide-text200-final.js` 實際捲動手機 200% 引導視窗，確認任務內容與成果欄可到達、整頁 overflow 為 0；不是僅憑頁面沒有溢位推論內容可讀。[可到達成果欄的畫面](../output/playwright/apple-brand-guide-text200-visible.png)。
