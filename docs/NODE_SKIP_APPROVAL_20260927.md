# 節點跳過審批：核定規則、實作與正式接入界線

使用者已選定一般節點由「PM＋該組主管共同核准」。兩席須由兩位不同的實際操作者確認。計價請款與結案不適用跳過；原本財務基準、交付版本、實際收付款雙方核對及結清條件保留。

## 已實作的本機契約

- `workspace.node_skip_requests` 保存申請、原因、影響、案件／節點／任務快照、PM／主管身分、版本、票決及歷史。每次重提建立新的申請 ID 與版本，保留舊資料。
- 既有 `/api/actions` 接受 `node_skip_create`、`node_skip_submit`、`node_skip_vote`、`node_skip_apply`、`node_skip_withdraw`，沿用工作區 version 與 request_id 防止並行覆寫或重送。
- 草稿不改節點或任務。測試／示範流程為 `draft → pending → approved → applied`；核准後仍由 PM 明確套用。駁回、撤回及失效分別保留狀態。
- 套用只將節點標成 `approved_skipped`，保留原任務狀態、成果及時間，不偽裝為 completed。`policy_summary.progress` 分別提供 completed_nodes、approved_skipped_nodes、total_nodes；`nodes[].skip` 顯示申請 ID、有效性與模擬標示。
- 有效跳過表示核准排除該節點的適用範圍，`project.engineering_waivers` 明列相關申請。財務基準、請款交付版本及收付款仍需照原規則核實。任何 `input_task_ids` 需要的成果，仍須真的 completed 並有 output；跳過不能充當交付資料。
- 已完成、來源已完成、封存、中止、財務及結案節點不能提出跳過。PM、組主管未指派、同一人兼任兩席或帳號停用時，不能送出或核准。管理員角色不自動取得兩席票決權。
- 案件版本、節點任務／必要資料、責任人、核准人、核准人啟用狀態、SOP 版本或申請內容改變，都使既有授權失效。歷史與票決保留，恢復原工作狀態並要求重提。

前端契約：create payload `{reason,impact}`；其餘操作帶 `{id}`；vote 另帶 `{seat:'pm'|'supervisor',result:'approved'|'rejected',reason?}`；withdraw 必填 reason。所有操作帶 project_id 與 node_id。

## 正式 Lark 送審尚未完成

正式區可保存草稿；submit/vote/apply 會拒絕，且不改節點工作狀態。示範票不能用在正式區。現有設計變更與展延的正式送審同樣尚未完成。既有實例查詢只保存外部狀態，`lark_binding_verified=false`，不能因此取得工作台核准。

`workspace.approval_connection` 是伺服器在回應時計算的能力，不採信資料庫內的成功旗標。`native_submit.available=false`，並說明缺少的審批单與未完成項目。填入 definition code、取得 token 或唯讀成功，都不會讓正式送審自動變成可用。demo 與 test 命名空間的 simulation_available 與 `/api/actions` 的模擬權限一致。

## 真實唯讀查證

本輪專用應用 GET 已知請假定義，實際回 HTTP 400／`99991672`。錯誤要求 `approval:approval`、`approval:approval:readonly` 或 `approval:definition` 其中之一；最小唯讀項為 `approval:approval:readonly`。這是應用身分權限，不是 CLI 使用者端點的 `approval:approval:read`。

[官方定義查詢 API](https://open.larksuite.com/document/server-docs/approval-v4/approval/get) 使用 tenant token、`GET /approval/v4/approvals/{approval_code}`。本輪未讀員工審批實例，未建立申請、未建立定義、未自行加權限。私有聚合紀錄為 `.runtime/approval-definition-probe-20260927.json`；官方規格保存於 `.runtime/approval-definition-official.md`。`scripts/probe_approval_definitions.py` 可重跑，只讀已知／設定的定義並輸出聚合結果。

既有公司證據只核實請假代理欄位及起訖，不含設計變更、展延或節點跳過的表單與流程對應。目前保存設定沒有這三類 definition code。官方本模組索引未列出應用身分列舉原生定義的端點，因此沒有猜測或掃描 ID。

## 真實送審的後續實作契約

1. 取得公司指定的原生定義，唯讀核對 form 控件 ID、型別、必要值、流程 node ID、AND 共同核准語義與人員選擇規則。不能借用請假定義，也不能把 OR 節點當成共同核准。
2. 審批內容須可驗證 workspace／案件／節點／申請版本／內容 hash；保存定義快照 hash、選定核准人的實際 Lark 識別與送出表單。任何映射改版須重新查證，不能硬編未核實的控件。
3. 送出前依即時權限、目的租戶與快照再次檢查；使用不可變 request UUID 綁定同一版本。超時保存 outcome_unknown，先查已建立實例；不得以新 UUID 盲目再送。
4. 保存真實 instance code／url 與回執，再唯讀查回表單、申請人、定義與兩席核准紀錄。只有全部匹配、兩人核准且版本仍有效，才可轉成可套用。不能只看 APPROVED 字串或使用者填入的實例編號。
5. 回呼須驗證平台來源；回呼只作刷新提示，伺服器查回最新狀態防止重送或亂序。無回呼時補查；撤回、駁回、刪除、未知或查證逾期皆不授權新操作。套用前須重新查證，不採信過期快取。
6. 正式生效後若撤銷或版本失效，移除後續使用授權並標需重核，保留已發生的工作、財務憑證及審計，不自動刪除歷史或反向改寫真實款項。
7. 真實隔離驗收應涵蓋核准、駁回、撤回、超時、重复、同人兼任、停權、申請後改版、錯誤案件綁定、資料交付依賴及財務保護。沒有真實回執前，維持「Lark送審待設定」。

原生提單的資料型態、UUID 与控件限制依 [官方建立實例 API](https://open.larksuite.com/document/server-docs/approval-v4/instance/create) 及本機 lark-approval 技能核對；正式串接前仍須針對選定 user／tenant 端點核實其所需 scope，不把兩種身分混用。

## 驗證範圍

本輪新增能力狀態與跳過規則測試，使用本機假資料、記憶體／暫存 SQLite，不連真實審批、不改正式資料库。自動測試證明規則與隔離，不代表已完成 Lark 端到端送審。
