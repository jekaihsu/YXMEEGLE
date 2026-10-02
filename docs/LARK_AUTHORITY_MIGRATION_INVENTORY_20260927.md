# Q2／Q3：成果交付、單一 Lark 審批與財務操作封鎖盤點

## 核定邊界與本輪範圍

依 `HANDOFF_20260927.md` 最上方最新裁示：工作台供同事交付成果，不提供直接財務操作；成果通過／退回統一由 Lark 審批決定。工作台保留提交、發起或關聯、查回、補件及進度呈現。成果通過不等於付款、入帳、結清。既有核准席次、all/any 條件及需要不同實際操作者的既定規則不變；不為每項任務另加審批。學習／能力認定／考評停用及能力 Base 禁止回寫保持。

本輪僅讀碼、執行合成資料的記憶體探測、寫審查文件，沒有修改 shared code、建立真單、代人核准或發通知。以下是可審阅實作範圍，**不是已完成封鎖或原生接入**。

## 實測：最新裁示與現行正式行為仍不一致

在合成工作區 `environment=production`、`demo=False` 呼叫現行業務函式：

- `finance_propose` 成功建立含合約金額／預算的本機草稿。
- `review_submit → review_vote` 由現行指定兩席投票後，cycle 變 approved、node 變 completed，沒有 Lark instance。

聚合證據 `.runtime/q2-q3-local-authority-audit-20260927.json`。這是本機程式行為實測，不是正式公司資料被操作的證據。它證明只隱藏 UI 或僅封鎖變更／展延／skip 不足以滿足 Q3。

## 入口清單與建議處置

### 成果提交與正式決定

| 現有入口／位置 | 現行效果及授權 | 對照 Q3 的具體遷移 |
|---|---|---|
| `workflow.task_start` | 負責人或有效代理開始工作；有前置成果檢查。 | 保留執行動作，不增加原本未要求的 Lark 審批。不能把開始視為驗收。 |
| `workflow.task_complete` | 執行者填 output，直接 task.status=completed。 | 保留任務執行完成／提交成果，明確與正式驗收狀態分開。不要只因目前 status 名為 completed 就一律要求每任務新審批。既有需驗收的成果仍需對應 Lark 證據；下游若要求「已核准成果」應查相應證據，不單看 task completed。 |
| `workflow.task_return` | 原負責人／代理填原因直接設 rework，並重開節點。不是主管審批端點。 | 不可繼續作為「主管正式退回」入口。可保留同一執行者的自我補正／撤回提交語義，保留原因、版本及過去驗收；若要推翻已核准範圍，走既定變更／補件版本，不覆寫舊核准。 |
| `operations.evidence_submit` | 保存文件／日報／連結；技術組 submitted，非技術組直接 accepted；PM 可提出 na_requested。 | 所有需正式覆核的成果提交只產生 submitted，不能由欄位提交順便 accepted。非成果的收件／資料登錄可保持獨立 recorded 狀態，避免把資料收妥誤作核准。不適用申請保留，不能由本地主管直接變 not_applicable。 |
| `operations.evidence_approve` | manager 或對應主管直接 accepted／not_applicable。 | 封鎖對外 action。以既定覆核條件的 Lark instance 決定接受或不適用；可由一張成果驗收單綁定多份 evidence，不必每附件新增一單。 |
| `operations.review_submit`、`node_complete`，以及 `workflow.node_complete` 後備分支 | 檢查 missing、建立本地 review cycle pending。`node_complete` 名稱實際是送審。 | 轉為準備不可變成果包／送 Lark，同一版本重送沿用 UUID。不在本地等待另一套投票。兩個 handler 都須經同一 server policy，不能只封其中一條。 |
| `operations.review_vote`、`vote()` | 本地 approved/returned 直接改 node completed/rework；TECHNICAL 需 supervisor；FINANCIAL 需 PM＋行政不同人；其他依 all/any。 | 最高優先封鎖公開本地投票。保留原席次計算用於建單和查回驗證，不授權工作台代投。Lark 退回同步成待補正，新版重新提交；本地缺資料、版本不符仍不得生效。 |
| `operations.delivery_submit` | 建交付批次、數量／單位、evidence 與 task 快照，required_reviewer_ids 依實際組主管。已要求 evidence.accepted。 | 保留成果批次及數量提交；將 accepted 來源換成可信 Lark 證據。可把本批次的證據覆核和成果驗收整合在適當既定申請中，避免同份成果重複輸入、重複核准。只提數量不建立請款金額。 |
| `operations.delivery_review` | 組主管或任何 manager 可 approved/returned；manager 可直接使整批 approved。 | 封鎖本地核准／退回。Lark 定義按既定組主管與批次範圍建立，不將舊 manager override 悄悄帶入新的席次政策。哪個主管已有明確責任就用該責任，缺責任阻擋送審。 |
| `workflow.approval_create/submit/confirm/lark/execute/withdraw/change_resume` | 變更／展延草稿存在；正式 submit 503，confirm/lark 只 demo。execute 本地 approved 後由 PM 套用；withdraw 目前僅本地。 | 草稿與送審入口保留，confirm/lark 不得在公司產品路徑假造結果。execute 必須可信 Lark 結果＋當前版本＋既定額外證據。pending 的 withdraw 改為申請撤回、查回遠端後顯示撤回；本地不能先假成功。設計變更仍需主管／業主佐證與 Lark 三線，不以 Lark 單一 APPROVED 自動補出缺證。 |
| `node_skip_create/submit/vote/apply/withdraw` | 正式目前只能草稿；demo 本地 PM＋組主管兩票，apply 標 approved_skipped。 | create/submit/apply 保留用途，vote 由 Lark 查回取代，維持兩位不同人；不改財務／結案不得跳過與必要實際成果條件。withdraw 與版本失效使用同一可信狀態機，不能拿 demo 票授權正式。 |
| `recurring_review` 的外業／內業預排 | 本地 PM 或 manager 將每期 history accepted/returned。 | 若原本該期已有審核要求，改為對應 Lark 結果；不擴大為所有日常追蹤都須审批。月考評屬最新停用功能，維持禁用，不因共用 recurring handler 恢復。 |
| `recurring_complete` 的 correction＋finished | 主管可直接將補正追蹤完成；一般追蹤可直接 accepted。 | 區分「記錄已聯絡／追蹤」與「成果已驗收」。前者保留，後者需既定 Lark 驗收證據才結束；未驗收不能用 finished 躲過正式成果退回／通過流程。 |

具體程式位置：`backend/workflow.py` 的 task/approval 分支，`backend/operations.py` 的 submit_review/vote、evidence/delivery/recurring 分支，`backend/node_skip.py`。公開入口統一經 `POST /api/actions`，仍須業務函式層防護，因為有別名／後備入口和 worker 呼叫。

### 財務金額及結案操作

以下建議全部從同事可呼叫的工作台 action 封鎖，涵蓋 manager／PM／行政，不能保留「管理員例外」形成第二套帳務系統。既有資料保留讀取、對應來源和歷史；原雙方／結清條件保留為驗證條件，不因功能封鎖改成可直接結案。

| 入口 | 現行可變更內容 | 封鎖理由／後续資料來源 |
|---|---|---|
| `finance_propose` | 合約金額、預算、稅基、幣別草稿。 | 工作台不建立另一個可編輯金額基準；顯示核定來源值與差異。 |
| `finance_approve` | 財務基準核定、寫 p.contract_amount。 | 不接受本地核准；資料是否已核定須有來源證據。 |
| `finance_allocate`、`finance_allocation_approve` | 跨案成本金額分攤及核准。 | 不在工作台計算／核准入帳歸屬；來源結果只讀。 |
| `finance_attest` | 基準、請款或實收付款 PM＋行政票。 | 不留站內財務簽核；原不同人條件不能被一個 manager 或 Lark 簡單狀態字串替代。 |
| `payment_create`、`payment_revise` | 請款／下包應付金額、期別和交付引用。 | 交付引用可展示，但不提供本地新增／改款项操作。 |
| `payment_accept` | 下包成果款的技術驗收標记。 | 技術驗收改從真實成果 Lark 結果讀回，不以本地按鍵簽收款項。 |
| `payment_approve` | 應收應付批次核准及生成收款追蹤。 | 封鎖本地款项核准。後續追蹤若保留，只追蹤外部核定資料，不代送催款通知。 |
| `payment_record` | 實收付金額、日期、憑證、本地未清余额。 | 禁止直接登錄金額、入帳、付款。工作台上傳成果／佐證不等於帳務紀錄。 |
| `payment_reconcile` | 全案已結清旗標及核對依據。 | 禁止手動結清。沒有已核實外部財務來源就顯示未驗證，不將 V4「已結案」或成果核准當結清證明。 |
| pricing/settlement 的 `review_submit/node_complete/review_vote` | 可用本地兩席讓計價／結案節點 completed。 | 不能經一般節點入口繞過財務封鎖。可展示外部業務狀態，內部結清證據缺少時仍標待核實。 |
| `input_mapping/input_draft/input_submit`＋generic input worker | 可映射 number 等欄位；現僅禁狀態／connector，未完整排除財務語意。 | **必須防替代通道**：新增、編輯、查證、送出、worker 執行和 HTTP 邊界均採核定成果欄位 allowlist；合約金額、請款、入帳、收付款、成本分攤及薪資欄位不得 generic 回寫。不能只靠中文欄名 denylist；未核實用途／field ID 保守禁止寫。既有排隊財務 input 同樣不能執行。 |

僅讓 `finance_*`/`payment_*` 回 403 還不完整：前台必須停止顯示可操作金額表單；generic input、財務節點完成、管理批次操作和重試隊列也須同一政策。能力 Base 的現有全部回寫禁令繼續是更強限制。

### 不應誤當成果驗收的行政／來源操作

| 入口 | 類型 | 建議保留的明確界線 |
|---|---|---|
| `daily_propose/daily_approve` | 日報與案件的來源配對治理。 | 修復的是關聯，並不核准日報成果、津貼或金額。可保留授權資料管理核對，名稱改清楚「核對配對」；source.review 仍從來源只讀，不能把配對 approved 當日報通過。若將來要求配對也送 Lark 再另核定，不擅自擴大 Q3。 |
| `migration_review` | 合併衝突核對與歷史保存。 | 保留純資料治理；解除 migration_review_required 不代表財務已核准。不能清旗標後把歷史本機財務票升級成來源正式證據。 |
| `quote_review` | PM＋業務認定有效／重複／追加報價，現有站內兩票。 | 它目前不直接改金額，但可能影響商業有效性。建議保留原分類提案／唯讀結果；任何「正式認定／核准有效報價」若仍要作下游權威，應接已核定席次的 Lark 結果，不能把它藏在 management 後繼續本地核准。不得藉本輪改成另一種核准人。 |
| `confirmation_issue/confirmation_ack` | 發出確認單通知／指定收件人收悉。 | ack 是收悉紀錄，不是審批。保留明確收悉語義，不作成果或財務核准。issue 會建外部訊息 job，須維持原外部通知授權邊界，本輪不發訊。 |
| `handover_request/handover_approve/handover_accept` | 指定職責移交、接手人接受，會改 owner／席次。 | 是權限與人員治理，不等於成果驗收；現行授權規則保留。不能移交後沿用不同人的舊 Lark 核准／批准範圍，變更責任使未生效申請需重核。 |
| `delegation_set/revoke`＋請假審批 verify | 有期限代理及來源查證。 | 保留 read-only 請假證據、freshness／起訖／範圍檢查。代理人若代正式審批，需 Lark 可查證的既定代理身分，不讓工作台 can_vote 代替遠端實際核准人。 |
| `sop_draft/publish/request/apply` | SOP 模板維護及案件採用。 | 屬配置權限，不新加成果審批。若改變待審範圍／必要交付，原生 binding 須失效；不可由 SOP 改版抹除已核准歷史或免除既定正式審批。 |
| `admin_person/project_roles/participants_update/schedule_set/calendar_update` | 系統權限／派工／班表維護。 | 保留核定管理能力，不算正式成果核准。派工或席次變動須触發相關 binding 換版。不得擴權讓 manager 直接取代指定成果核准人。 |
| `comment_add`、上傳／file_link、document_withdraw | 溝通、附件、撤下版本。 | 保留，附檔／評論不算核准；撤下已送審附件使該版本需重新查核或補件，不能讓原核准默默套用到另一個檔。工具内 mentions 不因此轉成發 Lark 通知。 |
| `sop_event_record/sop_deadline_resolve` | 明確作業事件及截止計算。 | 保留行政紀錄；事件不能當正式成果核准證據，不能借事件跳過期限變更审批。 |
| 學習、技能、能力、月考評及 `/api/learning/*` | 最新已停用。 | 不因復用審批 adapter、管理頁或 recurring 入口而恢復；能力 Base write guard 及舊 job 防護保持。 |

## 已有來源與查詢：可保留，但不能自動授權

- V4／報價總表來源同步保留。V4 業務狀態是 Q1 選定權威；`source_completed` 或 p.status 只能表示來源狀態，不自動產生本地成果核准票或結清證據。
- 日報 `review.status/checks/source_url` 是來源的唯讀事實；手動配對、checkbox 以及本機補資料都不能把它改為來源審批已通過。
- `POST /api/approvals/{id}/refresh` 現有使用者查詢只保存 external_status，刻意 `lark_binding_verified=false`。保留「僅供查閱、未確認版本綁定」的限制，不能接通 Q3 時直接把這條路徑升級成正式授權。正式改用已核實 native adapter／同一應用實例 GET；實例 code 由使用者貼入不等於屬於此成果版本。
- 同一應用的原生 approval readonly scope 成功、HR 名冊成功、請假代理欄位成功與成果審批 E2E 是不同驗收，不互相代用。

## 具體可執行遷移順序

1. **集中政策先封住**：新增不可由 client flags 改寫的交付工作台政策。`/api/actions` 和 domain 層共同拒絕財務異動與本地正式投票；generic input 和 worker 依真實目的欄位用途阻擋替代通道。demo／test 的本機票不能出現在公司使用流程，也不能因 workspace 名稱改變而升級為正式；純自動測試 fixtures 可保留演算法驗證。
2. **提交與決定分離**：保留工作、產出、批次、附件及補件。正式 review status 明列未送、送出中、Lark 審批中、待補件、已核准、已失效；節點完成／成果有效由可信結果導出。任務執行 completed 不改造成「每任務一單」；只在原本要求驗收的成果包／批次／節點建立正式審批。
3. **同一成果版本單一 binding**：沿 `native_approval.py` 保存不可變 UUID／app／tenant／案件／成果包／version／內容及來源 scope hash、控制項映射和原席次。工作台發起與關聯既有單共用驗證程序；已送出的版本不再要求另一份本地投票。不能以 UI 選項或通用 Lark APPROVED 直接繞過本人／席次／version。
4. **實際定义映射**：root 管理後台建立／核對定義。既有三張變更／展延／skip 不自動涵蓋所有成果驗收。成果包定義按原 all/any＋主管規則映射；不能為了方便 API 把原 any 改 all、並行改必須先後，或把不同人條件取消。UI 管理後台支持的实际流程需 GET 查回，無法證明相同規則就保持該類送審未就緒。
5. **狀態與補件**：只有 remote 拒绝／退回才顯示正式退回；補件保留舊版與拒绝原因，新版新 binding。未知、超时、刪除、撤回、改版、權限不足不授權新操作。仍由工作台明確套用已核准的變更／展延／skip；一般成果狀態查回更新不意味款项同步核准。
6. **歷史遷移保守**：保存所有既有 local votes/evidence/payment rows，標明 legacy_local 或 simulation，附原時間與人員。不要刪歷史、也不要把舊 completed 批量改為未完成。對下一次需要「正式核准」的動作，舊本機票不能提供權威；若有真实 Lark 單再依內容／人員／版本關聯核實。財務舊金額顯示本機歷史或來源差異，不能冒作來源已入帳。
7. **公開能力與 UI**：回應中分離 can_submit、native_definition_verified、remote_binding_verified、can_apply、readonly_finance，不用一個 connected 布林。移除核准／退回本地投票與財務表單，保留 Lark 原單連結、目前等待哪席、補件需求、原始來源。正式未就緒時可保存成果草稿，但不顯示已送出／已核准。

## 具體驗收與部署門檻

- 正式公司身份直接 HTTP 呼叫所有 finance/payment action、pricing/settlement completion、local review/evidence/delivery/skip vote 皆被政策拒絕；manager 不例外。不能只測按鈕不見。
- 合法成果提交、附件、評論、@、任務執行、日報唯讀及缺漏核對仍可完成；不新增與決策無關的審批阻擋。
- 可核准的 Lark 單必須精確綁該成果版本與原席次，重送同 UUID 不新增單，未知結果先查；不能用另一案、另一版、別人的或自動核准紀錄冒充。
- 本人／合法遠端代理與不同人規則、駁回、補件換版、撤回、失效、停權、上游來源改版、後續重查皆驗收。遠端不通時不假核准、不自動完成、不算款项結清。
- 舊本機 approved 與 source status 的回歸要證明只能作歷史或來源顯示；不是正式成果 authority。已完成歷史不批量抹除，後續動作要求當前可信證據。
- 學習與能力 Base 禁写測試繼續全部通過，generic input/job_retry 不能恢復停用功能。

需查證的缺資料是「哪些現有 Lark 成果驗收定義及控件」「各成果包原核准人如何對應真實帳號」「外部財務唯讀結果的來源欄位」，不是重新詢問 Q2／Q3，也不是重新訂核准席次。未查證前應阻擋該類正式決定，仍完成已授權的成果提交準備。
