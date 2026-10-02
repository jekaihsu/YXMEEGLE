# 隔離 Input 登錄契約與目的地

原本 isolated_live 僅核定 Base，沒有 table_id，且共用正式欄位設定；新 append-only 入口因此無法安全使用。現已完成：

- 新環境變數 LARK_TEST_INPUT_TABLE_ID、LARK_TEST_INPUT_REGISTRATION_FIELDS_JSON；正常工作台設定 test_input_table，預設空值並提供管理頁欄位。
- 測試 policy 同時核對 Base 與資料表，拒正式來源、正式 Input Base 或正式表；正式 policy 亦拒混用測試 Base／表。
- registration_fields 依 production／isolated_live 選 schema；缺少測試 schema 不退回正式 schema，正式與測試欄位 ID 不得重疊。
- 提交 API、未知結果唯讀查回與 worker 每次授權重新檢查皆用同一 helper，設定異動後既有排程會阻擋。
- 測試工作區只有 isolated_live 才顯示新登錄表单；simulation 不呈現真實登錄入口。

## 驗證

新增 12 項後端測試，包括 API→持久化計畫→worker 假遠端新增與完整讀回、正式 Base/表/欄位跨界拒絕、缺少測試設定拒絕、排隊後 schema 改變阻擋、未知結果僅 GET 核實、正常管理設定白名單。

完整 backend：842 passed（110.42 秒）。前端 TypeScript/Vite build 通過：index-DT7FQyzT.js、index-Bj1srCLy.css。本機 browser fixture 三項通過：隔離入口、模擬隱藏入口、管理表識別欄位。前端再次 freeze。上述 fixture 不是遠端資料新增驗收。

## 真實隔離 Base

正式唯一目的地成功後，另以原版 CLI 建立「詠翔專案工作台作業資料登錄（隔離測試）」。獨立 test-create-checkpoint 防重複建立；讀回唯一表、九個文字欄、零紀錄。Base、資料表、field IDs 均與正式目的地分離。沒有寫測試紀錄，沒有碰來源 Base。

私密配置：`.runtime/lark-input-cli/test-input-config.json`，含三個 LARK_TEST_* 變數與 test_base/test_input_table 工作區設定；回執在同目錄 test-create-receipt、test-tables-readback、test-fields-readback。permission_grant 一樣因無 CLI user skipped，不能聲稱同事已直接獲權。

尚待 root 部署環境設定、正常更新測試工作區設定並以授權測試案件做一次真實 Input→worker→Lark 讀回驗收。此批沒有執行該遠端紀錄測試。
