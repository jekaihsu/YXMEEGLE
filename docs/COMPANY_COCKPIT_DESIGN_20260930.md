# 公司駕駛艙實作筆記

- Visual thesis：沿用詠翔深藍與霧白，以清楚字級、留白和分隔線形成可掃讀的公司作業總覽，不使用卡片拼盤。
- Content plan：頁首標明統計時間與來源新鮮度；主要區呈現案件狀態與交付量；次要區呈現各組工作量；明細提供搜尋、篩選與案件直達連結。所有數值來自公司聚合 API，不推估趨勢。
- Interaction thesis：篩選與刷新保留閱讀位置；列連結用短暫底色變化提示可開啟；資料更新使用低調狀態提示。尊重 reduced-motion、鍵盤與窄螢幕。
- 權限：所有正常公司成員可見，獨立 company 深連結；保留個人首頁。只提供查閱導覽，不授予案件操作權，不呈現薪資、個人請假或財務數字。

## 真實瀏覽器複核

2026-09-30，依指定的 [Apple Design skill](https://github.com/emilkowalski/skills/blob/main/skills/apple-design/SKILL.md) 檢查回饋、層級、克制與 reduced motion。以 Playwright 既有 workbench30 context 新建獨立 tab，僅開 127.0.0.1:8819 與 route-intercept 虛構測試資料；未操作正式頁、正式資料或環境。

- 1440px：document scrollWidth=1440；來源狀態在首區，工作台交付獨立區塊。檢視完整截圖，標籤、數字和來源參考案件清楚。
- 390px：document scrollWidth=390，無頁面溢出；明細表在獨立區域水平捲動。按鈕、輸入及選單沒有低於 44px 的高度。
- 鍵盤：搜尋欄 Tab 到組別選單，focus outline 為 solid，截圖可見焦點。
- reduced motion：統計條 transitionDuration=0s。
- 錯誤與載入：模擬 503，顯示 alert、重試、舊資料保留警示；重試時 aria-busy=true，成功後錯誤消失。未拿此 fixture 證明真實 API 或正式權限。
- 已修：控制項 44px 最低高度、按壓即時底色、交付摘要間距。最終 build 成功：index-C_PoEZ3T.js / index-Cr0Er0yo.css；程式凍結。

截圖（已實際檢視）：output/playwright/cockpit-desktop-1440.png、cockpit-mobile-390.png、cockpit-error-390.png。測試腳本：.runtime/cockpit-review.js。案件路由另以 frontend/test-company-route.mjs 驗證 4 項通過。

## 10/01 真實語意修正

來源總數是案件與報價紀錄，不能將待確認報價計為成案。新增已成案／待確認報價分列，來源分類標為「來源進度與報價關聯」，明示待確認單僅代表尚未關聯確認單；來源已讀取但 mapping_status=review_required 時顯示部分關聯待核對。明細列帶 case_type 標籤。

更新獨立 fixture 後重跑真瀏覽器 1440／390 檢查，無橫向頁面溢出、無小於 44px 控制項；鍵盤、503 舊資料提示、retry loading 與 reduced-motion 仍通過。桌面與手機截圖已重新檢視。最新凍結資產：index-eS3Xac4o.js / index-4X_X65VW.css。
