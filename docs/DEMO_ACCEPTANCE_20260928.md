# Zeabur Demo 獨立驗收（2026-09-28）

目標：https://yongxiang-projects-20260925.zeabur.app

目前狀態：**新版已部署，獨立雲端唯讀驗收 10 項全部通過，可供 demo。** 驗收時間為 2026-09-28 18:39（Asia/Taipei）。保留 demo mode；不代表正式 Lark 整合全部通過。

部署編號：`6aba419d30d837437e0b01c9`（由部署主代理提供）；本代理另行 HTTP 檢驗實際服務內容。

## 部署前基準

- 雲端 `/api/health`：`status=ok`、`mode=demo`、`database=postgresql`。
- 部署前雲端資產：`index-C7V2E52H.js`、`index-Mf7O0Dmo.css`。
- 目標本地資產：`index-CJvSUYKp.js`、`index-bMhteLtr.css`。
- 部署前版本不同，尚未核定新版可展示。

## 部署後驗收

執行 `.runtime/demo_acceptance_20260928.py`，安全紀錄寫入 `.runtime/demo-acceptance-20260928.json`。僅使用 GET，不傳送訊息、不發起審批、不修改 Lark 或正式案件。

1. PostgreSQL 健康、首頁與全部資產下載成功。
2. 雲端資產檔名及每個檔案的 SHA-256／位元組與本地 build 相同。
3. 隔離 demo session、工作區、案件、上傳分類存在。
4. 新版 build 包含案件概覽、流程與交付、日報紀錄、案件資料、操作紀錄五個分頁標籤；這項不是瀏覽器互動驗收。
5. 案件列表、全部／單案日報、單案操作紀錄 API 可用，回傳分頁結構。
6. Demo 來源要求登入，不暴露正式來源紀錄。
7. 人員投影不暴露 `attendance_identity`。

### 實際結果

- 10 項檢查全數通過，安全 receipt：`.runtime/demo-acceptance-20260928.json`。
- 健康：`status=ok`、`mode=demo`、`database=postgresql`。
- JS：`index-CJvSUYKp.js`；SHA-256 `4587f728a7eeb7beef4fe2ae113a7cf2f3911cd595c582c73b4af40bcfe190df`。
- CSS：`index-bMhteLtr.css`；SHA-256 `0d787f6ec697873a193a01d6dd5c1fa465a7f2c1a4f7a72d369d54e2b12cefb1`。
- 雲端兩個資產皆與本地 `frontend/dist` 逐位元組相等。
- 新 demo session 有 7 個示範案件、7 個示範人員、7 種上傳分類。
- `/api/projects`、全量及單案 `/api/daily-reports`、單案 `/api/audit` 均 HTTP 200 並回傳合法 items。
- Demo 來源隔離與人員私密欄位檢查通過。未測試向真實同事傳訊或寫入任何 Lark 資料。

## 薪資／能力保護（本地獨立驗證）

`python -m pytest backend/test_learning_disabled.py -q`：**87 passed in 21.39s**。

涵蓋能力與訓練入口停用、既有背景工作阻擋、薪資 Base HTTP 修改在網路前攔截、generic Input 不可繞過、唯讀能力保留、班表及報價管理不受停用影響。未對真實薪資 Base 發送修改請求。

## 範圍界線

Demo 通過不等於正式 Lark OAuth、人員名單、專用審批定義、真實通知、Attendance 與 Drive 全線驗收完成。這些整合須各自有實際證據，不能以示範資料或畫面推定已接通。
