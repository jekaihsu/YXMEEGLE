# 第三輪逐行審查：各項證據與修復驗收

2026-10-03；所有項目均為待修復。重現斷言通過表示現存缺陷已確認。完整範圍與限制見 [主報告](README.md)。

## [[P1] 確認單換版仍沿用舊版收件確認，未重發也能完成節點 · #53](https://github.com/jekaihsu/YXMEEGLE/issues/53)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/backend/operations.py#L213)

位置：backend/operations.py:213–216、551–579、819–842。missing() 只看最後 confirmation_issue 的發出狀態與收件人集合，沒有核對 issue.evidence_id 是否為目前 confirmation 證據。

重現：建立 v1 確認單，以真實 Worker 在獨立 SQLite demo namespace 跑 durable simulation，得到 simulated 狀態及送達回執；指定收件人確認 v1；evidence_submit 換成 v2 並撤下 v1；沒有建立 v2 issue，missing() 卻為空，再 review_submit/review_vote 即 completed。

影響：成果內容已改版，但新版本未發送／未經收件組確認就被視為完成。P1 指流程完整性，不是聲稱已傳送錯誤實際通知。修正需綁定目前 evidence ID／hash、PM 與收件範圍；換版必須使舊確認只作歷史，且取得新版本發送及確認回執。驗收需包含未換版正常通過、換版後阻擋、發出並確認新版後通過。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/test_core.py)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#18。

## [[P1] 身分切換後仍套用舊操作回應，重新顯示前一工作區資料 · #63](https://github.com/jekaihsu/YXMEEGLE/issues/63)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/frontend/src/App.tsx#L95)

- 位置：`frontend/src/App.tsx:76`（acceptWorkspace 只比 version）、`:81-85`（refresh 清掉前工作區但先接受新 session）、`:95-96`（run/upload 回傳沒有 session epoch 驗證）、`:106`（手動 refresh 未因 mutation 禁用）。
- 觸發：A 的動作已送出，網路回應延遲；同瀏覽器另一分頁切換工作區或登入身分後，此頁手動重新整理取得 B session；接著 A 的舊回應才到達。
- 實測：真實 `App` 發起 `task_start`，攔住 fake fetch 回應；關閉任務面板後模擬下一次 `/api/session` 回 B/workspace-B，並按真正的「重新整理資料」。A 案已從畫面清除；釋放舊回應後，左下角 `ACTOR_B` 與 `PRIVATE_CASE_A` 同時出現，toast 為「已儲存，工作台已更新」。
- 影響：新身分畫面重新持有上一個 actor/workspace 的案件、資料及能力標記；可能是較高權限投影。後續 API 仍會後端授權，**本證據沒有證明後端越權寫入**，也不要求攻擊者任意控制伺服器回應。
- API 契約：`backend/app.py:415-464` mutation 在請求開始取得身分並回原 workspace；延遲回應本身正常，前端應拒绝跨 epoch 資料。`upload` 同一接收方式尚未另作檔案動態測試。
- 修正：每個 mutation 捕捉 actor/workspace/session epoch，套用回應及 toast 前比對；`acceptWorkspace` 不可只比全域 version。身分清除／變更應使在途請求失效；同一 epoch 保留原有排序保護。
- 驗收：A→B、正式→測試、登出→登入、延遲 upload/run 回應都不能復活 A 資料；正常同工作區 mutation 仍可更新。
- 證據：`docs/review3/reproductions/browser/epoch-proof.js`、`docs/review3/evidence/review3-frontend-epoch-evidence.json`；`docs/review3/images/review3-session-race.png`。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/browser/epoch-proof.js)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#19。

## [[P2] 交付批次改派主管後，仍允許舊主管核准 · #54](https://github.com/jekaihsu/YXMEEGLE/issues/54)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/backend/operations.py#L656)

位置：backend/operations.py:643–663。建立批次時將 required_reviewer_ids 保存成快照；delivery_review 只檢查該清單，未比對現任節點主管。delivery_current（:96–108）只驗內容、成果、文件與任務，不驗現任核准職責。

重現：由 PM u-pm 建立交付批次，當時指定的控制組主管為一般成員 u-control；管理員透過真實 project_roles 改派 u-field；u-control 不具管理員／業務備援權限，仍能 delivery_review approved，且 delivery_current=True。測試使用實際 apply_operation，不是直接改核准結果。

影響：現任主管未核准的交付仍顯示有效，可能被下游流程引用。未測真實遠端付款，不能聲稱款項已支付。修正需將主管席次與批次範圍綁定，每次投票／形成核准時檢查最新職責及在職狀態；改派應要求新任主管確認，保留歷史紀錄。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/test_core.py)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#18。

## [[P2] 主管交接未更新節點主管，接手人投票持續409 · #55](https://github.com/jekaihsu/YXMEEGLE/issues/55)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/backend/operations.py#L804)

位置：backend/operations.py:799–817（handover_accept）、257–260（seats）、290–296（submit_review）、312–314（vote）。交接更新 project.supervisor_id 與 pending cycle.seats，卻保留 node.supervisor_id；review_hash 仍依旧 node 主管計算，因此再送審會回傳同一輪不一致 cycle。

重現：控制節點先送審；主管由 u-manager 經申請、核准、接手人接受交接給 u-field；案件主管和 pending cycle 席位是 u-field，節點主管仍是 u-manager；重送審回同一輪，u-field 投票回 409「職責已變更」。

影響：使用者完成交接後依然不能完成覆核，需要管理員另改節點配置。這與 #45 投影導致看不到交接不同，直接使用合法接受 API／操作後仍成立。修正需明確區分交接範圍，將已交接職責對應節點、reviewers、pending seats 與 hash 一致更新；不得把無關的獨立組主管一律更換。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/test_core.py)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#45。

## [[P2] 報價共同認定在PM改派後仍計入舊PM的票 · #56](https://github.com/jekaihsu/YXMEEGLE/issues/56)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/backend/management.py#L34)

- `backend/management.py:31–44`：僅核對此次 actor 是當前 seat；尋找 pending review 時只比 quote id、source_hash、classification，未把目前 PM／sales 身分加入綁定，湊齊 seat 字串即 approved。
- 交叉位置 `backend/operations.py:469–519`：真實 project_roles 改派會失效 financial node review 的舊票，卻未處理 quote_reviews。
- 合成重現：PM u-pm 投 effective → 管理員用真實 project_roles 將 PM 改為 u-control → 現任 sales u-field 投 effective → review=approved，但完全沒有 u-control 的票，u-pm 舊票沒有 invalidated。
- 影響：現任 PM 尚未確認，報價就呈現雙方認定；不是原生審批核准繞過，未聲稱產生外部付款／遠端寫入。
- 建議：每次投票與最後核准時核實現任兩席及在職状态；project_roles/handover 改派時失效受影響 pending votes；記錄 seat/principal/version 綁定。
- 驗收：改派後等待新 PM 投票才 approved；原席不變時保持正常；已完成歷史票不直接抹除。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/test_permissions.py)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#18。

## [[P2] 試行複製保留附件索引但缺少檔案，下載404 · #57](https://github.com/jekaihsu/YXMEEGLE/issues/57)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/backend/app.py#L698)

- `backend/app.py:698–703` 將整個 project deepcopy，包含 local files/id/url/storage/sha256；沒有複製 uploads bytes 或明確改成來源參考。`:513–515` 下載依目前 workspace 的 SHA256 子目錄找檔案。
- 合成完整 HTTP 重現：正式 p2 上傳 synthetic-pilot.txt，下載 200 → manager POST /api/pilot/copy 200 → POST /api/workspace/switch test 200 → GET /api/workspace 附件仍 storage=local，URL 不變 → 該 URL 404。
- 影響：試行資料看似包含正式成果，但開啟/驗收附件會失敗；以這些 file IDs 作為 Input/成果佐證的試行不完整。沒有跨工作區讀取證據，問題是可用性而非資料外洩。
- 建議：若設計要求完整試行快照，受控複製 bytes 並核對 hash，與 DB transaction 失敗清理協調；若不複製，標示唯讀來源參考且不可宣稱 local 可下載，不可放寬下載跨 namespace。
- 驗收：複本每個宣稱 local 的附件均能在 test namespace 驗 SHA256，正式檔案及版本不被修改。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/test_permissions.py)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#23。

## [[P2] Bootstrap管理員降為在職成員後意外失去一般存取權 · #58](https://github.com/jekaihsu/YXMEEGLE/issues/58)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/backend/production_access.py#L18)

- `backend/production_access.py:18–19`：只要 bootstrap_admin=True 即立即以 manager role 判斷 admission，不再走 employed directory 分支。
- `backend/operations.py:368–389` 的 admin_person 可把 active 管理員降為 member，保留 bootstrap_admin；`backend/app.py:651–653` 將 role-map 管理員加 bootstrap flag，故旗標不是純人工異常資料。
- 合成重現：fresh directory/employed/app identity 完整且 active manager → access_mode=normal → 真實 admin_person 降為 active member → access_mode=denied；同筆資料只移除 bootstrap_admin 即 normal。
- 影響：撤銷管理員權限被意外擴大成禁止一般在職員工使用；重新 OAuth 仍經 require_access 失敗。這不是停權或離職情境。
- 建議：先以可信新鮮在職名冊判斷一般 admission；bootstrap fallback 只供仍具有效 bootstrap 管理員身分者使用，降權者不可憑 bootstrap 恢復權限，但應保留一般員工资格。
- 驗收：降權後可使用 member 功能、不能用 manager/recovery；過期/缺失/離職名冊仍依原規則拒絕。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/test_permissions.py)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#19。

## [[P2] 部署資產核對失敗仍以exit0結束 · #59](https://github.com/jekaihsu/YXMEEGLE/issues/59)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/scripts/deploy_verify.py#L88)

- `scripts/deploy_verify.py:35–37` 將 latest_frontend_assets / asset_downloads 設 false，但 `:88–93` 只寫報告、print、main()，無失敗 exit。
- 合成重現：mock 所有 HTTP，local index=new.js、remote index=old.js；main() 正常返回 None（命令列正常 exit 0），JSON latest_frontend_assets=false。
- 影響：以命令 exit code 判斷的發布程序會把舊 bundle 或 asset 下載失敗判為通過；只看 stdout JSON 的人工仍可辨識。未聲稱當前正式部署版本錯誤。
- 建議：輸出完整 receipt 後，所有必要 checks 必須 True 才回 0，否則非零；涵蓋 asset mismatches 與 downloads 404。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/test_permissions.py)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#7。

## [[P2] Drive子目錄未讀完分頁即判定唯一或建立新目錄 · #60](https://github.com/jekaihsu/YXMEEGLE/issues/60)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/backend/lark_adapter.py#L208)

- 精確位置：`backend/lark_adapter.py:199-217`，核心為 `:208` 第一個符合名稱的資料夾立刻回傳，`:209` 將缺少 has_more 當作 false，`:214` 在未證實完整目錄後直接建立。
- 呼叫鏈：`backend/jobs.py:350-369` 逐層取得案件、節點、Input/Output/佐證資料夾，接續上傳至所選目的。問題與 #35 根目錄白名單不同，這是在已選定父目錄內的子目錄唯一性及完整性檢查。
- 第一條可重現路徑：第一頁包含 `Output` token first、has_more=true、next_page_token=next；第二頁另有同名 token second。真實 LarkAdapter 使用 MockTransport，方法只發出一個 GET 並回傳 first，第二頁永遠不讀。既有 len(matches)>1 只能抓同頁重名。
- 第二條可重現路徑：GET 回傳 `{"code":0,"data":{}}`。方法將此視為完整空目錄，繼續 POST create_folder。應視為不完整回應並停止，不可推論「沒有資料夾」。
- 影響範圍：父目錄內實際有跨頁重名時會依遠端分頁順序任選目的；上游回應缺欄位時可能建立多餘目錄。沒有證據顯示正式環境已發生資料錯置，也不是任意外部目錄逃逸。
- 修正方向：嚴格檢查 files 為 list、has_more 為 bool、下一頁游標有效且未循環；收完所有頁後才能認定唯一、空白或重複。重複與不完整皆 fail closed。只完成列表後才可 POST create。
- 測試：`docs/review3/reproductions/test_jobs.py` 前兩項，真實 LarkAdapter.request/folder、httpx.MockTransport，斷言當前缺陷。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/test_jobs.py)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#21。

## [[P2] 部署前只核對manifest列出檔案，未拒絕額外檔案 · #62](https://github.com/jekaihsu/YXMEEGLE/issues/62)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/scripts/workbench_cloud_setup.py#L110)

- 精確位置：`scripts/workbench_cloud_setup.py:110-117`、`scripts/workbench_formal_release.py:28-32,56-58`。兩個入口只驗 manifest 中列出的檔案 hash，沒有拒絕額外檔案；接著把整个 stage 目錄交給 deploy。
- 合成證據：建立只有 app.py 的 manifest 與成功 smoke receipt，另外放入未列於 manifest 的 `backend/private.json`（僅合成文字）；真實 cloud_setup.deploy 沒有拒絕，抵達 subprocess.run，cwd 為含額外檔案的 stage。subprocess 已替換為本機 fake，因此**僅證實入口允許派送，不是實際上傳結果**。
- 包裝影響：repository `Dockerfile:13` 是 `COPY backend/ ./backend/`；`.dockerignore` 沒有排除 backend/private.json。相反，`.env` 確實被排除，不能拿 .env 範例聲稱一定進映像。因此問題以「已驗證封存包可混入未審查檔案」定義，實際雲端 CLI 還可能有額外忽略行為，未實測。也可用新增 backend/*.py 重現同一前置檢查缺口。
- 觸發前提：stage 建立／smoke 之後發生新增檔案；不是遠端 HTTP 攻擊。影響部署可重現性，以及混入未忽略私檔時的保密性。尚無正式發生證據。
- 修正方向：部署前以 canonical relative paths 比對實際檔案集合與manifest完全相等，驗證所有hash與禁止符號連結，再從核定不可變封存包部署；smoke receipt應綁定同一包hash。兩個入口共用驗證器。
- 主代理複驗：`docs/review3/reproductions/test_jobs.py` **4 passed in 10.69s**。第4項新增測試，前三項同樣通過。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/test_jobs.py)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#7。

## [[P2] 同標題表單草稿互相覆蓋，可將另一筆內容送入本筆紀錄 · #64](https://github.com/jekaihsu/YXMEEGLE/issues/64)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/frontend/src/FormDraft.tsx#L7)

- 位置：`frontend/src/FormDraft.tsx:7-11`；真實呼叫點 `frontend/src/Operations.tsx:85`（多個 recurring 的「記錄本次執行」「本期核准／退回」）、`:72`（撤下誤件）、`:149`（多個批次覆核）。
- 原因：key 只含 namespace、URL project/node 與 title，不含 recurring/file/batch/entry ID。React 的 list key 不能隔離 sessionStorage key。
- 實測：兩個真正 `DraftForm` 以相同 title 渲染不同 record；A 填 `A_PRIVATE_DRAFT`，B 填 `B_DIFFERENT_DRAFT`；storage 只有一個 key。卸載／重新載入後，在 A 按「恢復暫存文字」及「儲存」，handler 收到 `{record:"RECORD_A",evidence:"B_DIFFERENT_DRAFT"}`。
- 影響：草稿互相覆蓋，且可提交到錯誤週期／成果批次／誤件操作。這是記錄識別碰撞，和 #41 useDraft prop key 變更是不同機制。
- API 契約：`backend/operations.py:754-771` 接受指定 recurring id 與 evidence，无法辨識文字來自另一個 UI 草稿；沒有伺服器級草稿識別可補救。
- 修正：DraftForm 明確要求穩定 record/action/scope ID，加入 storage key；版本敏感表單含 revision，成功保存後清除該 key。不同同名人員、同標題批次也需隔離。
- 驗收：同 route 同 title 的多個 record 分開保存／恢復；不同 record 不能互相捨棄或覆蓋。
- 證據：`docs/review3/reproductions/browser/draft-proof.js`、`docs/review3/evidence/review3-frontend-draft-evidence.json`；`docs/review3/images/review3-draft-collision.png`。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/browser/draft-proof.js)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#41。

## [[P2] 換案查詢失敗後仍在新案件下顯示上一案稽核紀錄 · #65](https://github.com/jekaihsu/YXMEEGLE/issues/65)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/frontend/src/AuditTrail.tsx#L6)

- 位置：`frontend/src/AuditTrail.tsx:6-9`；掛載 `frontend/src/App.tsx:192`（依 p 更換而無 key）。
- 觸發：在 A 操作紀錄頁查詢成功，以保留 `tab=logs` 的 hash 路由轉到 B；B 查詢延遲或 503。
- 實測：真正 AuditTrail 先取得 `PRIVATE_AUDIT_A`，換 pB 後 API 503。畫面標題 pB、錯誤 synthetic B failed，卻仍 render A 的 audit，沒有表明該列屬 A。API 沒回任何 A 資料給 B 查詢。
- 影響：把其他案件的操作者／變更／核准紀錄當成當前案件證據；延遲期間也會短暫發生，失敗則持續存在。這不是證明後端 audit 權限繞過。
- API 契約：`backend/app.py:371-390` 按 project_id 篩選；前端需把 cache 與 project_id/offset 綁定。另 page 也應換案重設。
- 修正：換案即清 data/legacy/error/page，或 keyed component；回應附請求身分鍵並驗證；若保留舊快取必須只能屬同一案且明確標示。
- 驗收：A→B 的 pending/503/404/成功四條路徑都不出現 A audit 在 B 標題下。
- 證據：`docs/review3/reproductions/browser/audit-proof.js`、`docs/review3/evidence/review3-frontend-audit-evidence.json`；`docs/review3/images/review3-audit-stale.png`。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/browser/audit-proof.js)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#19。

## [[P2] 日報審核狀態列舉與API不一致，核准和退回皆顯示待查證 · #66](https://github.com/jekaihsu/YXMEEGLE/issues/66)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/frontend/src/DailyRecords.tsx#L18)

- 位置：`frontend/src/DailyRecords.tsx:18` 將 reviewed/partial 映射為成功；`backend/v4_sources.py:93-102` 真正產生 approved/returned/pending/unverified；`backend/source_projection.py:114-118` 原樣保留 review。
- 實測：`docs/review3/reproductions/browser/daily-contract.py` 呼叫真正 daily_review + daily_index，輸入合成的「已通過」「已退回」「待檢核」。DailyRecords 全顯示「原日報檢核待查證」，核准及退回資訊皆消失。
- 影響：即使來源已明確退回也看不見退回標記；來源審核進度錯誤。舊的未使用 DailyReviewCell 反而有正確 enum，但不在目前路由使用。
- 此項 **不要求核對舊系統未配對日報，不作該歷史資料的上線門檻**；此為任何新日報也會遇到的前後端契約錯誤。
- 修正：共用 enum 或集中轉換，區分已通過／已退回／待檢核／未查證；別以自創 reviewed/partial 覆盖後端語意。
- 證據：`docs/review3/reproductions/browser/daily-proof.js`、`docs/review3/reproductions/browser/daily-data.json`、`docs/review3/evidence/review3-frontend-daily-evidence.json`。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/browser/daily-proof.js)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#27。

## [[P2] 日報換案保留舊分頁位置，顯示有資料卻無法翻回首筆 · #67](https://github.com/jekaihsu/YXMEEGLE/issues/67)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/frontend/src/DailyRecords.tsx#L6)

- 位置：`frontend/src/DailyRecords.tsx:6-10,17-18`。
- 觸發：A 有 61 筆，翻到第3頁；保留 tab=daily 換到只有1筆的 B。page 仍為2，請求 offset60；B 回 total1/items[]。
- 實測：真正元件顯示「共 1 筆符合條件 · 第 1／1 頁」，cards=0，上一頁及下一頁皆 disabled。使用者無法用分頁控制回到真正的 offset0。
- 修正：p.id 變更重設 page；回應 total 減少致 offset 越界時更新請求 state 並重新取得，不僅 clamp 顯示 currentPage。
- 驗收：換案、同步刪減、由第3頁減至1頁都能讀到首筆；頁碼與 request offset 一致。
- 證據：同 FE4 的 daily-proof.js / daily-evidence.json。與歷史未配對日報是否核對無關。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/browser/daily-proof.js)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#27。

## [[P3] 可攜式恢復遺漏workspace外鍵，重啟亦不補回 · #61](https://github.com/jekaihsu/YXMEEGLE/issues/61)

基準：`32caa8009e966d03574fa2f69a04a29653f333b7`；第三輪逐行審查，尚未修復。

[主要程式位置](https://github.com/jekaihsu/YXMEEGLE/blob/32caa8009e966d03574fa2f69a04a29653f333b7/scripts/backup_restore.py#L26)

- 精確位置：`scripts/backup_restore.py:26` 自行重建 business_records 的 workspace_id，未定義外鍵；`:126` 使用此 META.create_all 建庫。正常應用 `backend/storage.py:16` 則定義 ForeignKey('workspaces.id')。
- 本機證據：使用 storage.models 正常 schema 建立 SQLite 空來源，inspect 確认外鍵存在；透過真實 backup → restore 恢復至新庫後外鍵變為空集合；再次執行正常 metadata.create_all 仍不會補回。第三個 isolated test 實際走完整 archive creation/restore，並未捏造 ZIP。
- 影響：災難恢復後失去原本 workspace 與 business_records 的資料庫參照完整性保護；後續維運 SQL 或有缺陷寫入可留下孤兒紀錄。不是目前案件已丟失，也未證實一般 HTTP 能製造孤兒紀錄。
- 修正方向：恢復使用版本化應用 schema／migration，避免備份模組維護不一致 DDL；演練除 rows_equal/attachments_equal，也比對必要 constraint/index。既有恢復庫需明確 migration 補外鍵，create_all 不會修補已存在表。
- 測試限制：實際跑 SQLite schema inspect，尚未在 PostgreSQL 恢復實測；DDL 缺項可從兩套 SQLAlchemy metadata 直接驗證。

[可重現測試](https://github.com/jekaihsu/YXMEEGLE/blob/main/docs/review3/reproductions/test_jobs.py)；斷言證明現況缺陷，不是修復驗收。相關追蹤：#23。

根代理定級 P3：已證實 schema 不一致，未重現一般 API 產生孤兒資料；不以此單項宣稱正式資料損毀。
