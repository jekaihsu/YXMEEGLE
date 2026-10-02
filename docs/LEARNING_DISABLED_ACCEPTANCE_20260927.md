# 訓練、能力與考評停用驗收（2026-09-27）

依業主 D1–D3 決策，本輪 `FEATURE_LEARNING=False`。只有管理功能保留；能力地圖涉及薪資，測試不解除其回寫封鎖。

## 已驗證

命令：`python -X utf8 -m pytest backend/test_learning_disabled.py backend/test_learning.py backend/test_learning_remote.py backend/test_isolated_live.py backend/test_worker_reliability.py -q`

結果：**161 passed in 31.09s**。

| 範圍 | 驗證方式與結果 |
| --- | --- |
| 訓練／能力／學習操作 | 七個既有及三個未知前綴 action，直接呼叫與實際 FastAPI TestClient 都回 404；版本、事件、工作佇列、認定紀錄不變 |
| 兩個 API | `/api/learning/sync`、`/api/learning/mappings/verify` 在解析無效 JSON、取得 adapter、讀取能力來源前就回 404 |
| 班表管理保留 | TestClient 保存、第二次修改、版本及歷史都正常；無權限者仍 403 |
| 報價管理保留 | TestClient 驗 PM → pending、指定業務 → approved；直接流程另驗非指定管理者不能代票 |
| 舊工作封鎖 | capability、training_record 六種未完狀態，含業務紀錄不存在，共 24 種；一律 blocked、移除 lease、零 adapter、無模擬成功 receipt，重試 403 |
| 已完歷史保留 | succeeded、canceled、cancelled 不被重送、不改寫原 receipt |
| 能力 Base HTTP 邊界 | create、update、delete、batch 與欄位 mutation，含 URL 編碼 token，全部在 HTTP 前 blocked；GET 與 POST records/search 保留 |
| 間接回寫 | 已驗證 Input mapping 也不能写能力 Base；三種工作區、五種訓練版本／狀態下 export 重試都零 HTTP |
| 舊本地邏輯 | 只有明確指定測試用 fixture 暫開 feature，以檢查保留的歷史訓練規則；成果／認定仍 writeback_paused、零新增 queue，不能解除能力 Base 封鎖 |

首輪一項報價 fixture 誤用空 seed，已改成示範案並重跑全五檔；不是產品問題。未修改正式資料或送出任何遠端 HTTP。

## 驗收界線

上述 API 為隔離 SQLite 的完整 FastAPI TestClient，不等於使用者正在瀏覽的 8792 服務已重啟，也不代表雲端已部署。UI 隱藏、舊 deep link、管理入口由 Apple reviewer 獨立驗證；實際服務與部署版本由 root 整合查核。
