# 2026-09-29 雲端展示驗收

驗收時間：2026-09-29 14:24:53（Asia/Taipei）。

- URL： https://yongxiang-projects-20260925.zeabur.app
- Root 已確認 RUNNING 的部署：`6abb58fbb57ea4921d62bd90`，stage `1520832c`。
- 執行：`python .runtime/demo_acceptance_20260929.py --deployment 6abb58fbb57ea4921d62bd90`
- 安全回執：`.runtime/release-observation-20260929/20260929T062456124028Z.json`。
- 結果：12 項全部通過，可使用此版本進行匿名展示。

## 本次確認

1. `/health` 回報 `ok`、資料庫 PostgreSQL。
2. 頁面資源為 `index-ieKSvLZ6.js` / `index-Bj1srCLy.css`，名稱及完整 bytes 均與本機凍結 dist 相符。
3. 五個主要頁面標籤存在。
4. 匿名 session 為 demo；workspace 為 demo namespace。
5. 7 筆案件均為 demo 來源，7 位展示人員，7 個文件分類。
6. 展示 session/workspace 不包含公司 open_id 或已檢查的私密身分／憑證欄位。
7. 案件清單、全域日報、單案日報、單案日誌 GET 均回 200 且具 items 清單。
8. 匿名來源介面要求登入且不回傳正式來源記錄；管理 runtime health 回 403。

上列文字合併了相關檢查，12 個布林結果以 JSON 回執為準。未保存 cookie、正式公司資料或憑證。

## 界線與後續

此輪是 HTTP／資源與匿名資料隔離驗收；瀏覽器互動修正的獨立本機驗收另見 `docs/APPLE_DESIGN_FINAL_REVIEW_20260929.md`。不把 API 200 等同完整業務流程成功，也不把匿名展示當成正式登入、Lark 訊息、原生審批、Drive 或 Input 的正式端到端驗收。

首次受限環境連線出現 ConnectError，經工具授權後重新執行全部通過。失敗回執保留，不判定為產品錯誤。

Root 預告 Attendance 分批修正會再發布後端；本回執只適用上述 deployment。最後設定穩定版仍需重跑。24 小時持續觀察尚未開始、未宣稱完成，計畫見 `docs/RELEASE_OBSERVATION_PLAN_20260929.md`。
