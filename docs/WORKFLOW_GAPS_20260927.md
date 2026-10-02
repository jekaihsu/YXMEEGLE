# 工作流程剩餘缺口核對 — 2026-09-27

核對依據：`HANDOFF_20260927.md` 的本對話核定決策及其中四份 PDF 摘要，並直接閱讀目前 backend、Dockerfile、worker 啟動程式。此文件是本輪程式檢視結果，**不代表正式部署或 Lark 真實串接驗收已完成**。父 agent 同時整合其他模組，後續修正應逐項補登，不刪除查證歷史。

本 agent 最近完成的隔離驗證：`python -B -m pytest backend/test_backend.py backend/test_operations.py backend/test_workflow_completion.py backend/test_sop_deadlines.py backend/test_runtime.py -q`，96 passed。這些測試包含模擬 HTTP、隔離 SQLite、記憶體狀態，以及真實本機 dummy 子程序生命週期，不是公司正式資料的寫入證明。本次缺口稽核與後續本機修正未執行任何遠端寫入。

### 後續本機修正狀態

- 已修正 Docker 啟動：`scripts/run_service.py` 監督 web＋worker；先等待 web 的 DB-aware health（最多 60 秒），再啟動 worker，避免空資料庫同時建表。子程序意外退出或逾時即清理並非零退出；尚未部署。
- 已實作 `backend/sop_deadlines.py`：9 類有佐證事件、PDF 的 0／1／2／3／5／10 日及派工前 3 工作日期限、版本／來源追溯、日曆變更重算、固定契約日期與已開工保護。自動抓來源事件日期仍需明確映射，沒有猜測資料。
- 已實作 `training_return`：保存原提交內容與退回理由、退回 planned 後重新提交；不通過不增加能力。
- 已實作代理快取新鮮度與完整時分秒檢查：超過 300 秒、不具時區、尚未開始或已結束均不授權；worker 增加有效代理核准狀態唯讀刷新。實際公司審批的端到端驗收仍未完成。

## 1. 仍影響完整執行的項目

| 等級 | 項目／實際證據 | 實際限制 | 完成條件及性質 |
| --- | --- | --- | --- |
| 已本機修正；待部署驗收 | **背景程序啟動**。Docker CMD 已切到 `scripts/run_service.py`；來源同步與工作佇列分開捕捉錯誤。 | 本機程序生命週期測試已通過，還不能宣稱部署平台的五分鐘同步及通知正在運行。 | 部署後驗證 web／worker、共用 DB／附件路徑、重啟及實際排程心跳。見第 3 節。 |
| P1 | **正式設計變更／展延尚不能送審**。`backend/workflow.py` 的 `approval_submit` 正式模式回 503；`approval_confirm`、`approval_lark` 僅模擬模式可操作。`app.py` 可查既有審批，但明示未驗證實例與案件範圍，不自動核准。 | 公司模式可以存草稿和查看既有審批，不具完整原生送審、回傳及工作解凍鏈。不可拿請假審批的代理人讀取功能當成此功能完成。 | 需要核實設計變更／展延各自審批定義、表單欄位、業主確認來源及應用權限；本機可建立映射、冪等送審、狀態校驗和重試模組。用隔離審批測試核准、駁回、撤回、超時、重送，以及案件／版本／任務範圍匹配後，才開正式執行。 |
| 已有本機引擎；P2 來源映射待驗證 | **PDF 相對工作日期限**。`sop_event_record` 明確記錄 9 類事件及版本；引擎已涵蓋需求＋0／1／3、報價發出＋10、回簽＋1／2／5、派工前3、階段完成＋2、收到確認單＋1、完成＋3、計價条件成立＋3、成果交付當日通知。 | 日期目前由授權 PM／行政／主管帶佐證記錄，不能宣稱已由 Base 所有來源欄位自動捕捉。報價組與工務助理未指定時顯示待分派，不猜成人員或業務角色。 | 已測假日／補班、跨年、負向日期、換版、固定日期及已開工衝突。需再核實來源錨點欄位及角色對照，才能開啟自動記錄。 |
| 已本機實作；待隔離資源實際驗收 | **Input／檔案的 `isolated_live` 分支已實作**，`backend/test_isolated_live.py` 已通過 29 項測試。測試工作區必須明確選擇此模式，且 `test_base/test_drive_root` 必須匹配伺服器 `LARK_TEST_BASE_TOKEN/LARK_TEST_DRIVE_ROOT` 白名單；已知正式來源 Base 與正式 Drive 目錄不可作為隔離目的地。 | 本機模擬 HTTP 測試證明 Input 映射核實、寫入讀回、檔案流程及目的地防護；尚不能證明真實隔離 Base／Drive 寫回成功。此模式只開放 Input／檔案；測試通知、確認單、訓練紀錄及能力地圖仍模擬，demo 永遠模擬。 | 外部需核實隔離 Base、Drive 目錄及應用權限。使用已實作分支取得真實寫入回執並讀回校驗，驗收斷線、部分成功、外部改值、未知結果；正式能力地圖驗收須另列證據。 |
| P2 | **班表採人工核定表，未接 Attendance 正常班表**。`learning.py:cutoff` 只讀 `ws.work_schedules`，`schedule_set` 可由有權人員維護日期與正常下班時間；已發現的 Base 考勤欄只有實際打卡。 | 已正確取消固定 17:00，班表缺漏顯示待設定；但目前不能宣稱從 Attendance 自動取得正常下班時間。 | 外部需確認正常班表、考勤組／班次來源和身份權限；本機串接後保留來源及版本。實際最後打卡、加班時間不可當截止。人工班表仍可作明確核定的來源，不能冒充自動同步。 |
| 已本機修正；待實際審批驗收 | **請假代理快取及有效期間**。已新增 300 秒快取檢查及完整時區時間比較，worker 定期唯讀刷新；讀取失敗不沿用過期核准。 | 已通過半天請假開始／結束及過期失效測試；仍需公司審批讀取授權與實際撤回案例。 | 以隔離人員／案例驗證撤回、取消、代理更換及讀取失敗，不能將程式測試代替公司審批串接證明。 |
| 已本機修正 | **訓練退回及補交**。`training_return` 保留原提交、版本及理由後退回 planned，可重新提交。 | 尚不代表能力目標／生存線的自動達標判斷已實作；該計算仍等核定定義及資料口徑。 | 訓練通過與正式能力認定保持分開，不通過不可增加能力。 |
| P2 | **SOP 中部分追蹤尚需手動建立**。`jobs.py:schedule` 自建日／週／月與作業中客戶聯繫；付款核准建立收付款追蹤。檢視未見交付後自動建立補正追蹤、請款時自動記錄滿意度發送待辦、案件回傳本與各組工作登錄的明確事件鏈。 | 使用者可手動記錄產出／建立追蹤，但「依 PDF 自動推動全部工作」仍未完整。滿意度發送證據目前在結案產出中，不等於請款時自動觸發。 | 可本機依具體業務事件補建一次性或週期工作，重送不重複建立；未回覆滿意度不能阻擋結案。對外發送仍需已核實模板、收件人與權限。 |

## 2. 已補上的護欄與仍應清楚標示的限制

- **工程與財務結案**：目前已阻擋技術未完的結案；交付或財務失效會撤回本地完成狀態。來源狀態與工作台執行狀態分開，不能把 V4 的「已結案」當成本地雙方核准紀錄。
- **成果及請款批次**：已儲存交付工項、數量、單位、核定佐證及不可變版本；款項引用版本，版本失效要重綁並重簽；同一交付版本／沿革不能重複建立同類請款。尚需用真實工項資料驗證數量及契約分期口徑，程式沒有自行推算每一工項的契約可請領數量。
- **入帳雙方核對**：`payment_record` 先建立 pending receipt；`finance_attest` 的兩位不同 PM／行政操作者核對後才 verified 並計入 paid。內容雜湊防止金額／日期／佐證變更沿用舊票。這項規則已測試；**它不是銀行對帳串接**。目前 `evidence` 為必填文字引用，未強制每筆都是可讀回的附件 token 或結構化憑證 ID；若產品要顯示「附件已驗證」，須另接文件／來源引用校驗，不能僅凭非空文字標示。
- **來源合併**：`migration_review` 由主管確認並保存衝突快照；涉及既有財務者，主管解除遷移待核對後，仍需重新 PM／行政共同核定財務基準。不可把主管核對理由当成財務共同核准。
- **能力地圖及訓練資料寫回**：已有技能目錄／人員綁定讀取、能力認定的專門權限和後台工作；來源映射或人員關聯未核實時顯示 pending_mapping。尚須提供訓練紀錄目的表的已驗證欄位、Drive 儲存位置及真實回執。訓練佐證目前可引用連結，未見獨立訓練附件上傳至 Drive 的完整 API 鏈。
- **生存底線與考評**：`learning_standard_set` 保存定義及生效日期，`calculation_status='definition_only'`。目前不計算分數、排名或達標；這符合「公式／分母／目標／權重未核定前不產生結果」的決策，**不是可宣稱已完成考評計算**。標準核定後還需選定資料口徑、單位、有效版本、期間及演算規則並測試。不得從既有點數換算公式推測生存線。
- **班表與提醒**：現有 cutoff 是人員＋到期日的正常班表，缺漏不假造時間；`jobs.schedule` 當日摘要及隔日升級並非精確到分鐘的截止偵測。公司工作日及補班可配置，例行日遇假日的順延規則目前為下一工作日，仍須在制度文件明列，避免稱為 PDF 已寫明。
- **原生審批**：請假代理讀取、設計變更／展延送審、工作台節點共同確認是三件不同事。不可因任一通過而宣稱三者皆已串通。

## 3. 已落地的部署監督及待驗收部分

本機已完成以下生命週期修正，尚未向部署平台發布：

1. 新增 `scripts/run_service.py` 作容器主程序，使用 `subprocess.Popen` 啟動 uvicorn，先等待本機 `/api/health` 成功後才啟動 `scripts/run_worker.py`，啟動期限 60 秒；不用 shell `&`。
2. 任一子程序意外結束，主程序向另一個送終止訊號，等待有限寬限時間後強制停止，主程序非零退出，讓部署平台重啟。收到 SIGTERM／SIGINT 時轉發至兩個程序並正常回收。
3. Docker CMD 改成此主程序；兩程序共用同一 `DATABASE_URL` 及 `/data/uploads`，保留一個 worker。分拆服務時必須確認兩邊有同一持久化檔案位置；不能把只有 web 容器的暫存檔當 worker 可讀。
4. `run_worker.py` 的來源同步與工作佇列已分開 `try`；同步 API 故障不會略過同工作區已排隊工作。
5. 主程序持續監看 web／worker 程序存活；程序級死亡會造成容器非零退出。背景業務迴圈 heartbeat／最後成功時間的獨立監測仍待完善，活程序不能證明每筆外部業務工作成功。
6. 只啟動程序不代表可打開正式對外寫入。保持目前目的／組織／權限護欄，設定核實後以隔離資源先驗收。

最低驗收：web 和 worker 同時啟動；worker 被終止時容器不可仍回報整體正常；停止容器能回收兩程序；同步 API 故障不阻塞已排隊工作；來源同步 300 秒節拍、工作排程與去重可觀察；重啟後保留工作回執且不盲目重送未知結果。

`backend/test_runtime.py` 的 8 項本機驗收已通過：子程序意外 0／7 退出、啟動失敗清理、雙程序正常停止、web readiness 後才啟 worker、啟動逾時不啟 worker、部署白名單及機密排除。`deploy_prepare.py staging` 已納入 supervisor、worker、備份排程及非機密來源表 JSON；設定 JSON 只允許資源識別與欄位中繼資料，不接受 credentials keys。

## 4. 對外報告時可使用的完成界線

可以說「本地案件與交付／財務／代理護欄已實作並通過隔離測試」，也可列出有實際結果的 API 讀取。

目前不得說「完整 SOP 全部自動化」、「原生變更與展延審批已串通」、「Attendance 班表自動同步完成」、「正式能力地圖已更新」、「隔離 Base／Drive 已真實寫回驗收」或「已部署所有背景任務」，除非本文件對應缺口已有後續實作及實際驗證紀錄。

## 5. 發布與正式備份的唯讀核查

2026-09-27 僅檢查本機 scripts、既有部署紀錄與已安裝 Zeabur CLI 的 `--help`；未部署、未執行遠端命令、未重建 staging。`docs/DEPLOYMENT_RECEIPT.md` 所列 service／environment 是既有識別，實際目前狀態仍需另行查核。

已核實的命令語法如下。發布須先完成審查並重建來源白名單 staging，再於該 staging 目錄執行，不能直接從含 `.runtime` 的工作區發布：

```powershell
python scripts/deploy_prepare.py staging
# 接著以輸出的 staging_directory 作為命令工作目錄：
zeabur.cmd deploy --project-id 6ab61680a4c05a5bcb57ace9 --environment-id 6ab6168036d2a6cac409f0c6 --service-id 6ab61834a4c05a5bcb57ad69 -i=false
zeabur.cmd deployment get --service-id 6ab61834a4c05a5bcb57ad69 --env-id 6ab6168036d2a6cac409f0c6 --json -i=false
```

CLI 支持在運行中的容器執行命令；確認該容器工作目錄、脚本存在、DB／volume 身份及所有寫入已暫停後，備份命令可寫為：

```powershell
zeabur.cmd service exec --id 6ab61834a4c05a5bcb57ad69 --env-id 6ab6168036d2a6cac409f0c6 -i=false -- python scripts/backup_restore.py backup --uploads /data/uploads --file /tmp/workspace-20260927.zip
```

此命令尚未執行，也不能單獨保證安全備份。`docs/DEPLOYMENT.md:94` 明定先暫停全部前景／背景寫入；工具不自行暫停服務，DB 快照與附件讀取不在同一原子交易內。現有 supervisor 會因子程序退出而停止服務，不能直接殺掉 worker／web 當作已驗證的維護模式。尚需核實受控維護容器或平台維護方式、備份下載到受保護位置的傳輸方式，以及空白隔離 DB／附件目錄的還原驗證。`zeabur file pull` 只下載已上傳的專案來源，並非容器 `/tmp` 或 volume 的備份下載工具。

`backup_restore.py` 的應用備份保存五張資料表及附件、驗證 SHA-256，不還原登入 session；它不是 PostgreSQL 全叢集備份。`backup_schedule.py` 已打包，但目前 supervisor 僅啟動 web／worker，不能宣稱每日備份已排程。既有雲端重新部署保留資料測試亦不等於異地備份還原完成。發布語法已確認，正式一致備份的前置條件及傳輸／還原鏈仍未實測。

後續同日獲授權的正式容器唯讀實測：`zeabur service exec` 已成功。工作目錄為 `/app`，`scripts/backup_restore.py` 與 `/data/uploads` 存在；`scripts/run_service.py`、`scripts/run_worker.py`、`scripts/backup_schedule.py` 均不存在，證明本機新版程序尚未出現在受查容器。掃描該容器 `backend/` 與 `scripts/` 共 6 個 Python 檔案，未找到 `maintenance/read_only/write_block/quiesce` 關鍵字；本機同類搜尋亦未找到停寫實作。此搜尋不能證明平台沒有維護功能，僅表明尚未發現可直接使用的應用停寫機制。命令只回傳目錄、檔案存在性及搜尋中繼資料，未讀取環境秘密；未執行備份、停服務或部署。後續可用既有遠端 exec 路徑執行備份，但仍須先核實完整停寫、保護備份傳輸及還原驗證；正式舊腳本的備份格式亦尚未核實，不可直接視為本機新版五表格式。

### 在線引用附件快照的後續程式核對

追加唯讀確認舊容器：PID 1 為單一 `uvicorn backend.app:app`；舊 `backup_restore.py` 使用 `yx-workspace-backup/1`，保存 workspaces、receipts、source_caches 三表，在同一 PostgreSQL `REPEATABLE READ` 交易中查詢，DB 快照一致。舊附件程式 `app.py:192–204` 以獨立 id 建立新路徑、`open('xb')` 禁止覆寫，完整寫完並關閉檔案後才把附件引用加入 workspace 並提交 DB。掃描所有 backend 程式僅找到 `app.py:206` 在上傳例外時刪除該次 target，未找到既有附件的一般覆寫／刪除 API。

因此可採用**新的受控在線備份程序**：先取上述三表的一致快照，再依快照中各 workspace 的 `projects[].files[]`、`storage='local'`、附件 id，推導 `sha256(workspace_id)/file_id`，只複製該快照引用的完成附件。逐檔驗證存在、非 symlink、路徑位於 uploads 內、大小符合快照 metadata，將內容雜湊寫入 manifest；缺檔或大小不符必須中止，不產出可接受的成功結果。這可避免舊腳本全目錄遍歷把尚在寫入或失敗清理中的孤兒檔混入備份。備份完成後仍須驗 ZIP 清單／雜湊、受保護傳輸及空白隔離還原。

這項可行性僅針對已檢視舊版的引用附件規則，不是舊備份命令已可無條件在線執行。DB commit 結果不明後，上傳例外 cleanup 仍可能刪除已提交引用檔案，因此備份必須在發現缺檔時失敗；不得忽略引用完整性。未測試的新版本也不可直接沿用此判斷。未執行 freeze 或備份。[Zeabur 官方健康檢查文件](https://zeabur.com/docs/en-US/operations/monitoring/health-checks) 說明就緒檢查及有 volume 時使用 Recreate 部署，但沒有提供「暫停 PID 1 不會被回收」的保證，因此不採 SIGSTOP 方案。

後續已獲授權實作並執行上述受控在線方案：新增 `scripts/backup_live_legacy.py`，9 項測試通過，正式三表 15／1／1 筆及 1 個引用附件已取回。245,180-byte ZIP 經传輸雜湊核對，並在本機空白 SQLite／uploads 使用新版還原工具成功還原；逐筆資料和附件雜湊全部相符。沒有停機、正式 DB 寫入或部署。詳見 [CLOUD_BACKUP_EVIDENCE_20260927.md](CLOUD_BACKUP_EVIDENCE_20260927.md)。此結果更新前文「尚未取回／本機還原」狀態，但尚不代表另一個雲端 PostgreSQL 災难復原或每日備份排程已驗收。
