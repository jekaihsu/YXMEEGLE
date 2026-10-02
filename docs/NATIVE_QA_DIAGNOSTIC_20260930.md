# QA 查回失敗診斷 — 2026-09-30

目標僅既有 `qa-joint-20260930`，實例 `2D9E52F7-298A-4FE2-A1CF-C9403B5B551E`。未建立第二張、未代核准、未修改本機 journal 或正式業務狀態。

## 真實結果

- 14:14:49 UTC：sandbox 執行，取得應用 token 階段 `ConnectError`，尚未讀到定義或實例。
- 14:14:56 UTC：依外部連線權限規則執行相同唯讀診斷，應用 token、原定義、原實例三步均 HTTP 200／API code 0。
- 原實例仍 `PENDING`；`binding_verified=true`、`approved=false`，兩個人工審批任務均 `PENDING`。

因此本次可重現原因是執行環境的網路存取限制，沒有證據支持重新送件。舊 runner 把 `application_adapter` 在 poll 內層 try 區塊之前的連線失敗統一顯示 `remote_operation_unverified`，本機最後成功回執仍為 version 5／pending；該泛化訊息本身不能區分權限或網路故障。

## 可重用診斷

```powershell
python scripts/native_qa_diagnose.py
```

固定同工作台 app／QA 定義／原 run／既有 instance。SQLite 以 `mode=ro` 開啟，先核對原綁定與 policy hash。唯一 POST 為取得應用 token，其後只 GET 原定義及原 UUID；輸出僅 HTTP 狀態、數字 API code、固定階段、遮罩 transport exception 類型、核對結果與任務狀態筆數。無密鑰、原表單或人員資料輸出。

安全報告保存 `.runtime/native-qa/diagnostic.json`。本機 3 項測試通過，涵蓋 token 失敗階段、既有 pending 實例唯讀、連線錯誤遮罩。正式原生送件開關維持原設定，診斷成功不是共同審批通過；仍須兩位同事本人核准後查回。
