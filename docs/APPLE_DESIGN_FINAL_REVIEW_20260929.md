# Apple Design 獨立最後審查

審查對象：本機 `http://127.0.0.1:8794`，實際瀏覽器確認 `index-DZ6qwWrR.js` / `index-Bj1srCLy.css`。本文件初版結論對應此 bundle，後續修正須另註重測版本。

使用使用者指定 [apple-design SKILL.md](https://github.com/emilkowalski/skills/blob/main/skills/apple-design/SKILL.md)，不是只參考顏色。評估重點為操作的可預測性、立即回饋、資訊層級、可恢復性、鍵盤／手機可用性及減少動態效果。本次有具體審查任務，因此不使用 skill 的空白初次回應。

## 發現

| 等級 | 問題與證據 | 建議 |
| --- | --- | --- |
| P1，待修 | `ProjectExecutionNotice` 的 value/reason 不隨案件切換重置，`ProjectDetail` 也未 keyed。browser fixture：p1 是 workbench，填原因後切 p2（meegle），畫面屬 p2，選單仍 workbench、原因仍 p1；保存卻使用目前 p2.id，有誤改舊案執行歸屬風險。 | 以案件識別隔離表單，並處理同案伺服器歸屬更新與未存草稿衝突。 |
| P2，已量測 | 390px 正常 16px 根字級，完成節點按鈕高 34.8px、討論送出高 32.8px；觸控目標偏小。 | 手機常用提交動作的可點區域至少 44px；不必改大文字。 |
| P2，程式推論，待實測 | `InputRegistration` 提交前即 attempted=true，所有錯誤後皆鎖住內容；20,000 中文字可能超過後端 50KB 限制並回 422，但欄位無法縮短，也沒有放棄出口。 | 明確未受理的驗證錯誤可修正；網路未知結果維持固定識別與原內容，先核實再處理。 |

P1 已即時通報 root 與前端 agent。本 agent 未修改 frontend。歸屬重現只用攔截回應，封鎖全部非 GET 請求，沒有核定任何實際案件。

## 已檢查通過

- 390px、200% 根字級：任务抽屜無水平溢出、文字仍可讀、Enter 開啟、Tab 焦點限制、Escape 關閉並回原觸發按鈕、手機導覽焦點限制與 Escape。共 12 checks 通過。
- 案件五分頁於 1440、390、320px，共 15 組整頁無水平溢出，當前可見按鈕無匿名控制，頂部分頁清楚指向概覽／流程／日報／資料／紀錄。此輪沿用前一步 200% 根字級，屬壓力檢查。
- 另重設 16px 根字級後截正常桌面與手機畫面，目視確認留白、標題與次要資料層級、品牌藍灰色調、手機任務改卡片呈現。
- reduced-motion 實測抽屜 animation none、transition 0；程式檢查完成回饋在 reduced-motion 關閉彩紙、保留靜態成功訊息。沒有為測動畫去完成任何真實工作。
- 程式已有 reduced-transparency／increased-contrast 規則及按壓 :active 回饋。未逐色進行完整 WCAG 對比計算，不宣稱完整無障礙認證。

## 證據

- `output/playwright/apple-design-desktop-normal-20260929.png`
- `output/playwright/apple-design-mobile-normal-20260929.png`
- `output/playwright/apple-design-mobile-node-20260929.png`
- `output/playwright/apple-stale-assignment-20260929.png`
- `.runtime/apple-design-audit-20260929.js`、`.runtime/apple-design-visual-20260929.js`、`.runtime/apple-state-review-20260929.js`

使用獨立 `appleaudit29` 瀏覽器，未使用 root 的 Lark 後台 session。主要畫面是本機 demo；正式權限／歸屬測試屬明示 fixture，不是 Lark 端到端驗收。

## 新參考連結

使用者提供的 [Claude artifact](https://claude.ai/artifact/FWhSDShmKTejqkCoDtCKup) 已在獨立新分頁開啟並正常等待後重讀，均停於 Cloudflare 安全驗證。`output/playwright/claude-reference-20260929.png` 記錄當時畫面。未看到 artifact 本體，不能判斷其功能或宣稱已參考；未登入、未輸入憑證或繞過驗證。

## 修正版獨立複驗：ieKSvLZ6

前端 agent 修正後，本 agent 確认瀏覽器載入 `/assets/index-ieKSvLZ6.js`，原 P1 重現腳本再次執行：由 p1 切 p2，選單正確為 meegle、原因為空。**P1 已修正並獨立驗證，不再阻擋此版本部署。** `apple-stale-assignment-20260929.png` 已由同腳本重跑覆存，現在呈現修正後畫面；初始缺陷仍以本文件與第一次瀏覽器回執為證。

新增 `.runtime/apple-independent-retest-20260929.js` 共 10/10 通過：

- 同案件伺服器核定 signature 改變時，舊草稿保存按鈕禁用；強制 dispatch submit 也不會 POST；明確捨棄後清空。
- 17,000 個中文字超過 50KB 時，提交在前端即被阻止。
- 首次明確 422 未受理後可編輯，修正後使用新 request_id。
- 409 及模擬網路失敗均保留鎖定；其後重試得到 422 仍保持原 request_id 與原內容，沒有誤放過未知結果。

因此 Input 驗證錯誤無修正出口的 P2 亦已修復。手機觸控按鈕高度的 P2 仍列待改善；本輪不要求因此重新修改 freeze。測試使用獨立 fixture workspace 草稿 key，全部寫入請求在瀏覽器攔截，不是 Lark 實測。Claude 參考未讀取不阻擋上述修正版驗收。
