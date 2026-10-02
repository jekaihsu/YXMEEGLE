# 原生審批正式接入契約

2026-09-27 使用者授權建立設計變更、期限展延、節點跳過專用審批單。此文件區分已核定政策、官方 API 能力及仍待真實驗證部分；未指定實際測試申請人／核准人前，不送測試單、不代人核准。

## 官方查證與最小權限

| 操作 | tenant token 端點 | 最小 scope |
|---|---|---|
| 建立原生定義 | POST `/approval/v4/approvals` | `approval:definition` |
| 查已知定義 | GET `/approval/v4/approvals/{code}` | 已有 `approval:approval:readonly` |
| 建立原生實例 | POST `/approval/v4/instances` | `approval:instance` |
| 查實例／相同 UUID | GET `/approval/v4/instances/{instance_id}` | 已有 `approval:approval:readonly` |

全程同一工作台應用 open_id；不要求取得 user_id，不需增加 contact:user.employee_id:readonly，不使用另一 CLI 應用的身分。定義／實例的 narrow scope 本身是該資源完整管理權，不能描述為僅一次建立權限。程式不呼叫代人同意／駁回 API。

官方指出 **API 建立的定義無法經管理後台或 API 停用、刪除**，且建議企業自建應用優先在審批管理後台建立。主線應優先以已登入管理後台建立可維護的三張定義；若選 API，建立前明確告知這項不可逆限制並審閱具體 payload，不能悄悄建立試驗定義。API 傳入既有 approval_code 是全量覆寫，禁止拿舊公司定義試作。

來源：[建立定義](https://open.larksuite.com/document/server-docs/approval-v4/approval/create.md)、[查詢定義](https://open.larksuite.com/document/server-docs/approval-v4/approval/get.md)、[建立實例](https://open.larksuite.com/document/server-docs/approval-v4/instance/create.md)、[查詢實例](https://open.larksuite.com/document/server-docs/approval-v4/instance/get.md)。官方原文已存 `.runtime/approval-official-*.md`，此次僅讀公開文件。

## 專用表單與流程草案

三單名稱為「詠翔專案工作台－設計變更」「詠翔專案工作台－期限展延」「詠翔專案工作台－節點跳過」。共同欄位：工程編號、案件名稱、申請原因、影響範圍、工作台申請識別與版本、內容驗證碼。追加內容：變更含原／新版與費用、排程影響及對外確認佐證；展延含每項任務原期限／新期限；跳過含節點與任務快照、跳過影響及後續仍需交付的成果。實際控件 ID 待建立後 GET 查證，絕不把此草案名稱當真實 ID。

- 節點跳過：PM 和該組主管兩位不同的有效人員，共同核准。可用單一 Free 多選 AND 節點；指定這两人、不允許同人兼兩票。`starter_assignee=STARTER`，本人仍須實際核准，不使用 AUTO_PASS。財務、結案和已完成／封存節點仍禁止跳過。
- 期限展延：依 PRD_v0.4 第 6 節由主管確認；原期限在待審及核准未套用期間仍有效。跨組申請的主管人选尚需依實際任務與已核定責任人確認，不臆造指定全公司主管；缺可核實人选先擋送審。
- 設計變更：依 PRD_v0.4 第 7 節保留公司主管、業主確認佐證及 Lark 內部審批三線。Lark 核准不替代另外兩條，客戶不因表單建立自動成為 Lark 帳號。內部核准人需已核實的責任關係，不能預設任意 manager。

送出只用 `node_approver_open_id_list:[{key:已查證node_id,value:已授權人員IDs}]`，不混 user_id 造成聯集擴大、不設定 node_auto_approval_list。申請內容以 JSON string `form` 傳送；`allow_resubmit=false`、`allow_submit_again=false` 防遠端沿舊內容另送，仍須查回辨識改版或另生實例。定義可見範圍盡量限制工作台入口，遠端另行發起的未綁定單據永不授權工作台操作。

## 不可變綁定與故障處理

每個本機版本在任何網路寫入前持久化唯一 UUID、app／tenant／workspace／案件／本機申請 ID、申請人、定義快照 hash、表單控件和值、核准席次與實際 IDs、範圍版本 hash。正式呼叫前重新檢查身分、授權、版本與定義。沒有實際定義映射時不送出，不解凍／改期限／跳過。

同版本一律沿用 UUID。官方支援直接以 UUID 查實例；衝突 60012、超時、5xx、程序重啟先 GET 相同 UUID。查無或讀取失敗不能推定未建立，更不能用新 UUID 重送。首次送出／未確定結果分開標記，未知結果保留 outcome_unknown，由後續同 UUID 查回；只有明確尚未嘗試過的準備紀錄才首次 POST。

查回需要完整匹配定義、UUID、申請人、每個綁定表單值及實例識別。同時驗證目前案件／任務／責任人與權限快照未變。只有 APPROVED 還不夠：每個既定核准人必須在正確 node 的 task_list 有 APPROVED、type AND，並能對應到實際 PASS 動態，不能把 DONE、自動通過、轉交、加減簽或去重當成預定本人同意。任何多義、不符或缺資料狀態不授權。

查回結果僅建立可信外部核准證據；業務套用仍由 PM 明確執行，保留所有既有財務／交付／三線確認 gate。使用前重查遠端，撤回／刪除／駁回／查證失敗不授權新操作；已發生歷史不可抹除。回呼只作受驗證的刷新提示，不直接把傳入字串寫成 approved；尚未完成事件驗證前以 worker 輪詢代替。

## 實作與驗收界線

已實作獨立 `backend/native_approval.py` 和 `backend/test_native_approval.py`，不直接啟用正式送審。2026-09-27 原生模組 36 項＋人員目錄 35 項共 **71 passed in 2.47s**；全部為本機／假 HTTP，無真實申請或代人核准。涵蓋錯定義、不同 form 值、重複控件、錯人／同人／自動同意、來源改版、撤銷、超時已建立但回執遺失、重送不第二次 POST、查回未完成／錯誤及 durable checkpoint 失敗不得寫入。

`prepare_binding(mapping, definition, context, applicant, approvers, content, field_values)` 產出不可變 payload 與 UUID；mapping 必含邏輯欄位 binding/content，各欄對應实际 id/name/type，流程每節點對應實際 node_id 及 seats。初版只接受已查證 input/textarea 控件，其他型別須先實作明確契約。context.scope_hash 必須涵蓋目前案件／任務／責任人／人員 active 等適用版本，caller 不得只採粗略 project.revision。

`NativeApprovalAdapter(adapter, authorize).submit(binding, context, checkpoint)` 的 checkpoint 必須在回傳前原子持久化 attempted 狀態並使用版本／唯一約束抵擋並行。submit 遇任何寫入錯誤先查同 UUID；曾嘗試版本即使查無也不再 POST，交人工核對，避免查詢可見性延迟下重複申請。`poll` 每次重新 GET 定義和實例，不缓存核准權。authorize callback 每個網路邊界檢查目前公司、操作者、版本與使用範圍。回傳 approved 只是外部證據，不改本機業務 approved 或節點。正式整合仍須補上 service 持久化、worker、使用前查證及三線確認，再做真實兩人端到端驗收；不存在僅由 config 旗標打開正式功能的捷徑。

唯讀請假定義成功只證明 definition read，與這三類正式送審無關。建立定義成功、scope/token 可用、假 HTTP 通過均不能單獨顯示正式核准已串通。
