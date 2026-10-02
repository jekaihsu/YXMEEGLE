# Input 隔離验收準備與新版公開驗收

2026-09-29；未執行遠端 Input 登錄。本文件不能作為正式 Input 已串通的證明。

## 已核實的部署

對部署 `6abb6d99498d5ec175a08d0d` 在 08:17 UTC 進行獨立 HTTP GET 驗收，12 項通過：PostgreSQL 健康、首頁與 assets、匿名 demo、案件與日報／稽核讀取、來源登入保護、管理健康權限拒絕。JS `index-DT7FQyzT.js` 與 CSS `index-Bj1srCLy.css` 均與本地 dist 雜湊相同。私人回執保存在 `.runtime/release-observation-20260929/`。

這些檢查沒有使用公司的登入 cookie，沒有驗收 OAuth、人員名冊、Input、Drive 或審批的真實寫入。

## 供 root 正常登入後執行的準備

生成器 `scripts/prepare_isolated_input_browser.py` 只讀私人正式／測試 Input 設定與已核定管理員 subject，產生 `.runtime/isolated-input-acceptance-browser-step.js`。生成器不發請求；生成內容已通過 `node --check`。私檔預設 `EXECUTE=false`，本輪沒有改成 true 或執行瀏覽器腳本。

前置條件：新版測試環境變數已套用、使用精確核定的公司管理員正常 Lark 登入（`access_mode=normal`，不能是 recovery），使用獨立瀏覽器登入 session。工作區切換會變更同一 session 的其他視窗，勿在正在操作正式案件的共用 session 執行。

腳本使用現有 UI 同一套已驗證 session API，不是 DOM 點擊測試。必要正常 UI 步驟為：切換測試工作區 → 管理設定填專用測試 Base／Input table／Drive root，模式選 isolated_live → 使用已複製試行案件的 PM 節點 → 作業資料 Input 填資料名稱與內容 → 查看背景工作與讀回回執。內容會清楚標記「隔離驗收」，不作為實際成果。

## 精確 API 流程

1. GET `/api/session`，檢查身分、normal、manager；GET `/api/workspace`。
2. 必要時 POST `/api/workspace/switch`，body `{"environment":"test"}`；必須讀回 `environment=test` 且 namespace 以 `test-lark-` 開頭。
3. 檢查既有 queued/retry/running/outcome_unknown 工作；除了本次已固定 Input 以外有任何工作即停止，避免一起外送。
4. 必要時 POST `/api/actions`：`{action:"admin_settings",version,request_id,payload:{test_base,test_input_table,test_drive_root,test_connection_mode:"isolated_live",external_enabled:true}}`。所有目的 ID 從私人已讀回的隔離配置取得，與正式 base/table 不同；GET 再核對。
5. 選現有 `pilot=true` 測試案件；沒有時可從正式既有來源鏡像 POST `/api/pilot/copy` `{project_id}`，只複製到測試 namespace，不修改正式案件或來源 Base。
6. POST `/api/projects/{project_id}/nodes/{node_id}/inputs`：`{version,request_id,key:"work_input",label,value}`。request_id、案件、節點和內容先存 localStorage checkpoint；重新執行不產生另一筆識別。
7. 對首次排入的登錄最多呼叫一次 POST `/api/admin/worker/run` `{}`，接著 GET workspace 查回。排入 queued 不算成功。
8. 只有 `status=succeeded` 且 receipt `verified=true`、`simulated=false`、`remote_mode=isolated_live`、`base_token` 等於專用測試 Base 才回報 verified。

不確定結果不盲重送。既有 request_id 會先查回本地登錄；未知且無本地證據時停止。遠端 `outcome_unknown` 只允 POST `/api/input-revisions/{id}/reconcile` `{version}` 查回；準備腳本不自動執行 reconcile。worker 已嘗試但未完成時停止並人工檢視，不循環重送。

腳本結束保留測試工作區。root 需保存實際回執與異常，再正常切回正式。若錯過版本、缺 schema、角色不足或工作阻擋，屬未通過，不能把準備成功當作串接成功。

若瀏覽器 current tab 是另一個應用，使用另備的 `.runtime/isolated-input-acceptance-workbench-tab.js`，由 `scripts/prepare_input_workbench_tab.py` 生成。root 已核實兩個工作台 tab 皆由自己建立且共用登入 cookie，因此此版本從既有 browser context 挑 exact origin 的第一個工作台 tab，沒有導航、切換焦點或操作另一 app tab；候選為零時停止。保留原版腳本及相同 localStorage checkpoint，預設仍不執行。已有測試 session 可沿用既有 pilot；沒有 pilot 且沒有正式來源選擇時停止，不自動建立正式案件。

## 修正版公開驗收

08:48:16 UTC 再驗修正版 `6abb7a9cb57ea4921d62c57b`，12/12 通過，健康、demo 案件／日報／稽核 API 實際回應正常，DT7 JS／Bj1 CSS 位元與本地相同。這是實際 GET 結果，不是把 RUNNING 狀態當通過；仍不代表公司登入或外部串接寫入驗收。

## 測試補正

新 worker 對所有真實外送核對名冊後，三個舊 Input 測試的 fixture 被正確擋下。本輪只將 `test_input_registration_worker.py`、`test_input_destination.py` 的 actor 改為同 app 且 fresh 的正式 PersonRow，沒有放鬆 gate；兩檔 11 項通過，完整 suite 由獨立 agent 重跑。
