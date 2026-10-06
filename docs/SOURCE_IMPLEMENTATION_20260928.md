# 來源與原生審批實作紀錄（2026-09-28）

本文件記錄本次程式與本機測試，不代表新版已正式部署、已完成真實送審或已通過正式 DB 驗收。

## 來源同步

- `SourceSyncService.sync(wid, actor_id, token=None)` 保留呼叫相容性，但忽略傳入的使用者 token。手動與背景都以核定公司 application 身分讀取，要求 APP_ID、WORKER_IDENTITY=application、WORKER_ORGANIZATION、ALLOWED_TENANTS 相符。
- 每次 HTTP 前及提交前重查操作者／公司／設定。完整九表及完整分頁才套用；缺少明確 items/has_more 不能當空表。同步 generation 與時間防止較舊或較慢快照覆蓋後完成資料，過時失敗也不覆蓋較新的成功狀態。
- 完整快照刪除證據只適用已涵蓋的表。案件、工項及附件缺失標記保留歷史與人工成果，不自動完成／刪案；日報原有 source_missing 歷史機制保留。增量或未涵蓋表不得推定刪除。
- 新增 V4 工項呼叫共用 `inherit_new_task`，繼承有效節點 owner；既有人工作業不覆蓋。SOP key 僅採已核定且唯一的 task_definitions，不聲稱完整 Meegle 範本已驗收。

## 真資料投影與附件

- `p.source_projection`：fields(client/due_date/contract_amount) 各含 value/status/source_urls；finance 為唯讀來源金額及預估／實際成本，verified=false。衝突不任選第一筆，零金額不視為空，不覆蓋人工金額／日期。
- `p.source_work_items` 保存已明確關聯的合約／填報工項；工項 `source_snapshot` 帶實際欄位及來源連結，供交付前確認，不等於交付成果已通過。
- 只在已核定業務 Bases 依實際 type=17 欄位讀附件 metadata。`source_attachment_index`／`p.source_attachments` 含名稱、token、大小、來源欄位及紀錄連結；category_id=other，status=indexed、verified=false，不下載檔案、不保存暫時下載 URL、不冒稱已存公司 Drive。
- 附件刪除僅在本次完整表且同附件欄位仍可見時判定 source_missing，避免欄位權限缺失被當作刪除。CSV 同時輸出來源附件索引並明說尚未下載核實。
- 舊實際快照沒有附件 metadata 欄位，因此重播的零附件不是「來源沒有附件」的驗收證據。

## 全公司日報契約

`source_projection.daily_index(state, *, project_id, department, actor_id, date_from, date_to, mapping_status, include_missing=False, status='all', q='', offset=0, limit=100)`。

`status` 可為 all/matched/unmatched/source_missing；limit 最大 200。回傳 items/total/offset/limit/summary/last_sync。summary 為篩選後 matched/unmatched/source_missing 總數；items 帶 project_id/project_code，排除 raw source_fields/provenance/candidates。API 呼叫前必須完成正式使用者／workspace 授權。

535 筆舊日報是移轉核對資料，與先前新增真日報測試分開記錄，不以 0/535 推論新增日報串接失敗。

## 人員

- 固定 Base VwAsbezz9app3YsramgjduLYp2U、表 tblrXclB7LSknReZ，精確只讀姓名(type1)、人員(type11)、在職(type7)、內外勤(type3)。同名新表、欄位型別漂移不能取代已核定來源。
- 真 checkbox true/false 才是明確在職／離職；缺值保持 unknown。缺／重複帳號保留待核對，失聯名冊保留歷史，不以缺列自行停權。
- 不再自動讀取或採用其他「部門」欄位。工作台部門、組主管、PM 由管理設定，內外勤僅為來源分類提示。
- 正式登入與可指派／標註由共用 admission gate 決定；同步不升權、不恢復管理停用。

## 原生重大審批

僅 financial/change/extension/node_skip；普通成果依原本本地 SOP。

- `NativeApprovalService` 提供 prepare/submit/poll。authorize 必須每次回傳最新 server context；checkpoint 必須先 durable CAS。context 包含 app_id/tenant/workspace_id/project_id/request_id/version/scope_hash。
- 設定 `LARK_NATIVE_APPROVAL_MAPPINGS_JSON` 各類實際 approval_code、fields 與節點 seats，未設定或定義漂移一律阻擋。不可由 token/scope/唯讀成功推論可正式送審。
- `native_routes.register(app, identity, load, persist, sessions, W, cfg)`；POST `/api/native-approvals/{kind}/{request_id}/{prepare|submit|poll}`，body `{project_version}`（所屬案件目前的 concurrency_version，非工作區 version），回 workspace。
- prepare 僅讀定義；首次 submit 在 HTTP POST 前保存 UUID/版本與 outcome_unknown，重試只查同 UUID，不重複 POST。設計變更首次 attempted 同交易 freeze_change；prepared 不暫停任務。
- 實例表單、申請人、UUID、定義、每位指定核准人的 AND task 與 PASS timeline 皆需吻合；同人不得兩票。遠端自動通過、改派／增減核准人及回滾不視為本規則核准。
- route 保存 native_binding/native_receipt；只有真正查回才有 verified_at。fresh apply 要求 5 分鐘內證據。暫時查詢失敗不延長證據，阻擋新套用；既成 waiver 保留先前真核准歷史並標待核對。確定性內容／定義不符及撤回清除核准效力。已 applied 再查回 APPROVED 不降回 approved。
- `native_requests.receipt_valid` 同時驗不可變綁定、目前 scope、同 app 已核實在職 actors 及 server native_approval_authority。app load 應從目前 cfg 注入 authority，不能沿用 DB 舊設定。
- 跳過固定 PM＋該組主管；財務交付固定 PM＋行政，兩位不同人。變更必須有 owner＋client 實際核准席位；未配置業主身分不能猜。
- POST `/api/native-approvals/financial/request`：version/project_id/node_id/evidence_ids/reason/confirmation_kind(contract/payment/settlement)。只建交付確認草稿，金額只讀 source_finance，拒絕 amount/paid 等帳務欄位；送前驗證證明未撤下及本地文件已核實存入公司 Lark。不改餘額、收付款或結清。

### 精確權限

依已保存官方 tenant API 文件：GET definition 使用 approval:approval:readonly；POST /approval/v4/instances 需 approval:instance；GET instance/UUID 可使用 approval:approval:readonly 或 approval:instance。不需 user_id 通訊錄權限，全部用本應用 open_id。定義由管理後台建立，不需增加 definition API 寫入權限。

官方：[建立實例](https://open.larksuite.com/document/server-docs/approval-v4/instance/create)、[查回實例](https://open.larksuite.com/document/server-docs/approval-v4/instance/get)。保存原文位於 `.runtime/approval-official-instance_create.md` 與 `instance_get.md`。

## 證據與仍待驗收

- 本輪來源／人員／原生 service／routes／日報專項 140 passed，另 HTTP 非 JSON／錯誤結構回應 6 項通過。fake HTTP／SQLite memory 均不等於正式送審成功。
- 另一 agent 獨立複跑 native routes／adapter／workflow／批次交付／mentions 合計 100 項通過；交叉發現的 applied 回讀降狀態、財務任務改版、核准人名冊及變更暫停接點已修。財務 receipt scope 包含本節點實質任務／必備資料與證明引用的檔案版本。
- `.runtime/source-implementation-replay-20260928.json`：保存的真九表 2,569 列在新版記憶體重播，15 正式＋266 待確認、6,545 任務；重播案件／任務 ID 穩定，281 案均有來源投影，舊日報 535 筆另列核對。
- 原始真新日報新增／修改／刪除證據仍屬先前測試，不當成新版正式 DB 驗收。
- 新版 cloud、正式 DB 名冊與九表同步、最新附件欄位真讀、Drive 上傳讀回、專用審批定義與實際兩人審批、查回與撤回 E2E 須在部署後獨立驗收。未配置維持明確阻擋。
- 能力／薪資 Base 的所有遠端寫入仍禁止；本次沒有正式審批提單、訊息或遠端業務寫入。

## 第二輪：來源實體與局部失效

- 新增持久化集合 `source_quotes`、`source_confirmations`、`contract_items`；身分固定為 `base/table/record`。來源明確連結形成報價→確認單→案件、合約工項→填報工項→跨組任務關係；不以名稱或近似編號推測。
- 同一合約工項跨組仍只有一筆金額；`task_refs` 僅指向不同工作，不複製金額或推算配點。`allocation_status=unverified`。
- 報價 `project_ids` 聚合明確確認單的所有案件；`review_quote_id` 保留既有工作台報價識別，`review_project_ids` 僅列確實含此報價的案件。normalized ID 不可直接送舊 `quote_review`。
- 各實體有 revision/history；完整覆蓋該表才標 source_missing，增量不判刪。既有 `p.quotes` 同樣標記來源消失，不能沿用舊已收款欄位當作目前收款證據。
- V4 已結案留在 `source_status`，不把本地節點、任務或交付結案狀態改為完成。只讀 `source_completed` 亦不是工作流通過。
- 日報核准 hash 對上游確認單限身分／明確關聯欄位；完整 provenance 仍保存供稽核。僅修改確認單備註不使全案日報失效。日報本身或關聯身分改變仍使相關核對失效；`reconcile_daily_evidence` 只重開引用該改版日報的成果節點。
- 保存真快照新版本機重播 `.runtime/source-entities-replay-20260928.json`：2,569 列，15 正式＋266 待確認、6,545 任務，282 報價／212 確認单／511 合約工項。案件任務 ID、實體 revision/history 重播穩定。舊 535 日報仍獨立待核對；此為本機記憶體證據，不是部署或新版遠端驗收。

## 審批週期查回與財務宣告

- `NativeApprovalPoller(sessions,W,B,P,cfg).run_due(wid)`，只查已 attempted 的既有原生申請，每筆 5 分鐘、單輪最多 10 筆。只 GET、不 POST、不投票、不自行執行業務改動。
- 以目前 server cfg 核對公司及應用，保留原 immutable binding。原申請人停用、業務 scope 已改版時仍可觀察原申請狀態，但不能把原票套用至新範圍；fresh apply 另要求原申請人目前合格。
- 確認撤回／拒絕／定義內容不符會清除核准效力及更新 waiver gates。純網路錯誤不延長 verified_at、不抹除歷史真收據，也不允許新 apply。
- 財務草稿 `payables_declaration` 可為 unknown/no_payables/all_settled；必有理由及原始佐證，宣告納入 scope hash。報價收款來源只能證明 incoming，不能推定下包或其他應付款已結清。

## 正常班表唯讀接線

官方介面已查證：`POST /attendance/v1/user_daily_shifts/query` 是只讀查詢，權限 `attendance:task:readonly`；`GET /attendance/v1/shifts/:shift_id` 權限 `attendance:rule:readonly`。不採打卡紀錄、不加寫入考勤權限。

- 官方文件：[查詢排班](https://open.larksuite.com/document/server-docs/attendance-v1/user_daily_shift/query)、[取得班次](https://open.larksuite.com/document/server-docs/attendance-v1/shift/get)。原文保存 `.runtime/attendance-official-schedule.md`／`attendance-official-shift.md`。
- Attendance API 只收 employee_id/employee_no，不能直接塞 open_id。只接受同應用同公司 OAuth 已驗證 user_info 的 user_id，保存為 `attendance_identity.employee_id`；缺值 pending、不猜姓名、不擴通訊錄查詢。此識別不應公開前端。
- `AttendanceScheduleService(sessions,W,B,P,cfg).sync(wid,actor_id,date_from=None,date_to=None)`；預設今天起 14 天，最多 30 天。正式且已核實 manager/calendar_edit 操作者，HTTP 前／提交前重查權限及身分，generation 防舊結果覆蓋。
- `run_due(wid)` 僅在 `attendance_schedule_connection.enabled` 為真時執行，5 分鐘節流。成功手動同步啟用連線；未配置或無真權限不得假標已連線。
- `work_schedules` 保存 basis=attendance_schedule、status、active、end_time、normal_off_at、off_day_offset、version/history。人工 company_schedule 優先，不能被讀回覆蓋；缺身分／班次／彈性班次保持 pending，舊來源班次以歷史保留。網路失敗保留成功資料與 last_success_at。
- `attendance_schedule_status` 含 status、last_attempt_at、last_success_at、issues、ready_count、manual_override_count、date_from/to、app_id、sync_revision。
- 26:00 解析成隔天 02:00；不擅自把 02:00 猜成隔天。`learning.cutoff` 回傳絕對 `at` 與 off_day_offset，排程／逾期消費端必須採絕對時間，不能只比 due_date。人工 override 忽略殘留舊來源跨日欄位。
- 仍需公司權限與實際 employee_id 的真排班查回驗收；fake adapter 測試不等於 Attendance 已正式串通。

第二輪 source entity／Attendance service與reader／native poller／native route／局部失效／finance 專項 **54 passed**。此前較廣 source/daily/native 組 **72 passed**。兩組有重疊，不相加宣稱總測試數；本輪無遠端業務寫入。
