# 正式 rollout 審查（2026-09-30）

## 結論與可直接使用的候選版本

9/30 修正可進入「正式部署前檢查」，目前尚不能把 staging 當成正式。`.runtime/zeabur-stage-cd67bd7b` 的 118 檔 frozen manifest 與當時來源核對吻合，其隔離 smoke 回執 `ok=true`。**本次審查後主線又新增 OAuth、Input CAS 與前端修正，因此現在 frozen stage 不等於最新來源。** 正式發布前須為最終來源重新測試、凍結並驗收新 stage；下方 cd67bd7b 僅是先前可重現的候選基準，不能拿它宣稱包含最新修正。

正式目標僅：project `6ab61680a4c05a5bcb57ace9`，environment `6ab6168036d2a6cac409f0c6`，app `6ab61834a4c05a5bcb57ad69`。正式 PG 不換、不使用 staging／restore PG。

本次為只讀審查：未部署、未修改正式資料、未更新任何雲端環境。工作區及兩層上層未發現 AGENTS.md。

## 已取得的正式資料證據

正式快照 `.runtime/workbench-snapshot/receipt.json`：2026-09-30 13:22:11 UTC，1,683,523 bytes，SHA256 `ef6e2f8ffd1c248156ce75e2d2435aa7cb26ade32da450f90dda4d26ddf5907b`。`cloud-restore/restore-verified.json` 同 SHA，獨立 PG `6abce665454b8f31a5efc37e` 資料列與附件比對均 true，沒有跑 retention。此為已成功還原，不再列作未完成；不代表定時備份已啟用，也不能復原此時間之後的新增資料。

從該備份直接讀取而未接觸正式 DB 的統計：

| 內容 | 核實結果 | 發布含意 |
|---|---|---|
| workspace | 37 個，全部 storage_schema=2；35 demo、1 production、1 test | 無須把舊 root JSON 全量再遷移一次；不刪 demo 歷史 |
| production 案件 | 289 案，全部 case_visibility 缺值、execution_system=pending | 9/30 新 projection 將全部隱藏；這符合「舊案不進來」，但公司入口會暫時空白，不能說串接掉資料 |
| 新舊案 baseline | 不存在 | 正式建立一次基準仍是必要步驟；不能拿舊 staging 基準替代 |
| production SOP | 289 案均 2026-09-28.1 | 不需要批次改寫這批即將排除的舊案；保留歷史，不靜默套新版 |
| production 審批 | approvals/financial_requests/node_skip 無實例、native attempted=0 | 快照當時沒有需遷移的業務原生審批；部署前仍須 fresh 核對。QA 是獨立驗收，不應當公司案件 |
| 來源同步 | ready，sync_revision=462；source/directory connection enabled | 新容器 worker 一啟動就會同步；部署前核查 volume 與公司 namespace，不能假定 worker 不會跑 |
| 本地附件 | 共 2 件，分屬 demo/test；皆無 committed sha256 | 不得聲稱舊附件原始承諾雜湊已核實；本次快照/restore bytes 一致。無 production 本地附件需回填 hash 的證據 |

## 執行順序與具體 gate

1. **先做唯讀 runtime／volume preflight，不先部署碰運氣。** `Dockerfile:15` 建立 UID/GID 10001，`:17` 以該 UID 執行；舊持久卷掛載會遮住 image 內 chown。透過正式 service exec 僅讀 `/proc/self/mountinfo`、`/data/uploads` 及既有子目錄的 owner/mode、可用空間，核查 UID 10001 可 traverse/read/write。`.runtime/workbench-snapshot` 只證實存在／無 symlink，不證明新 UID 可寫。若不符，先保留 owner/mode 清單，再用限定正式 uploads 卷的維修步驟調整；不得對 `/data` 或主機任意遞迴 chown。沒有權限回執就不換 nonroot image。
2. **取 fresh 正式環境完整 map，僅讀先比對。** 保持 PostgreSQL DSN、SESSION_SECRET、UPLOAD_DIR、PUBLIC_ORIGIN 與專用 Lark app 不變。必須保留 `DEMO_MODE=false`、`ALLOW_CLOUD_DEMO=false`、`FEATURE_LEARNING=false`、`LARK_NATIVE_APPROVAL_SUBMIT_ENABLED=false`；補設定也要完整 map 合併＋readback，不能局部替換。`release_env_guard.py:7` 只檢查必要鍵，沒有保證讀到的是最新環境，不能用一份 9/29 saved JSON 直接套。
3. **核對 jekai grant 的 scope。** `business_policy.py:2,34` 新版僅承認 `company:ordinary_business_backup`；原授權若只有 enabled/manager 而無 scopes，登入／系統管理仍可用但不再有普通業務備援。fresh map 中精確既有 grant 加此核定 scope，保留 app/open_id/tenant/grant_id 原值；不改 coworkers 角色，不把 jekai 塞入固定流程。
4. **發布前檢查資料增量與回復點。** 快照在 13:22 UTC，需 fresh 確認之後有無業務寫入、未解決原生 attempted、worker job 未知結果。若有異動，先取得新的可核實快照或明確維護窗口，不能把舊備份稱為零損失回復。只新增 source/directory 心跳也需記錄，但不必把它誤算為人工交付。
5. **部署既有 frozen stage。** 先再次核實 manifest 路徑及每檔 SHA；在 `.runtime/zeabur-stage-cd67bd7b` 為 cwd 執行：`zeabur.cmd deploy --project-id 6ab61680a4c05a5bcb57ace9 --environment-id 6ab6168036d2a6cac409f0c6 --service-id 6ab61834a4c05a5bcb57ad69 --interactive=false`。保存 deployment ID；不執行 service create、DB restore、重設資料。此文件沒有實際執行此命令。
6. **部署後立即 runtime 驗收。** 看 RUNNING 之外，逐一核對 frozen backend/helper SHA、frontend JS/CSS bytes、web＋worker 子進程、實際 UID、uploads 持久卷。匿名 session 必須 user:null/mode:lark，workspace/projects/sources 必須 401；OAuth redirect 必須固定 app `cli_aa3cab98b2789e17`。正式舊 demo cookie 必須 401（新增 test_demo_disable_cutover 已有本地回歸）。目前 `scripts/deploy_verify.py before/after` 會用 demo 寫入，不適用這次正式驗收，禁止為跑它重新開 demo。
7. **一次性建立正式來源 baseline。** 需本人已驗證且 manager 的正式登入；先完成一次完整 V4＋報價表同步，立即 GET 最新 workspace/version/source_status.sync_revision，再送 `POST /api/sources/cutover-baseline`，body 只有 `{version:<最新正整數>,sync_revision:<最新正整數>,reason:<公司切換核定紀錄>}`。不直接改 DB。`app.py` endpoint 與 `source_case_policy.py:40` 已驗證正式環境、完整快照、sync revision、cache timestamp、一回性。409 先刷新核對，不能自增版本盲送。若 result lost，先 GET baseline_status，active 就不能再建。
8. **切換效果核對。** 這批 289 舊案應全不出現在案件／搜尋／待辦／摘要／來源 API；保留私有 recovery/audit。baseline 之後來源 native created_time 晚於 cutoff、且不連到舊案的紀錄才可自動成新案。同一案報價更新應更新，不應重開。尚未有真新案時顯示空清單是正確結果，不能為 demo 匯入假資料。新案 `sources.py:163` 使用新版 template；被排除舊案不批次 sop_apply。若有經核實已可見的新案保留舊 SOP，另走 sop_request → sop_apply 稽核，已完成紀錄保留。
9. **正常角色准入与監控。** 在職 coworkers 的 fresh 名冊＋各自登入與真實操作另驗；管理員能進不等於全公司准入完成。原生審批 submit 仍 false，直到 QA distinct-human 核准真實回查。記錄本 deployment 起點後開始 24h 觀測，不沿用 staging uptime。

## 定時備份與資料遷移的界線

`run_service.py:114` 只有 BACKUP_DIR 存在才啟動 backup 子程序；Docker 建 `/data/backups` 不等於 Zeabur 已掛持久卷。定時 backup 需另驗備份卷 UID 10001、容量、本機 retention、獨立 app 設定與告警；加密金鑰尚未公司另存不阻止上述技術部署／准入／baseline 準備，但不能把長期營運交接寫成完成。

`backend/app.py:79` import 時 create_all，`:83` 僅 storage_schema!=2 才舊 schema 遷移。快照 37 個都為 2，這次不需要手寫 SQL 全量搬資料。新版對 source visibility、SOP 候選、company grant 是業務層版本規則，不能把 rollback 理解為「換回舊 image 就所有資料語意不變」。baseline 建立之後若回退 9/29 projection，旧案可能重新可見；此時應先暫停入口並使用相容修補或審核過的回復流程，不能直接 redeploy 舊 image 給同事繼續用。

## 目前真正未核實的發布阻擋

- 正式持久 uploads 卷對 UID 10001 可寫、權限可逆修復證據尚未找到；這是換新版 image 前實際 gate。
- 尚未取得 fresh 全量 env 比對／grant scopes 及 snapshot 後業務增量的本輪回執；不能以舊 saved response 代替。
- 正式 baseline 尚未建立；目前 frontend 沒有 cutover-baseline 的操作頁（全 src 搜尋無入口），需要受控已登入 API 操作及回執，不能期待同事自行點完。
- `EXECUTION_TRACKER` 最後兩節有大量 `?` 文字損毀且較早「備份仍未驗」已被後續回執取代；接手必須以本文件引用的 JSON 回執為準，文件需主線修正文案。

以上未把獨立 staging、QA 送出或已成功 restore 冒充正式 rollout 完成。

## 正式 volume 最新實测（2026-09-30 14:18:29 UTC）

已執行固定正式 service 的唯讀 exec；安全回執 `.runtime/formal-volume-preflight.json`，工具 `scripts/formal_volume_preflight.py`。之前兩次 probe 因內嵌子程式縮排失敗，不作為 volume 證據；第三次成功取得以下結果，沒有修改正式檔案或權限。

- 正式舊容器為 UID/GID 0。
- `/` 與 `/data` 都是 root:root 0755，UID 10001 可遍歷。
- `/data/uploads` 是獨立 ext4 掛載、read_only=false、root:root 0777，剩餘 39,475,433,472 bytes。
- 共 2 個子目錄（root:root 0755）、2 份檔案（root:root 0644），無 symlink，掃描未截斷。
- 以真的 UID/GID 10001 子進程 `os.access` 核實：uploads 根可讀寫遍歷，但 2 子目錄不可寫；檔案均可讀。`uid_10001_uploads_ready=false`。

因此新 UID 可在 uploads 根建立新 namespace，也可讀舊附件；**既有兩個 namespace 後續上傳會失敗**。快照顯示它們為 demo／test，沒有 production 本地附件，但 test 工作區仍可能使用，不能稱全部權限已妥當。最低修法是在確認仍是本次那兩個非 symlink 子目錄後，只變更它們的 owner/group 給 10001（保留 0755，既有附件讀權可保留 0644）；保存原 metadata 以供回復，然後重跑同一唯讀 probe。要同時收斂 uploads 根的 0777 可另將 owner 設 10001 並收成 0750，但這是獨立寫入維修操作，本次未執行，勿為方便對任意 /data 遞迴 chown。

## 權限 gate 已完成修復與複驗（2026-09-30 14:21:57 UTC）

經固定目標工具 `scripts/formal_upload_permissions.py` 的 plan／apply 與正常 escalation 執行完成；工具 5 項本地測試先通過。唯讀 plan 精準核對根目錄＋2子目錄＋2檔案共5 entries，原 manifest SHA256 `c8401d9dda1a2e7d5a0557550b115158a0c520b58f7bf01655ff680d645cb56d`。

apply 在更動之前，以 exclusive 檔案保存完整原 owner/mode/inode/device 清單與 attempt；僅更動這5 entries，10001:10001、目錄0750、檔案0640，uploads根最後收緊。結果 SHA256 `67d1024dad18b4d8d162154030390decd0f58d7bea33cf3e17eef0491eaa571d`。可逆原清單保存在 `.runtime/formal-upload-permissions/plan.json` 及舊容器 `/tmp/yx-uploads-permission-repair-20260930/original.json`；容器替換後仍以本地原清單保留復原資訊。

獨立 `formal_volume_preflight.py` 複驗：實際降權 UID/GID10001 後可讀寫遍歷全部目錄，blocked_directories=0、unreadable_files=0、無symlink，uploads維持獨立ext4可寫卷，free38,838,091,776 bytes。`uid_10001_uploads_ready=true`。這項 gate 已解除，先前「尚未核實權限」段落是歷史狀態；未修改正式DB、未部署新映像，其他 rollout gate 仍獨立存在。

## Fresh 正式資料增量（2026-09-30 14:24:43 UTC）

固定 service 的 `scripts/formal_data_delta.py` 使用 PostgreSQL `REPEATABLE READ`＋`SET TRANSACTION READ ONLY`；沒有 import app／create_all／migration，沒有寫DB。完整最小安全回執 `.runtime/formal-data-delta.json` 只含集合／欄位雜湊與計數，不含人名、案名、金額或附件內容。工具2項本地測試通過。

相較 13:22:11 快照：production action_audit 14筆整體hash完全相同，附件內容hash完全相同，approval_count=0、native_attempted=0。新增事件只有 source_sync／people_directory_sync／attendance_identity_sync／attendance_schedule_sync 各10，以及 case_execution_initialize 1；沒有工作台人工送件的新稽核證據。

但不是純心跳：案件289→290、來源報價292→293、節點2601→2610、任務6532→6555；contract_items仍511筆，但來源金額／工項名稱／歷史欄雜湊改變。992筆班表只有source_verified_at／updated_at變動。結論是**沒有觀察到新增工作台人工交付，但有真實來源業務更新**；不能把13:22快照称為最新回復點。建議主線正式部署之前另取得新只讀快照保存這批來源新案與歷史，不需因此重複已成功的完整加密還原驗收。後續 baseline 仍以真正切換當時完整來源快照為準。

## 新正式發布前復原點已建立（2026-09-30 14:27:05 UTC）

新入口 `scripts/workbench_release_snapshot.py` 固定 purpose=`formal-release-20260930`、獨立 `.runtime/workbench-release-snapshot`。未覆蓋／刪除原已還原驗收的13:22快照；3項本地測試通過後，逐步escalation執行diag、reviewed-helper快照及下載。只在新私有/tmp內使用已審helper，不改正式/app，不寫正式DB。

新 snapshot SHA256 `c5ef716191458365f45db372464a034d9bb89f80426e5b21bcbd6a1999bf3091`，1,701,577 bytes，回執 `.runtime/workbench-release-snapshot/receipt.json`。READ ONLY REPEATABLE READ：37workspaces、5receipts、2source_caches、25,570business_records、128company_people、33action_audit、2附件。相較13:22審核多1筆，動作僅login，沒有新的交付稽核證據。

這是新的本地完整復原點，已SHA與archive manifest核實；未把它宣稱為再次完成還原驗收或新異地上傳。已驗收的offsite restore仍對應13:22版。正式新stage f6eb1998應使用此新回復點作發布前紀錄；部署與baseline仍由主線獨立執行。

## 正式 deployment 與背景健康已核實（2026-09-30 14:40 UTC）

主線部署後，本代理只讀查詢固定正式 deployment `6abd1efe9fbfb7e88417462c`：created14:38:54 UTC，build finished14:40:03，14:40:44 查得 RUNNING。這取代文件前段「尚未部署」的歷史狀態；檔案SHA／UID與OAuth由主線另驗，不能只憑RUNNING推定通過。

14:40:50只讀DB聚合：worker status=ok、stage=cycle_complete、last_success14:40:26 UTC。正式1個workspace；290projects、2610nodes、6555tasks仍保留，source/directory connection仍enabled。baseline不存在（baseline_required），原案持久資料仍visibility缺值／execution pending，當時source新一輪尚未到期；這不代表新版projection會把它們公開。source成功時間22:38:18+08、revision475、ready但mapping review_required；名冊成功22:39:29+08、revision476、review_required，不把需核對名冊稱為全員已准入。

安全回執 `.runtime/formal-rollout-status.json`、`.runtime/formal-rollout-health.json`。工具 `scripts/formal_rollout_status.py status|health`，3項測試通過，不寫資料／不做migration。正式baseline仍須主線以已核實登入與完整新來源快照核定。
