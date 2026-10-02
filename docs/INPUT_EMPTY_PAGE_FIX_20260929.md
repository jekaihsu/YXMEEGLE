# Input 空表分頁修正

真實隔離驗收的首次背景工作在送出記錄前 blocked：`Input 登錄分頁內容不完整`。2026-09-29 使用專用應用對專用測試表執行 records GET，實際成功 data 是 `{"has_more":false,"total":0}`，沒有 items。私人去敏回執：`.runtime/lark-input-cli/test-empty-records-shape.json`；本輪未 POST 業務記錄。

`RegistrationAdapter._pages` 原本只接受 items list，因此拒絕 Lark 的合法空表。現在僅接受「第一頁、items 欄位省略、has_more 嚴格 false、total 嚴格整數 0、沒有 page_token」作空集合。items=null、缺少總數、total 非整數、仍有更多、帶游標、後续分頁省略內容全部仍阻擋。不改未知結果政策：reconcile 查不到記錄仍為 outcome_unknown，不會建立新記錄。

新增 11 項案例涵蓋真實空表形狀、成功一次建立後讀回、查回不存在禁止寫入、九類不完整形狀及後續頁缺失。Input adapter／worker／隔離 route／destination 四檔共 44 項通過。

正常 API 重試私稿 `.runtime/input-blocked-retry-browser-step.js` 已通過語法檢查，預設 EXECUTE=false，沒有執行。必須先部署修正，再由 root 正常管理員 session 核對精確原 blocked job、attempts=1 與原錯誤，使用 job_retry 重排原工作，不再提交 Input，不更換 revision、plan 或 client_token。localStorage checkpoint 防重複執行；未知或不符條件停止。其他待處理測試工作存在時也停止，避免一起外送。

本次只有空表 GET 與本地測試通過，不能宣稱 Input 已成功送達；真實 verified 回執仍待 root 重試驗收。

## 真實驗收已完成

修正已部署於 `6abb7deeb57ea4921d62c688`，09:00:18 UTC 為 RUNNING。中斷後先重新正常 OAuth 登入，確認原工作仍 blocked／attempts=1，才透過正常 job_retry 重排同一工作；沒有再提交新 Input。

原 revision `e54ee2c7a1a34b71933d2b43d9af2207` 與原 job 均 succeeded，receipt verified=true、simulated=false、remote_mode=isolated_live、operation=append_registration，verification_basis=remote_current_row_matches_plan，目的為已核定專用測試 Base。遠端 record_id `reczz28HKWfQTlRX`；同一不可變 plan 的九欄內容讀回相符。

這證明隔離測試的正常提交→背景工作→實際 Lark 追加→讀回已串通；不等同全公司正式流程或所有人員審批驗收完成。正式來源與薪資 Base 未寫入。原 retry checkpoint 保留，禁止再次執行該驗收重試。
