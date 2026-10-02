# 前端正式流程整合紀錄 — 2026-09-29

## 本批完成並凍結

- 管理健康頁接 runtime-health，區分無紀錄、未配置、過期與健康；不把程序健康當作 Lark 業務成功。
- 案件歸屬顯示 pending / meegle / workbench。管理員可核定歸屬；待核定及 Meegle 舊案禁止新業務操作，保留查閱與既有審批查回、撤回。後端 gate 才是權限依據。
- 名冊過期 recovery session 不讀完整 workspace，提供名冊重同步、健康與登出；加入畫面錯誤邊界避免整頁白屏。
- 正常上傳後顯示自動排入 Drive 背景工作，不再要求第二次按保存。queued 不呈現為 verified；舊檔無回執及失敗結果導向核查。
- 正式 Input 改獨立作業資料登錄：名稱及內容兩欄、隱藏固定技術 key、保留 request_id 草稿供同一請求重試；結果不明只能查回。尚無核定的語意欄位字典，沒有宣稱已自動對應來源格子。
- Native 送出遵守 by_type.available 總開關；原申請人可撤回既有 Lark 審批，未知結果不重送。唯讀案件仍保留清理既有申請入口。
- SOP 來源不完整時顯示部分盤點警示，不聲稱等價模板已完成。

## 驗證與產物

- TypeScript / Vite build 通過：`frontend/dist/assets/index-DZ6qwWrR.js`、`index-Bj1srCLy.css`。
- `frontend/qa/ui_cutover_health_20260929.js`：13 項 fixture 瀏覽器檢查通過（歸屬、健康、recovery 不讀案件）。
- `frontend/qa/ui_drive_auto_20260929.js`：5 項本機 demo 真 upload 檢查通過。僅本機檔案及本機背景排程；未傳入 Lark。
- `frontend/qa/ui_input_native_20260929.js`：9 項 fixture 檢查通過：無技術 ID、失敗保留草稿、同 request_id 重試、固定 key、未知唯讀查回、總開關、唯讀查回/撤回、撤回不重送。
- 獨立本機 8794 與 browser finalcross29 執行。Fixture 攔截 API，不能算真實 Lark 提單、撤回或 Input 登錄驗收。
- 這批尚未部署；交 root 部署。Apple Design 最终獨立複查另行執行。

## 尚未完成的功能範圍

1. 第二 Meegle 模板 566082 仍待取得真實完整定義；334662 v137 的盤點不代表兩模板皆實作。
2. 四份 SOP 的穩定節點/子任務映射、角色、啟動條件、並行與條件分支、必填資料及附件欄位仍需完整 crosswalk 與引擎驗證；保存條件原文不等於可執行條件。
3. 模板升級須保留已完成成果、歷史、人工責任人；未完成等價升級測試。薪資/訓練相關來源節點僅盤點，不啟用。
4. 真實 Drive 上傳下載 SHA 比對、Input 登錄查回、原生審批提單/撤回仍需獨立正式連線驗收；本批只驗 UI 契約。
5. 部分共用操作按鈕在提交前顯示唯讀原因，並非全數隱藏；後端必須持續以 execution gate 強制阻止寫入。

## Apple 獨立審查後修正

- 發現 P1：歸屬核定草稿在切換案件時沿用。現在以帳號／工作區／案件 key 隔離組件；同案 server 歸屬或決策紀錄變更時，dirty 草稿顯示衝突並禁止提交，須明確捨棄才載入最新歸屬。
- P2：Input 中文內容按 UTF-8 JSON 位元組先檢查 50KB，避免字元數合法但伺服器拒絕。首次送出收到 422（明確未受理驗證）恢復內容編輯並換新 request_id；409／網路未知及未知後的重試不解鎖，不失去原請求識別。
- 最新 build：`index-ieKSvLZ6.js`、`index-Bj1srCLy.css`。已再次 freeze。
- 新增 `ui_assignment_draft_20260929.js` 7 項 fixture 檢查全通；重跑 Input/native 9 項全通。獨立 reviewer 另行複驗。沒有遠端寫入。
