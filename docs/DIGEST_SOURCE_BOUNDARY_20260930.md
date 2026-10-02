# 背景摘要來源隔離驗收

每日摘要排程在工作入列時保存 `source_scope=case_digest_v1` 及精確的 `source_project_ids`。不從通知文字推測來源。

正式外送前及每次 HTTP 邊界均重新載入工作區，逐案確認仍為可見新案且由工作台執行。任何來源案件成為舊案、未知案件或未核定執行歸屬，整張摘要停止外送。舊佇列若沒有來源識別，一律標記 blocked；示範與測試的模擬通知維持原行為。

覆蓋：合法新案成功、legacy 缺少來源、入列後 baseline 隔離、混合新舊案、未知案件、未核定案件、最後 HTTP 前突然隔離。排程測試同時確認來源識別確實寫入佇列。

2026-09-30 本輪驗證：110 passed。涵蓋 `test_digest_source_boundary.py`、`test_worker_reliability.py`、`test_independent_input_worker_review.py`、`test_isolated_live.py`、`test_isolated_input_registration.py`、`test_operations.py`。此結果是本機程式與模擬遠端測試，不表示正式 Lark 外送已啟用或部署已完成。
