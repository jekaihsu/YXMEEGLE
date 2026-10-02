# 案件切換與来源同步進度（2026-09-29）

依使用者核定：全公司切換；Meegle 舊案留原系統完成，工作台接新案。V4 與報價總表仍可同步參考，來源讀入不等於新案，不匯入 Meegle 舊案業務資料。

已讀 `ISSUES_MASTER_20260929_CLAUDE.md`。本批先處理 Q9 歸屬 gate 與 #80 不變來源仍改案件版本；其他來源／Input 問題另列，不宣稱一次全部完成。

## 已實作

- `backend/case_cutover.py`：正式案件 `execution_system=pending|meegle|workbench`。缺值／未知值一律待確認，只有管理員附原因核定 workbench 後可處理業務。demo／test 明示環境可演練；缺 environment 不自動放行。
- 初始化僅新增歸屬資料與 system event，不刪案件、任務、成果、文件或操作歷史。管理員核定有前後值、原因、時間及歷史。
- V4 正式／待確認案件來源同步後套用初始化；已核定 Meegle 或 workbench 的歸屬不因同步翻回。首次出現的新 record 也維持 pending，不按讀取時間／案號猜測上線新案。
- 多份來源身分合併若存在不同歸屬，合併主案重新標記 pending，保留原決策供核對，避免舊案默默取得 workbench 執行權。
- 来源內容相同時不再重寫 `source_changed_at`；真實來源內容異動才更新時間。測試確認不變快照不推進案件 `concurrency_version`，內容改變才 +1。工作區同步狀態仍會更新，未宣稱全域版本問題全部解決。
- 背景来源同步使用 B Agent 共用 `readonly_sync_actor/readonly_sync_connection`：基於先前明確啟用的公司 application 唯讀授權，不永久綁最後操作人。最後操作人停權不使同步永久斷線；停用連線／錯 app 或公司仍阻擋。正常來源同步不受舊案業務 gate 阻止。

## 整合接口

- `execution_allowed(ws,p)`／`require_execution(ws,p)`：供 API／workflow／worker 入口使用。
- `initialize_execution_system(ws)`：正式舊資料遷移，重複呼叫不重複事件。
- `assign_execution(ws,actor,project_id,target,reason)`：管理員核定。
- `project_execution_view(ws,p)`：`execution_system`、`execution_system_label`、`execution_allowed`、`execution_readonly_reason`。
- 建議公共 action `case_execution_assign`，payload `execution_system,reason`。主代理擁有 app/native/integration/jobs/workflow 掛鉤；前端代理已取得契約。

## 驗證及界線

`test_case_cutover`、`test_source_sync`、`test_source_identity`、`test_source_projection`、`test_source_entities`：**57 項通過**。

含無權限核定、未知狀態、保留成果、來源重匯、來源合併不同歸屬、最後人工操作人停權後背景同步、停用連線阻擋、不變來源案件版本穩定。皆為本地隔離測試；尚非所有業務 API／背景工作掛鉤後的端到端驗收，亦未部署或寫入 Lark。

## 續作

日報人工配對範圍 hash、來源移除、新日報完整日期／工項／人員驗收，以及 Input 已核定專用表實際配置與 unknown 結果核實出口。薪資 Base 不回寫，Meegle 僅讀模板。

## 第二批：隱含案件與 Input 登錄契約

- `resolve_action_projects` 從儲存的 Input、審批、SOP、日報核對、交接、代理、定期工作及 job payload 找實際案件；偽造 body.project_id 不能把其他案件的操作移到允許執行的案件。
- 正式 v3 Base `Sdw1bG1djaHsVGsRPvmjyVWipgg` 加入禁止作為 Input 目的地／隔離測試目的地的固定清單。
- `input_registration.py` 提供獨立登錄契約。修訂對應一筆新登錄，保留提交人、案件、節點、內容及雜湊；不修改已有來源格子。
- 持久化 plan 含 UUIDv4 client_token、工作區＋修訂識別的唯一鍵與完整目的地映射。提交前讀欄位、查既有唯一鍵；已有且全欄相符則只讀回。重複或同鍵不同內容拒絕，絕不覆寫。
- POST 成功仍需讀回全部欄位才 verified；送出結果未知只允許 `reconcile` GET。查不到不當作未送出，不盲目再建立。
- 43 個針對測試通過。這是模組測試，尚未代表正式 UI／worker 已切換或真 Lark E2E 完成；由 root 協調接線及專用表設定。

專用表 9 欄全部為文字 type=1：登錄識別、工作區識別、案件識別、節點識別、修訂識別、提交人識別、提交時間、登錄內容、內容雜湊。`destination.fields` 以語意 key 對應真 field_id 與上述 field_name；Base＋table 仍需 server／workspace 雙白名單。不可把名稱當作已驗證真 ID。

API 契約核對官方 SDK：[建立紀錄與 client_token](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/api/bitable/v1/model/create_app_table_record_request.py)、[唯讀列紀錄與分頁](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/api/bitable/v1/model/list_app_table_record_request.py)。目前查重採完整分頁上限 20,000 筆，超限阻擋；資料增加後應改核實過的精確條件查詢，避免全表查重成本。

## 第三批：實際入口與日報範圍

- `POST /api/projects/{project_id}/nodes/{node_id}/inputs` 接受 `version, request_id(UUID), key, label, value`；先持久化 plan 與同一 request_id 防重，僅排隊，不宣稱成功同步。前端隱藏技術 key、只讓同事填資料名稱及內容；尚無核定語意字典，不冒充已映射來源欄位。
- `POST /api/input-revisions/{id}/reconcile` 僅處理 unknown 工作，逐次 HTTP 重新核對人員、歸屬、base/table/fields 與 revision；GET 相符才變 succeeded。查不到仍 unknown，不再 POST。
- Worker 正式工作只接受 `append_registration`；既有正式 cell patch jobs 阻擋。隔離測試原先明示核定的 cell mapping 測試保留，仍禁止公司來源 Base。模擬工作保留原行為。
- 正式 `input_mapping / input_draft / input_submit` actions 停止使用，改走新登錄入口；舊歷史不刪除。
- 新環境鍵 `LARK_INPUT_REGISTRATION_FIELDS_JSON`：`{"registration_key":{"field_id":"真實ID","field_name":"登錄識別"}, ...}`，完整 key/name 以 `input_registration.FIELD_NAMES` 九欄為準。Worker 每次 HTTP 前檢查它仍等於不可變 plan；Base、table 另外維持雙白名單。
- 日報 `daily_mapping_version` 分離上游身份／關聯範圍：contract/reporting/confirmation 的非關聯備註、行政檢核不使整案人工配對失效。日報本身與成本單仍保留精確內容，以免更改來源日期、人員、內容後沿用未核對決策。交付引用繼續用 `daily_source_version`，不因縮小配對範圍而放過內容變更。
- 舊 review 有保存原 entry 則從原快照衍生 mapping version；沒有 entry 則只在舊完整 source hash 與目前完全一致時遷移。無法核對的舊決策不自動認可。
- Gate resolver 另補 node_skip 儲存歸屬與 task_batch_complete 全批案件。正式財務舊 actions 維持禁止直接操作。

驗證：第一輪相關來源／日報／Input／operations 101 通過；更新日報保守相容後 scope/workflow completion/isolated-live/daily 61 通過；正式 worker append 與未知不重送＋endpoint＋目的地 14 通過。皆為自動化測試，未建立真實 Input 表、未送出真實登錄，正式配置及外部 E2E 仍待完成。
