# 工作台介面實作與驗收（2026-09-28）

本輪是本機實作／驗收，不是正式部署或 Lark 全鏈路驗收。測試使用 `http://127.0.0.1:8793`、獨立 demo namespace；未操作正式 Lark 資料。正式資料、通知送達、原生審批與雲端部署仍須各自回執。

## 已實作

- 案件固定五個頂層：案件概覽、流程與交付、日報紀錄、案件資料、操作紀錄。原報價／母子案／基本資料／人員／附件深連結映射到資料分類，原 operations／approvals 映射到流程。
- 概覽保留單一「報價（筆數）」入口；重大事項審批在流程頂部保留明顯入口，一般成果仍走本地 SOP。
- 原內層八個操作頁籤改成有標籤的工作內容選單；交付表改為卡片，操作區移出任務表格外框。移除 active 底線的負位移，避免額外垂直溢出。手機頁籤完整顯示兩排。
- 案件來源狀態明確標 V4；交付與結案條件另外呈現，來源完成不是工作台結案。財務只讀來源及重大原生審批，沒有直接記帳、核准款項入口。
- 個人可一次確認本人已啟用工作，每項成果說明／版本／伺服器 hash 送交後端原子驗證；代理人不列入本人批次。已依排程啟用與實際開始時間分開。
- 全量日報 API 篩選與分頁，待配對資料可見，日報檢核不等於交付完成。HTTP 404 明確標舊服務範圍，查詢失敗不將舊篩選結果冒充新結果。
- 文件類別、階段、用途分開；同檔版本群組、来源附件只讀索引、管理員類別設定。新增版本自動承接原分類／階段／用途。
- 送審支援先核對、提交、查回原實例；未知結果不建立第二張，最近查回失敗明示待核對。測試區不送正式原生財務審批。
- 草稿以帳號與工作區隔離暫存 24 小時，登出清除；一般表單可明確恢復暫存文字。名冊／視窗焦點刷新保持草稿。舊版本回應不能覆寫新版本。
- 未登入顯示登入頁；失效清除案件畫面；保留登入前案件深連結；名冊未核實錯誤清楚呈現。
- @ 標註使用伺服器 `can_mention`，送出後各別顯示排隊／模擬／受阻／待核實。沒有回執不得顯示送達，失效對象會提示重新選擇。
- 學習入口與深連結維持停用。保留詠翔官網藍色與只有實際節點完成才出現的回饋，遵守 reduced motion。

## 實際瀏覽器證據

`frontend/qa/ui_navigation_20260928.js`：23 項通過。包含五頁、舊深連結、單報價入口、重大流程布局、無直接帳務操作、文件分類／用途／Escape。1440 桌面、900 窄桌面、390 手機與 200% 字級放大沒有頁面水平溢出，也沒有案件頁籤額外垂直捲軸。實看畫面後，另修正手機任務列為卡片，確保 200% 任務標題有足夠寬度且不超出卡片；已量測與檢視 `company-task-200percent-viewport-20260928.png`。200% 測試是 document font-size 200%，不是作業系統顯示縮放；另搭配 390px 重新排版。

- `output/playwright/company-flow-desktop-20260928.png`
- `output/playwright/company-flow-900-20260928.png`
- `output/playwright/company-flow-390-20260928.png`（已實際檢視）
- `output/playwright/company-flow-200percent-20260928.png`
- `output/playwright/company-file-index-20260928.png`

`frontend/qa/ui_auth_20260928.js`：6 項攔截 fixture 通過。未登入不查 workspace、舊案件不殘留、名冊錯誤、深連結、401 清空、舊版本不覆蓋。此項不代表真實 OAuth 已端到端通過。

- `output/playwright/company-login-20260928.png`

`frontend/qa/ui_functional_20260928.js`：17 項真本機功能通過。本人批次完成、焦點刷新與重載草稿、成功訊息、未完成節點不慶祝、文件分類及兩版同組、評論 @ 選單 Escape、評論草稿、送出成功清空及焦點返回、日報／稽核端點、待配對入口。第一輪發現 `file_link` 忽略 file_key，後端修復並重啟後已實際重測通過。立即 render 斷言已改成等待回應及畫面穩定。

`frontend/qa/ui_cas_20260928.js`：5 項真本機 API 通過。每案版本存在、第一案成功、別案修改後允許舊工作區版本、同案舊版本 409、被拒留言未寫入。前端 action／upload 已傳對應案版本；全域操作仍由全域版本保護。

`frontend/qa/ui_source_readiness_20260928.js`：8 項明確攔截 fixture 通過。V4「已結案」與工作台缺財務條件並列、單一報價入口、報價多確認關係、未有對應舊 review 身分不提供錯誤核對操作、合約工項金額只呈現一次、跨組任務深連結、手機無溢出。

`frontend/qa/ui_financial_guard_20260928.js`：6 項明確攔截 fixture 通過。已核實財務核准提供 `financial_finalize` 入口、帶正確案／節點且不含金額、查回失敗停用完成並說明、日報子 API 的 401 也清除案件畫面。無正式財務或 Lark 寫入。

`frontend/qa/ui_attendance_20260928.js`：7 項攔截 fixture 通過。班表未核實員工識別顯示明確原因、無成功回執不宣稱成功、跨日 ISO 日期及 +1 天、Attendance 不冒充人工來源、正式管理員日期查詢入口、demo 禁止正式同步。此項沒有向真實 Attendance 查詢。

共 72 項斷言通過：45 項本機畫面／API 與 27 項攔截 fixture。fixture 不當作正式 Lark 端到端證據。測試中預期的 401 console 訊息為故障情境注入。

補充截圖：`output/playwright/company-daily-20260928.png`、`output/playwright/company-source-readiness-mobile-20260928.png`。

## Apple Design 檢查方式

使用 [apple-design SKILL.md](https://raw.githubusercontent.com/emilkowalski/skills/main/skills/apple-design/SKILL.md) 的回饋、可預測操作、層級、焦點與減少動態原則。此輪審查者同時實作前端，因此是依 skill 自查；需要另一代理交叉檢查才能称獨立審查，也不是 Apple 認證。沒有以玻璃效果或配色替代業務流程驗收。

## 尚需完成的驗收

- 同檔版本及每案 CAS 已由新後端真本機驗證；來源實體與財務核准畫面使用 fixture 驗證，正式來源／審批仍須真實回執。
- 正式 Lark OAuth／名冊、真原生審批及 @ 訊息回執，須在具備權限設定的正式或授權測試環境驗證。
- 本機 build 與圖像不證明正式雲端部署完成。

獨立交叉審查由 `/root/audit_existing_source` 執行，另外發現並已修正：財務 rejected/withdrawn/invalidated 應優先顯示終態；未覆核佐證不放進財務選單並提供補件入口；手機 200% 任務詳情日期換行；工項只顯可讀名稱或來源待核對。原生財務完成紀錄顯示 Lark 共同核准，不把空本地 votes 顯示成待確認。重驗結論由獨立報告記錄，不以此實作者報告代替。

最新 TypeScript／Vite 建置已通過；最終 bundle 以 `frontend/dist/index.html` 與獨立複審紀錄為準。
