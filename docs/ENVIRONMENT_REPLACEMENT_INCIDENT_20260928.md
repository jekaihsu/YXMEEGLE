# Zeabur 環境設定覆蓋事件（2026-09-28）

本次準備 application worker 與九表來源設定時，`prepare_release_settings.py` 只產出三項差異。主協調者實測確認 `updateEnvironmentVariable` 是完整替換而非合併：執行後現有環境缺少 14 項設定，新部署出現 `Production requires PostgreSQL DATABASE_URL`。因此不能將 GraphQL mutation 成功當作服務設定完整或服務可用。

主協調者已使用私密保存的完整原始 16 項設定，加上本次三項差異（其中一項為既有來源清單），產出合計 18 項的完整復原請求並收到套用成功回應。

確認時序（由主協調者線上驗收回報，未補造分鐘時間）：

1. 三項 delta 套用成功，但完整環境少了 14 項；服務啟動報 PostgreSQL 設定缺失。
2. 原始完整設定加差異復原，讀回 18 項，必要設定 `required_restored=true`。
3. 服務重啟成功；部署 `6aba548ecf055b5b045624e1` 恢復 `RUNNING`。
4. 線上 JS `BCoPSSh5` 與 CSS `bMhteLtr` 的 bytes 和預期一致。
5. Demo 10 項檢查全部通過：7 案件、7 使用者、7 附件分類，案件／日報／audit API 均為 HTTP 200。

以上證實 demo 服務恢復；不表示真實 Lark 登入及外部整合驗收全部完成。

永久修正：

- `prepare_release_settings.py` 現在先驗證完整來源快照，再保留所有原設定並合併差異，拒絕缺項、空值、重複 key 的快照。
- `release_env_guard.py` 驗證此工作台必要設定、PostgreSQL、session secret 長度及 demo 開關；錯誤不回傳值。
- `zeabur_api.py` 在讀取本機帳號憑證及發送網路請求前執行防護。工作台環境 mutation 僅接受可檢查的完整 map；其他未核定服務的環境替換拒絕，普通查詢不受影響。
- 回歸測試覆蓋三項 delta 拒絕、每項必要設定缺漏／空白拒絕、完整 map 接受、原本自訂設定保留、不輸出秘密、快照不完整時不覆寫已準備請求。

復原資料與完整環境請求保留於忽略版控的 `.runtime`；本文件不保存憑證、連線字串或正式人員資料。後續所有環境更新必須完整讀取並保留未知設定，發布後另檢查執行中版本和服務健康。

防護回歸：`python -B -m pytest backend/test_release_env_guard.py -q` → **16 passed in 0.07s**。未由此子代理再次執行任何遠端設定 mutation。
