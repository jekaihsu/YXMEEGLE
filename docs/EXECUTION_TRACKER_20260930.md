# 2026-09-30 公司工作台收尾

## 最高優先最新核定：全部 Lark 案件與全公司駕駛艙

使用者於 2026-09-30 明確核定：**V4＋Lark 報價總表全部案件顯示，包含已結案**。本決策取代先前 baseline／切換前案件全部排除規則，不再等待使用者核准 baseline。公開 baseline API 已在程式退役，經登入、正式區與管理員檢核後回應 410，不修改案件。

公司駕駛艙供全公司已准入同事使用，不是 manager-only。來源顯示不自動授予業務操作：既有執行歸屬保留，新來源影子案預設 pending；無權威來源確證的 Meegle 舊案不另行搬入。詳見 [來源決策](SOURCE_VISIBILITY_DECISION_20260930.md)。

**10/01 00:09 台灣：新版已部署及真實驗收。** 固定包 `35faeb15`、正式 deployment `6abd3252c997a72fa17492b7`；來源 9 表／2605 筆，290 筆 source_reference 可見，駕駛艙 API 與畫面一致、分頁／桌面／手機正常。來源 mapping_status 仍 review_required，不宣稱工程跨表去重全部完成。完整回歸及針對性修正結果、未完成事項見 [本輪發布紀錄](COMPANY_COCKPIT_RELEASE_20261001.md)。下方先前 0 案及 baseline 待辦僅為歷史。

使用者核定本對話 proposed_plan 並要求 Implement the plan。這份紀錄接續 9/29 實作，不重建系統。完成需分開記錄程式、測試、部署、真實驗收。

## 最新決策

- 工具供公司同事日常使用，不依賴 jekai 分派、確認或核准。
- jekai 另授全公司普通業務備用權限，保留系統管理，不進固定流程；重大雙人審批仍需不同本人。
- V4 與報價總表全部權威來源案件均顯示，包含已結案；不按建立時間排除。Meegle 來源不另抓取搬入，來源顯示與正式執行准入分開。
- 日報自動關聯作參考，完成條件依 SOP 必交成果，不一律要求日報；照片依適用 SOP。
- V4＋Lark 報價總表，薪資／能力 Base 禁寫，訓練考評關閉。普通 SOP 本地，財務／變更／展延／跳過 Lark 原生。

## 本輪分工

| 範圍 | 主責 | 完成標準 |
|---|---|---|
| SOP／角色／範本效能 | workflow_completion | #221/222/223/181/175/47/1-d，必要回歸及實際接口 |
| 安全／輸入／通知／資料投影 | security_gap_review | #141-147/#7/#213，型別及權限反例 |
| 備份／依賴／執行映像 | backup_completion | #203-207/171，未知結果恢復、獨立憑證、還原驗收 |
| 審批／來源分流／API整合／UI／部署 | root | 修孤兒審批、舊案排除、API接線、獨立環境及真實驗收 |

## 最新核實進度（2026-09-30，登入入口切換後）

- 完整後端回歸：`1245 passed in 214.83s`，回執 `.runtime/pytest-20260930-release.log`。其後新增「同 DB／同密鑰，停用 Demo 後拒絕舊 Demo cookie」獨立 HTTP 測試，1 passed；不是再跑一次全套的聲稱。
- 前端建置通過。Stage `zeabur-stage-cd67bd7b` 共 118 檔，隔離 import/API smoke 通過。雲端 JavaScript `index-BQ5-l7iM.js`、CSS `index-Bj1srCLy.css` 與本地 bytes SHA256 相同。
- 新版已部署至獨立 staging 服務 `6abc0821454b8f31a5ef614a`，獨立 PostgreSQL `6abc081caa61051740e67fbd`。2026-09-30 05:58 UTC 完成 8 項線上檢查；這批最初的示範驗收已結束，不作為公司入口。
- 使用者最新明確要求：**不得一進站就是 Demo，要供公司實際使用。** 已在正式與 staging 最新完整環境 map 僅修改 `DEMO_MODE=false`、`ALLOW_CLOUD_DEMO=false`，各保留 32／15 個設定鍵；原映像 restart 後再次核實，不是只改檔。
- 06:16 UTC 正式入口核實：匿名 session `user:null`、mode `lark`、workspace/projects 401；OAuth 指向專用 app `cli_aa3cab98b2789e17` 及正確 callback。staging 同樣停止匿名 Demo。正式網址為 https://yongxiang-projects-20260925.zeabur.app 。
- 實際瀏覽器已切至正式登入頁，確認「使用 Lark 登入」存在、DEMO 不存在。截圖 `output/playwright/company-login-20260930.png`。這只證明入口，不代表同事真人登入與送審驗收完成。
- 正式服務程式仍是 9/29 已部署版；9/30 新修正目前在 staging。此次正式異動僅登入模式與原映像 restart，未刪除資料、未重設權限或取代資料庫。
- 已重新啟用多 Agent 並完成交叉檢查：案件 CAS 擴充、舊 SOP 任務明確遷移、Input 分頁嚴格驗證／只追加、Drive 未知結果不重傳、舊案摘要停止外送、名冊 freshness 預警均有新增反例測試。
- Apple Design 靜態複查：`APPLE_DESIGN_STATIC_REVIEW_20260930.md`。Root 另實測 staging 桌機 1440 與手機 390 首頁／案件頁，皆無水平溢出；首頁無 pageerror、案件頁 Tab 可到按鈕。這不是完整輔助科技或真人審批驗收。
- 已建立獨立 Lark 備份 app **cli_aa361fea3678de13**（詠翔工作台備份）。尚待最小 scope、發布、備份資料夾 ACL 與加密往返驗收；不可宣稱備份啟用。官方最小 scope 證據見 `BACKUP_LARK_MINIMUM_SCOPES_20260930.md`。

## 仍待完成（不能作為已可全公司切換的證據）

- 專用驗收審批定義、真人共同審批結果、同事本人 OAuth／名冊准入；正式送審仍不得因 UI 可見即假定可用。
- 備份 app 最小權限＋目的地 ACL、公司金鑰分離保管、持久卷 UID 10001 權限、獨立空 PostgreSQL 加密還原與附件比對。
- 全部 Lark 來源顯示與全公司駕駛艙最新版本部署及真實驗收；不再建立 baseline，不靜默套用 SOP 或授予執行權限。
- 原生審批與 Input REST 仍保留全域 CAS；已改善的案件 actions 不代表所有背景衝突都消除。
- 同一正式部署 24 小時觀測、告警交接及備份維運責任。

## 歷史基準與阻擋（當時狀態）

- 9/29 20:35 已有 deployment `6abbadeeb57ea4921d62d510`、bundle `D_PdAUvj/Bj1srCLy` 的 12 項公開驗收回執；不代表此刻全部外部串接成功。
- 9/29 20:36 正常管理員唯讀核對四份原生審批定義 HTTP200；送審仍 disabled，真人核准未完成。
- 9/30 重跑 deployment staging 單測仍因 fixture 缺 sop_source_contracts.json 失敗，不得宣稱全套全綠。
- 本機 C 約 3 GiB，D 約 302 GiB 可用；不清理使用者其他資料。
- 正式切換前須完成安全／流程阻擋、同事本人 OAuth／核准、獨立加密備份還原與同部署24小時觀測。

## 執行規則

先修缺陷，再建隔離測試服務；正式更新前保留可回復快照。未知遠端結果先查回，不能新建ID盲重送。不得代登入或代核准。各代理人完成後互相審查不同模組。完整驗收回執未取得的項目保持未完成。

## 9/30 最新技術驗收（取代損壞的問號文字）

- 正式公司入口已停用 Demo；9/30 程式目前僅部署 staging，正式仍是 9/29 映像。正式最新入口核對時間 14:07 UTC，匿名受保護 API 拒絕存取，OAuth 指向公司應用。
- 獨立備份應用 cli_aa361fea3678de13 已發布 1.0.0，只開 drive:file:upload 與 drive:drive:readonly。完整資料夾協作者 UI 與應用讀取均已驗證，不使用不支援的資料夾 members API 作成功證據。
- 正式唯讀快照完成於 13:22:11 UTC，1,683,523 bytes；SHA256：ef6e2f8ffd1c248156ce75e2d2435aa7cb26ade32da450f90dda4d26ddf5907b。
- 快照含 workspaces 37、receipts 5、source_caches 2、business_records 25,494、company_people 128、action_audit 32，以及 2 份附件。登入 sessions 不還原；2 份歷史附件缺原始資料庫 SHA，不能宣稱歷史原始雜湊已核實。
- 已由獨立 Lark 應用上傳加密備份、下載遠端密文、解密核對快照雜湊，再還原至獨立空 PostgreSQL 6abce665454b8f31a5efc37e。資料列與附件逐一比對成功：postgresql_rows_equal=true、attachments_equal=true、downloaded_ciphertext_only=true。
- 未修改正式資料庫或 staging DATABASE_URL；還原服務僅私網可用。單次傳輸 RSA 私鑰已移除，備份還原金鑰仍保留。沒有執行遠端保留期刪除。
- 回執位於 .runtime/workbench-snapshot/receipt.json、.runtime/workbench-backup-roundtrip/roundtrip-receipt.json、.runtime/cloud-restore/restore-verified.json 與 transport-cleanup.json；回執不代表常態排程已啟用。
- 使用者已明確回覆「尚未另存，先繼續技術驗收」。保管人 jekai；custody_confirmed=false。常態備份排程保持關閉，其他技術工作繼續，不重問已回答事項。
- QA 定義 E1DEFC43-3E29-4238-AD9D-91ACF8E29091 已發布並核實 ACTIVE；測試使用同應用名冊解析出的兩個不同在職帳號，不新增正式業務角色。
- QA run qa-joint-20260930，instance 2D9E52F7-298A-4FE2-A1CF-C9403B5B551E 已成功送出；最後成功查回 PENDING 且 binding_verified=true。14:07 UTC 最新 poll 回報 remote_operation_unverified，不能以本機舊 pending 當作最新遠端結果；禁止重送或代真人核准，正在診斷。
- 當時發布檢核包含持久卷、來源 baseline、同事 OAuth 與共同審批；其中 baseline 已被頁首最新核定取消。其餘完成狀態應依最新交接回執，常態維運仍需獨立記錄金鑰保管及同版本觀測。
- C 槽僅清理可再生 pip/npm 快取，保留程式、瀏覽器工作階段、公司資料與金鑰；詳見 DISK_RECOVERY_20260930.md。

以上依已有技術回執重建，非重新執行驗收。舊章節記錄的是當時狀態，判斷目前進度以本節及後續紀錄為準。

## 9/30 續行：真實登入、發布前檢查與追加修正

- QA 查詢失敗已定位到受限環境的 token 連線 ConnectError；使用已核准外連後，token／definition／原 instance 皆 HTTP200/API0。原 run poll 已成功持久化 version 6，仍為 PENDING，binding_verified=true；未重送、未代核准。詳見 NATIVE_QA_HANDOFF_20260930.md。
- OAuth callback 已加入名冊 freshness 檢查，避免名冊過期仍先登入成功再被踢回；管理員復原模式保留。相关 OAuth／准入測試 82 passed。
- Input 提交及未知結果唯讀查回支援案件版本，後端案件身分取自 URL／既有 revision，不採任意 client 範圍。純背景同步不再造成 workspace 409，同案實質修改仍拒絕；52 項相關測試通過，交叉審查未見阻擋缺口。
- 正式設定產生器預設關閉 Demo，舊設定檔帶 Demo=true 時，接入公司 Lark 也強制關閉；缺憑證拒絕建立設定。12 項相關測試通過。
- 上述批次整合驗證 71 passed，部署包測試 2 passed；前端 build 成功。這些測試有重疊，不將各數字相加宣稱全套總數。
- stage f6eb1998（118 檔）已部署隔離 staging，14:23:26 UTC 八項線上檢查通過，JS index-DKmZ9zz1.js 與本機 bytes 相同。這不是正式部署，後續同步修正需重建套件。
- 正式 uploads 專用卷權限已保存原值後修復至 UID/GID 10001；目錄 0750、附件 0640。14:21:57 UTC 降權唯讀存取檢查 blocked_directories=0、unreadable_files=0。原權限回復資料保留在 .runtime/formal-upload-permissions。
- 14:22:02 UTC 僅補既有精確 jekai grant 的核定 company:ordinary_business_backup scope，fresh 完整環境讀回相同。未開啟原生送件、未更動資料庫或秘密；新 runtime 生效仍需部署。
- 正式資料增量：備份後案件 289→290、報價 292→293，工項也有來源更新；操作稽核與附件雜湊不變。正準備新的唯讀發布前快照，不能把 13:22 快照當作最新零損失回復點。
- 實際瀏覽器沿用使用者先前核准的 jekai 帳號與既有 scopes 完成 OAuth；公司 session HTTP200、mode=lark、logged_in=true、account_matches=true、role=manager，workspace HTTP200。這只證明 jekai，不能替代其他同事本人驗收。
- 歷史檢查曾發現無 baseline 空匯入會誤標來源 missing，當時暫緩部署。該時間點採用的舊案全部隱藏規則已被頁首最新核定取代，不再是現行要求。

## 最後候選版本驗證（14:34 UTC 更新）

- 歷史防護曾採無 baseline 僅更新完整快照與健康；現已改為全部核定來源匯入，完整快照與真實刪除判定保留，不再因缺 baseline 阻止案件顯示。
- source 相關必要測試 83 passed、延伸來源測試 80 passed；另一 Agent 交叉審查 34 passed。其後完整 backend 回歸 **1347 passed in 222.47s**，回執 `.runtime/pytest-20260930-final-release.log`；這些數字不相加。
- stage ab7633cf 已部署 staging；14:31:23 UTC 公開 API／資產 8 項檢查通過，14:32:40 UTC 五個關鍵後端檔案 SHA 全部相同。早先舊 hash 是部署尚未切換完成，沒有盲目重送同一版本。
- 仍發現雲端 run_service／web／worker 實際 UID 為 0，與 Docker USER 10001 設定不符；正在補啟動降權及驗收，因此 ab7633cf 尚未正式部署。
- 新的發布前唯讀快照已完成於 14:27:05 UTC，1,701,577 bytes，SHA256 c5ef716191458365f45db372464a034d9bb89f80426e5b21bcbd6a1999bf3091，存放 `.runtime/workbench-release-snapshot`。不覆蓋已完成加密還原的 13:22 版本；新的這份尚未另做異地上傳。快照新增稽核僅登入，沒有新增交付。

## 正式部署完成（14:53 UTC 最新接續點）

- 最終正式 package `zeabur-stage-c370d195`，deployment `6abd215dc997a72fa1748eba`，14:50:04 UTC RUNNING。六個關鍵檔案雜湊相同；supervisor／web／worker 實際 UID 10001，正式 Demo 仍關閉。
- 新增公司登入固定進正式 namespace 的修正已上線；不再被舊 manager default_workspace=test 導向測試。重新完成 jekai OAuth 並實測 formal_namespace=true、session/workspace HTTP200；其他同事本人登入仍待驗。
- 歷史版本正式來源實測 9 表／2605 筆／全部 ready；當時 baseline 限制造成清單 0 案，DB 290 案、2610 節點、6555 任務仍保留。最新核定已要求取消此限制，0 案不能再視為預期驗收結果。
- Lark 專用應用 0.4.3 最新已發布，可用範圍真實核實「所有员工」。名冊 6 筆缺帳號：5 離職＋1 在職「鄭光瑞」；已詢問其公司帳號狀況，未寫薪資 Base 或猜配。
- 一次 source HTTPException 導致 worker 降級，其後成功恢復；來源同步競爭屬推論，未捕获當次狀態碼。目錄最後同步成功，review_required 主要為上述帳號缺口，不能視為全部員工已驗收。
- 本輪最後部署只補 OAuth 預設區；41 項相關測試通過。啟動降權補丁另有 16 項服務／包測試通過。此前全 backend 1347 passed，不把不同批次結果混算。
- 最新交接入口：`docs/RELEASE_HANDOFF_20260930_LATEST.md`。待真人共同審批、普通同事本人驗收、全部來源顯示／駕駛艙新版驗收、金鑰另存／常態備份及同版 24 小時觀測。鄭光瑞帳號與 baseline 已由後續核定移出待辦。不要重建 QA、備份 app 或反覆部署相同 marker。

## 最新使用範圍決策

使用者回覆：「他不用，只要有 LARK 帳號的人才可以使用。」鄭光瑞不需補帳號，不再列為上線缺口。沒有公司 Lark 帳號的人員不納入工作台使用者；既有公司租戶、在職名冊、角色權限及特別核定公司管理帳號規則維持。現有程式已依帳號逐人核對，不需要為此放寬登入或修改薪資 Base。

接續待辦移除「鄭光瑞帳號確認」及已被最新政策取代的「正式 baseline」，保留具帳號同事本人驗收、真人共同審批、新版全部來源／駕駛艙驗收、金鑰分離保管／常態備份及同版本觀測。名冊 6 筆 missing_account 是來源資料狀態，不再當成需讓所有 69 列都能登入的要求。
