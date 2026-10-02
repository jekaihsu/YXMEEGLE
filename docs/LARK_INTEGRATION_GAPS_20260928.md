# Lark 審批與 Drive 真實串接缺項（2026-09-28）

本次為獨立唯讀盤點，使用工作台專用應用 `cli_aa3cab98b2789e17` 的 application 身分。沒有使用另一個 CLI 應用代替；沒有發訊息、提單、上傳或修改 Lark。已讀取 lark-shared、lark-approval、lark-drive 技能與既有官方審批 API 規格。

## 已有證據

- 2026-09-28 18:45（Asia/Taipei），專用應用 GET 既有請假審批定義成功：HTTP 200、API code 0、ACTIVE。
- 這只證明既有定義可讀，**不證明專用財務／設計變更／展延／跳過定義已存在或可發起**。
- 私有安全紀錄：`.runtime/lark-integration-readonly-20260928.json`；不含憑證、token、員工名單或表單內容。
- 保存的雲端設定快照 `.runtime/release-current-env-response.json` 沒有 `LARK_NATIVE_APPROVAL_MAPPINGS_JSON`、`LARK_DRIVE_ROOT`、`LARK_TEST_DRIVE_ROOT`、`LARK_TEST_BASE_TOKEN`。這是**保存快照**，不代表主代理更新後的即時雲端狀態。
- 本機 `backend/workspace.db` 沒有可盤點的正式工作區 Drive 設定；未找到已核定 root 候選，故未向任意資料夾發出探測，也沒有以空 token 根目錄當作公司的正式儲存目錄。

## 最小設定清單

| 項目 | 必要內容／存放位置 | 目前證據及下一步 |
| --- | --- | --- |
| 應用身分 | 伺服器 `LARK_APP_ID`、`LARK_APP_SECRET`、`LARK_ALLOWED_TENANTS`、`LARK_WORKER_IDENTITY=application`、`LARK_WORKER_ORGANIZATION` | 專用 app 可取得 token 並讀既有定義；主代理需核對新雲端 worker 設定 |
| 專用審批設定 | `LARK_NATIVE_APPROVAL_MAPPINGS_JSON`，各類含真實 approval_code、欄位 id/name/type、節點 id/seats | 保存快照不存在；须先在审批管理后台建立并启用，再 GET 真實 ID 核對，不可猜造 |
| 審批權限 | 定義／結果唯讀 `approval:approval:readonly`；發起原生實例需要 `approval:instance`（官方所列可選權限中較窄者） | 定義讀取已成功；發起權限未以提單驗收，本次不提單 |
| 正式 Drive 目的 | **工作區** `settings.drive_root`，不是只設環境變數 | 未找到根目錄；需指定公司管理的目錄並授予專用 app 存取 |
| 正式外部檔案開關 | 工作區 `settings.external_enabled=true`，正式 wid 必須等於 `lark-` + worker organization | `remote_policy.py` 實際使用此處；僅開 scope 不會自動啟用 |
| Drive API 能力 | 能列取指定目錄、建立子目錄、上傳普通檔案、下載讀回 | 實作呼叫 list/create_folder/upload_all/download；由主代理依開發者後台核定並發布，另需資源層級目錄授權 |
| 隔離 Drive 驗收 | `LARK_TEST_DRIVE_ROOT` 與測試工作區 `settings.test_drive_root` 必須相同且不同於正式 root；`test_connection_mode=isolated_live` | 保存快照不存在；應先使用隔離目錄取得實際上傳／讀回雜湊證據 |
| 實際角色 | 同專用 app 的在職人員 open_id；案件 PM、行政、節點負責人／主管 | 兩席不可為同一人，不得以名称或不同 app 的 open_id 代替 |

## 審批表單契約

目前 verifier 接受的最小表單為 `binding` 與 `content` 兩個 logical fields，實際型別須為 `input` 或 `textarea`，欄位名稱／ID 與 GET 完全相符。若表單新增其他欄位，必須一併有映射與值，不能靠 UI 看到表單就認定準備完成。

核准節點必須 `node_type=AND`、`need_approver=true`，多席同節點時須 `approver_chosen_multi=true`；各席不同人。

| 類別 | 現行程式要求 |
| --- | --- |
| financial | PM + 行政，證明文件先獲本地確認；本地檔案必須已核實存入 Lark；不能由此改帳務金額 |
| node_skip | PM + 該組主管，共同核准 |
| change | PM + 該組主管（2026-09-28 使用者最新核定，已修正 exact seats）；主管線與業主佐證另行確認 |
| extension | 使用已核定流程的節點 seats；程式未硬編核准組合，不能臨時自選代替決策 |

初次盤點發現的設計變更限制已修正：不再要求 `client_approver_id` 是在職員工。外部業主採本版本佐證，PM＋該組主管完成 Lark 內審，主管本人確認另保留，不得互相代替。

審批管理後台建立定義優先於 API。既有官方文件記錄 API 建立定義不可經後台或 API 停用／刪除；本次沒有建立不可逆測試定義。

## Drive 行為與尚需完成的工作

- 現行 `POST /api/files/{id}/store-lark` 才排入 file job。一般上傳不等於已存入 Lark；如要達到少點擊、自動填寫需求，需在已核定目的與權限具備後接入自動排程，不能只完成 UI。
- Worker 的資料夾路徑目前為「案件 → 節點 → Input／Output／佐證」。上傳分類是檔案 metadata／UI 過濾，不會自動成為 Drive 的分類資料夾。
- 遠端單檔上限由 adapter 固定為 20 MB；上傳後下載計算 SHA-256 一致才標記 verified。
- 正式 `LARK_DRIVE_ROOT` **未被 `connection_policy` 當作目的來源**；它目前只參與測試目錄不可指向正式 root 的防護。需設定正式工作區 `settings.drive_root`。
- 原生審批目前只有正式工作區可發起；demo／test 不能當作真實專用審批端對端驗收。首次實際提單會通知真的指定核准人，須用已核定內容與人員，不能把無害讀取稱作已成功送審。

## 與既定要求的其他落差

`remote_policy.py` 正式 Input 目的仍為 `settings.v4_base`，不是已核定的專用 Input 登錄表。即使其他串接完成，也不應啟用任意 V4 寫回；主代理需先補齊目的模型／白名單與實際登錄表。薪資能力 Base 的硬性寫入阻擋持續有效。

本次沒有更改程式、重建前端、改雲端設定或操作共用瀏覽器。

## Drive 最小權限品牌核實補充

直接下載 **Lark** 官方文件後確認：

| 呼叫 | Lark 官方列出的可選 scope |
| --- | --- |
| POST `/drive/v1/files/create_folder` | `drive:drive` |
| GET `/drive/v1/files` | `drive:drive` 或 `drive:drive:readonly` |

既有 `drive:file` 不能覆蓋目前 worker 自動建子目錄／列取重用目錄的完整流程。就 Lark 現有官方證據，保留既有上下載 scope，另需 `drive:drive`；不需再重複加 readonly。

CLI schema 的 Feishu 文件曾列更細 `space:folder:create`／`space:document:retrieve`，但 Lark 品牌原文沒有列出，不應未核實就認定可用或以此取代 Lark 權限。

官方來源：[新建資料夾](https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/reference/drive-v1/file/create_folder.md)、[列取資料夾](https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/reference/drive-v1/file/list.md)。保存於 `.runtime/drive-official-create_folder.md`、`.runtime/drive-official-list.md`。API scope 不取代 root 的資源存取權。

四種審批的 UI 控件／流程／映射設定另見 [LARK_APPROVAL_UI_SETUP_20260928.md](LARK_APPROVAL_UI_SETUP_20260928.md)。

## 後續程式修正（本地已完成，須另部署）

- 設計變更 Lark 席次依使用者最新決策固定 PM＋該組主管共同核准，不再要求外部業主是公司員工；未設 mapping 繼續阻擋送審。definition、context 均拒絕缺、多、重複或替換席次，同一人不能兼兩席；不提供代票。
- Lark APPROVED 不再直接把設計變更標 approved。新增 `POST /api/change-approvals/{request_id}/confirm-line`，body 為 `version`、`party=supervisor|client`、`reason`、業主線 `evidence_ids`。指定主管須本人確認；案件 PM／指定主管可登錄已確認的業主佐證，事件明確記為「登錄佐證」，不是冒充業主投票。
- 兩線各保存當時 scope、操作者、時間；業主佐證再綁定已 accepted 證据及附件版本 hash。撤下、改版、責任人異動、在職資格失效都不能沿用確認；正式執行變更再次檢查三線。
- API 查回及背景 poller 都使用相同三線 gate。修正執行時從已保存申請取 node_id，避免瀏覽器只送 approval_id 時誤用空節點導致回執失效。
- 正式 Input 改用工作區 `settings.input_base`、`settings.input_table`，且必須等於伺服器 `LARK_INPUT_BASE_TOKEN`、`LARK_INPUT_TABLE_ID`。已核定 V4、報價、薪資三個來源 Base 永不得作為登錄目的，沒有設定不再退回 V4。
- Input mapping 建立、verify、worker 寫前檢查均限制核定 table；測試 Base 也不得指向正式 Input 登錄 Base。

驗證：新增三線／Input 防護 **13 項通過**；既有 native／worker／operations／隔離連線／能力停用 **221 項通過**。全部為本地測試，沒有發出真實審批或寫入 Lark。

## 審批定義配置缺項已解除（23:07 台北）

四張 UI 建立的 node_skip／financial／extension／change 定義已以專用 app 實際 GET 核實 ACTIVE，欄位與節點映射全部通過 verifier。merged 配置為 `.runtime/native-approval-mappings-20260928.json`；驗證 receipt 為 `.runtime/native-definitions-verified-20260928.json`。對 UI hash 型起終節點新增明確 ID 與 shape 驗證，未知／固定核准節點不得被忽略；68 項 native／三線測試通過。待主代理部署此設定與新版程式，尚不能稱為已完成真實提單及核准端到端驗收。

### Drive 送存防重複狀態修正

`POST /api/files/{id}/store-lark` 現拒絕已有非空 `remote_status` 或既有 `jobs.key=file:{id}` 的再送請求，回 409 導向背景工作核對，避免既有失敗／未知結果被假改為 queued。原 worker 重試流程不變。真實 HTTP endpoint regression **9 項通過**：首次排隊、重複、failed／outcome_unknown／blocked／running／verified／simulated、只有狀態或只有原工作；拒絕後版本、檔案與原工作／回執不變。
