# 原生共同審批 QA 交接 — 2026-09-30

## 後續進度：固定定義 probe 已準備

Root 回報已透過 UI 發布專用定義：`E1DEFC43-3E29-4238-AD9D-91ACF8E29091`（後台 numeric ID `7691275502535413275`）。本 Agent 尚未對外 GET 驗證，因此以下仍須實際 probe，不把 UI 回報等同 API 驗收。

已新增 `scripts/native_qa_setup.py`，固定工作台 app／此 QA code／名稱，不接受任意遠端目標。`probe` 只取得應用 token 與 GET 該定義，將經白名單縮減的欄位／節點證據保存 `.runtime/native-qa/definition-probe.json`；不存實例資料、管理員名單或密鑰。檢查雙 textarea、真實欄位 ID、單一多人 AND、精確起終節點，以及不屬於任何正式審批 code。

```powershell
python scripts/native_qa_setup.py --saved-config .runtime/login-cutover/company-intended.json probe
python scripts/native_qa_setup.py --saved-config .runtime/login-cutover/company-intended.json people
python scripts/native_qa_setup.py --saved-config .runtime/login-cutover/company-intended.json manifest --participants .runtime/native-qa/participants-verified.json
```

`people` 復用 `backend.people_directory.fetch_directory(adapter, app_id)`，只讀已核定四欄，不呼叫同步 service、不存公司 DB、不取得薪資資料值。私有證據 `.runtime/native-qa/people-probe.json` 僅保留兩位候選必要身分；標準輸出僅候選姓名及筆數。文乃毅 fresh ID 必須符合既有工作台已證 ID，鍾智偉取相同應用讀回的唯一在職帳號；另一應用／ID 不符／重名／非在職均 blocked，不推論跨 app 對應。

`manifest` 命令完全離線；既有 config.json 絕不覆寫。上述三命令本 Agent 均未執行。保存的 participant 證據格式：

```json
{
  "app_id": "cli_aa3cab98b2789e17",
  "tenant": "<本公司 tenant>",
  "verified_at": "<一小時內的實際核實时间，含時區>",
  "evidence_ref": "<root 以本 app fresh 核對的私有證據路徑>",
  "participants": {
    "applicant": "<已核實 jekai 或其他申請人 open_id>",
    "approvers": {"pm": "<同事一 open_id>", "supervisor": "<同事二 open_id>"},
    "allowlist": ["<不重複且恰為上述參與者集合>"]
  },
  "authorization": {
    "decision_ref": "<本對話測試授權依據>",
    "authorized_by": "<授權人>",
    "reason": "獨立 QA，測試席次不修改正式業務角色",
    "expires_at": "<明確到期時間>"
  }
}
```

**身分資料不能直接沿用**：本機 `roster-four-fields-readonly-private.json` 是 user 身分讀取，沒有來源 app_id 證據；其文乃毅 open_id 與舊工作台交接不同。鍾智偉與文乃毅在該舊快照為在職，僅可作候選，不能拿舊 ID 直接送審。該四欄沒有 PM／主管角色；內外勤不能推論業務角色。依使用者不參與日常管理的要求，本輪優先兩位真實同事，各自 fresh 核對工作台 app 身分與測試席次；jekai 最多作 applicant，不當必需核准人。

`manifest` 所需證據由 root 實際查證保存，脚本不會把填入的時間或路徑自行變成通訊錄查證事實。`prepare` 前仍需檢查當日任職及授權。7 項純本機測試通過，涵蓋真實 ID 抽取、名稱／型別／AND／多人／額外節點拒絕、同 app 時效與兩席不同人；無遠端操作。

本次僅讀取 `scripts/native_qa_runner.py`、`backend/native_qa.py`、`backend/native_approval.py`、既有交接及本機瀏覽器步驟檔。未操作瀏覽器、未發布定義、未送件、未代投票。正式 `LARK_NATIVE_APPROVAL_SUBMIT_ENABLED` 維持關閉。

## 現況與可確認範圍

- 本機留有 `.runtime/qa-definition-draft.js`、`qa-definition-fields-finish.js`、`qa-definition-process.js` 及唯讀 `qa-definition-resume.js`。這些是操作程式，不是成功執行或發布回執，不能據此宣稱設定已完成。
- 舊交接記錄指出曾建立專用草稿、兩個 Paragraph 欄位，流程設定仍待完成。恢復時先確認既有草稿／發布狀態，避免再次建立同名定義。
- 本次檔案搜尋未找到可直接使用的 `.runtime/native-qa/config.json` 或 QA attempts.sqlite。尚無這輪真實雙人 PASS 回執。
- Runner 與正式工作區 DB 隔離；即使測試核准成功，永遠回報 `business_apply_allowed=false`。

## 專用定義的確切規格

| 項目 | 設定／核對要求 |
| --- | --- |
| 名稱 | `詠翔工作台－串接驗收測試`，含全形 `－`；GET 回傳名稱須完全相同 |
| 說明 | 僅供工作台串接驗收，不對應正式案件、不改工程進度、不產生財務或薪資效力；請本人核准測試單 |
| 欄位 1 | 名稱 `驗收識別`，Paragraph／API `textarea`，runner logical key `binding` |
| 欄位 2 | 名稱 `驗收測試內容`，Paragraph／API `textarea`，runner logical key `content` |
| 其他欄位 | 不新增；`verify_definition` 要求兩個實際欄位與 mapping 精確相等 |
| 審批節點 | 一個人工審批節點；由發起人指定審批人，允許多人；**Everyone assigned (all approvers need to agree)** |
| 自己為審批人 | **Requester reviews the request**；不得自己提出就自動通過 |
| 自動規則 | 不啟用自動通過、重複核准人免審、缺少核准人自動通過。避免額外抄送／分支／固定人審批節點 |
| 範圍 | 限核定的測試參與者，並使專案工作台專用應用可讀取及建立此 QA 定義的實例 |
| 發布 | GET 必須 `status=ACTIVE`；草稿不算可用 |

不猜欄位 ID 或節點 ID。Paragraph 曾無可見 Custom ID，`workbench_binding`／`workbench_content` 只是早期腳本意圖，不能拿來當實際 ID。發布後用定義 GET 取得真正 `form[].id`、`node_list[].node_id`。若起終節點為雜湊 ID，填 `boundary_nodes.start/end`，名稱分別精確為 `Submit`／`End`。

審批節點 API 須有 `node_type=AND`、`need_approver=true`、`approver_chosen_multi=true`。後台自動規則仍需人工核對，不能只因上述三欄吻合就認定不會自動跳過。

## 真正驗證「共同」核准

舊 `NATIVE_QA_RUNNER_20260929.md` 範例是 `kind=extension`、單一 supervisor；它只能驗證單人傳輸，**不能用來宣稱雙人共同審批通過**。

本輪採 `kind=node_skip`，`mapping.nodes[0].seats=["pm","supervisor"]`。兩席必須是不同 `open_id`。這些是 QA 席次，不會改公司正式案件角色。發起人可與其中一位相同，但仍須該帳號本人實際 PASS，不得自動通過。

既有交接選定的候選測試同事為文乃毅，另有已驗證 jekai 帳號；若採兩者測試，僅限此次 QA，不把 jekai 設成日常審批必經人。實際 open_id、公司 tenant 及參與者目前資格須由 root 以工作台專用 app 核對後寫入 `.runtime` manifest；不要猜姓名或借用其他應用的 open_id。

`participants.allowlist` 須恰好等於 applicant 與兩位 approver 的不重複集合。`authorization` 四項必填：本對話已授權依據 `decision_ref`、授權人、測試原因、具時區且涵蓋預定人工核准時間的 `expires_at`。不擅自延長既有 run 的授權或更換參與者。

## Manifest 與命令

以下是準備格式，所有尖括號均待查證填入；目前不是可直接送件的設定。

```json
{
  "schema_version": 1,
  "purpose": "native_qa_transport_only",
  "app_id": "cli_aa3cab98b2789e17",
  "tenant": "<已核實公司 tenant>",
  "definition_name": "詠翔工作台－串接驗收測試",
  "mapping": {
    "kind": "node_skip",
    "approval_code": "<獨立 QA 定義 code，不能是任何正式 code>",
    "fields": {
      "binding": {"id": "<GET 實際 ID>", "name": "驗收識別", "type": "textarea"},
      "content": {"id": "<GET 實際 ID>", "name": "驗收測試內容", "type": "textarea"}
    },
    "nodes": [{"id": "<GET 實際人工節點 ID>", "seats": ["pm", "supervisor"]}],
    "boundary_nodes": {
      "start": {"id": "<GET Submit ID>", "name": "Submit"},
      "end": {"id": "<GET End ID>", "name": "End"}
    }
  },
  "participants": {
    "applicant": "<ou_...>",
    "approvers": {"pm": "<ou_第一位>", "supervisor": "<ou_第二位>"},
    "allowlist": ["<不重複、核定的參與者 IDs>"]
  },
  "authorization": {
    "decision_ref": "<既有明確測試授權依據>",
    "authorized_by": "<授權人>",
    "reason": "獨立 QA 傳輸及雙人本人共同審批驗收，不改正式業務角色",
    "expires_at": "<含時區 ISO 到期時間>"
  }
}
```

將非密鑰 manifest 保存 `.runtime/native-qa/config.json`。另外的 `.runtime/native-qa/server-config.json` 是 root 安全準備的工作台應用設定，至少含 ID/secret、application worker 身分、公司 tenant／白名單及完整四類正式審批 mapping inventory；不要混用新備份 app。環境 `LARK_*` 會覆蓋 saved-config，執行前核對來源，勿輸出密鑰。

```powershell
python scripts/native_qa_runner.py --config .runtime/native-qa/config.json --saved-config .runtime/native-qa/server-config.json doctor
python scripts/native_qa_runner.py --config .runtime/native-qa/config.json --saved-config .runtime/native-qa/server-config.json prepare --run-id qa-joint-20260930
python scripts/native_qa_runner.py --config .runtime/native-qa/config.json --saved-config .runtime/native-qa/server-config.json status --run-id qa-joint-20260930
```

doctor 不連網；prepare 僅 GET 定義並保存固定 UUID。root 核實專用定義及參與者後，才在已有授權範圍內執行真實測試：

```powershell
python scripts/native_qa_runner.py --config .runtime/native-qa/config.json --saved-config .runtime/native-qa/server-config.json create --run-id qa-joint-20260930 --allow-create
python scripts/native_qa_runner.py --config .runtime/native-qa/config.json --saved-config .runtime/native-qa/server-config.json poll --run-id qa-joint-20260930
```

以上命令本輪均未執行。run ID 若已存在，先 status，不換 ID 規避未知結果。第一次 create 前持久化 attempted；之後 create 只查原 UUID，連確定拒絕都不會自動重送。這是 QA runner 的保守限制，與正式 native service 的拒建恢復入口不同。若遇到 definition／policy drift 或授權逾期，保留原 journal，先核對，不直接編 manifest 或刪資料庫。

## 驗收紀錄與上線依賴

1. 保存發布後定義 GET 與後台人工流程設定證據；GET 名稱、欄位、節點精確相符。
2. create 回執保存 UUID／instance_code；先觀察 PENDING。
3. 第一位本人核准後仍不得判定兩人共同通過；第二位本人核准後 poll。
4. 結果必須 `approved=true`、`binding_verified=true`、外部 APPROVED，且 task_list 的兩席不同人、各有相同 task ID／open_id 的本人 PASS。AUTO_PASS／REMOVE_REPEAT 等不算通過。
5. `business_apply_allowed=false` 始終成立；QA 成功不代表正式案件套用、財務或四種業務審批全線驗收完畢。

已與 worker_boundary_resume 同步：本 QA 用本機獨立 SQLite，不需要 PostgreSQL，也不等待備份 app 發布；共同上線仍缺独立備份應用權限、真實加密 Drive roundtrip、**與正式及既有 staging app 分離的空 PostgreSQL** 還原驗收，以及正式站真實同事登入／業務權限驗收。不能借用已有 app tables 的 staging DB 充當空還原目標。


## Verified poll recovery (2026-09-30 UTC)

The sandbox diagnostic failed at token acquisition with ConnectError at 14:14:49 UTC. The same fixed read-only diagnostic with approved escalation succeeded at 14:14:56 UTC: token, definition and original instance returned HTTP 200 / API code 0. See NATIVE_QA_DIAGNOSTIC_20260930.md.

The existing runner poll was then executed with escalation for qa-joint-20260930, using the frozen manifest and company-intended private configuration. Durable version is 6; instance 2D9E52F7-298A-4FE2-A1CF-C9403B5B551E remains PENDING, binding_verified=true, approved=false, business_apply_allowed=false, last_error=null. No new instance was submitted and no approval was performed. Both human approval tasks remain pending; joint approval acceptance is not complete.
