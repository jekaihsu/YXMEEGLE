# 專案工作台最新交接入口

> 2026-10-03 新版入口：[圖文交接](guide/handoff.md)、[使用說明](guide/user-manual.md)、[深入審查與更新清單](guide/code-review.md)。本頁以下為 9/30–10/01 歷史回執；舊移轉日報已由業主裁示免核對，不列上線門檻。歷史同號案件另請雅雯核對。本輪文件更新不代表業務修正已部署。

## 最新核定（優先於下方歷史部署紀錄）

2026-09-30 使用者已核定：**V4＋Lark 報價總表全部案件都要顯示，包含已結案**。先前「尚待 baseline」「切換前來源案全部排除」的要求已被取代，不再是待核准或上線門檻。公開 baseline 入口已在程式退役，驗證登入／正式工作區／管理員後回應 410，不修改資料。

公司駕駛艙供全公司已准入同事使用，**不是僅限 manager**；仍維持公司租戶、在職名冊及各動作角色權限。來源可見與業務執行分開：權威來源確證後可見，既有歸屬保留，新影子案預設待核定，不自動授予執行或核准權限。

**10/01 00:09 台灣更新：已部署 `zeabur-stage-35faeb15`，正式 deployment `6abd3252c997a72fa17492b7`。** 七個關鍵檔案與測試站同版；真實同步 9 表／2605 筆，290 筆案件恢復可見，駕駛艙 API、分頁、桌面／手機真實畫面通過。來源關聯仍 review_required，不宣稱跨表工程已全部去重。一般公司 member 存取由 HTTP 測試證實，真實普通同事本人 OAuth 仍未驗收。

本輪發布／測試／限制詳見 [全公司駕駛艙發布紀錄](COMPANY_COCKPIT_RELEASE_20261001.md) 及 [最新來源決策](SOURCE_VISIBILITY_DECISION_20260930.md)。以下截至 14:53 UTC（台灣 22:53）的部署回執屬先前版本歷史。

## 已完成且有證據

| 項目 | 核實結果與限制 | 回執 |
|---|---|---|
| 全後端本機回歸 | 1347 passed，222.47 秒；不等同雲端全部串接驗收 | `.runtime/pytest-20260930-final-release.log`（UTF-16） |
| 加密異地往返 | 獨立備份 app 上傳密文、下載遠端密文、本機解密 hash 一致；未執行遠端 retention | `.runtime/workbench-backup-roundtrip/roundtrip-receipt.json` |
| 獨立 PostgreSQL 還原 | 來源 SHA `ef6e2f8ffd1c248156ce75e2d2435aa7cb26ade32da450f90dda4d26ddf5907b`；`postgresql_rows_equal=true`、`attachments_equal=true`、`downloaded_ciphertext_only=true` | `.runtime/cloud-restore/restore-verified.json` |
| 新鮮發布前快照 | 14:27:05 UTC，正式服務快照 SHA `c5ef716191458365f45db372464a034d9bb89f80426e5b21bcbd6a1999bf3091`；與前項已還原快照不同，不混稱同一份 | `.runtime/workbench-release-snapshot/receipt.json` |
| 正式附件 volume | 14:21:57 UTC，獨立 ext4 `/data/uploads`，UID/GID 10001 可讀寫及遍歷；0 blocked directories、0 unreadable files | `.runtime/formal-volume-preflight.json` |
| jekai 核定備用 scope | 14:22:02 UTC，只補精確既有公司 grant scope，完整 env map 讀回相符；native submit、DB 與秘密未變 | `.runtime/company-grant-scope/verified.json` |
| jekai 實際工作台 session | 最新版重新 OAuth 後，直接進正式 lark namespace；session 200、帳號相符、manager、workspace 200。只證明此管理帳號，不是普通同事本人驗收 | `.runtime/workbench-lark-company-session-check.txt` |
| 正式新版 | 最終 `zeabur-stage-c370d195`、deployment `6abd215dc997a72fa1748eba`，14:50:04 UTC 完成切換；14:50:41 六個關鍵檔案 SHA 相同、三個服務程序實際 UID 10001 | `.runtime/formal-rollout-status.json`、`.runtime/release-source-formal-c370d195.json` |
| Lark 公司可用範圍 | 專用 app 0.4.3 已發布，14:38:21 UTC 真實 UI 核實為「所有员工」；不把舊版部分成員設定誤當最新狀態 | `.runtime/company-app-availability-verified.json` |
| 正式來源讀取（歷史版本） | 當時 HTTP200、9 表、2605 筆、全部 ready、baseline_required；最新核定已取消此門檻，待新版同步驗收 | `.runtime/workbench-lark-company-source-refresh.txt` |
| 正式畫面（歷史版本） | 當時 workspace 200、0 可見案件，290 案仍在 DB；這是已被取代的 baseline 顯示限制，不是目前要求的正常結果 | `.runtime/workbench-lark-company-release-ui.txt` |

最終正式及 staging 抽查 app、integration_routes、source_sync、source_case_policy、production_access、run_service 六檔，不宣稱所有檔案逐一遠端核對。先前 UID 0 問題已補啟動降權，正式 supervisor／web／worker 都真實核實為 UID 10001。

## 本輪程式修正

- 普通同事 OAuth callback 直接查 900 秒名冊新鮮度，過期／未來／錯誤時間不建立 session；bootstrap 維修入口保留。相關 82 項測試通過，見 [同事登入核對](COWORKER_LOGIN_REVIEW_20260930.md)。
- 後續真實驗收抓到舊 manager profile 預設測試區；已修成所有新 OAuth 登入直接進正式區，新 profile 的 default_workspace=production。明確切換與測試資料保留；41 項相關測試通過，並完成 jekai 重新 OAuth 真實驗證。
- 雲端啟動時若 Linux 正式環境仍為 root，先清除補充群組並降 UID/GID 10001；失敗即停止，不以 root 啟動服務。該修正後服務／降權／包驗證 16 項通過。1347 全套是這兩項小修之前，後續使用上述針對性回歸，不混稱最後版本再跑過全套。
- 歷史修正曾採無 baseline 僅保存 cache；**已被最新全部來源顯示決策取代**。目前程式完整匯入核定來源，依真實三元組確證可見，保留去重、成果歷史與完整來源刪除判定。
- Input 的正式／隔離目的地、只追加與未知結果不重送等受完整本機回歸覆蓋；本頁沒有新增宣稱這輪再次完成正式 Input 真實寫入。
- 正式部署設定產生器預設 Demo=false；讀舊設定也不會在 prepare_lark 恢復 Demo。相關 12 項測試通過。
- 名冊健康獨立依來源成功讀取時間判斷，10 分鐘預警，超過 15 分鐘異常；worker 心跳不能代替名冊成功。名冊健康測試 26 項通過。
- 舊佇列摘要缺來源 ID 或包含旧案時停止外送；每個 HTTP 邊界重新核對來源，相關 worker／isolated／operations 110 項測試通過。

以上子集合彼此可能重疊，不能相加當作獨立總測試數。

## 尚未完成，不得標為全公司已驗收

1. **帳號使用範圍已核定，無須補鄭光瑞。** 使用者最新回覆「他不用，只要有 LARK 帳號的人才可以使用」。鄭光瑞不列為上線缺口，不要求補帳號關聯；另外 5 筆無帳號且離職資料也不納入使用者。維持公司租戶、在職名冊與既有角色檢核，不因持有任意 Lark 帳號而授予存取。其他具帳號同事仍待本人登入驗收。
2. **原生審批真人兩席。** QA instance `2D9E52F7-298A-4FE2-A1CF-C9403B5B551E` 最新主線狀態為 PENDING、binding_verified=true；仍需兩位指定本人核准及讀回結果。禁止代按，正式送件保持關閉，不能把 QA 狀態套用業務案件。
3. **普通同事本人 OAuth。** jekai 的 200 session 不足以證明一般 member 登入、正確案件權限與本人交付可用。
4. **密鑰另處保管與常態排程。** `custody_confirmed=false`，備份排程未啟用；目前 key 的本機私有保存不等於公司完成獨立保管。一次加密還原成功不等於常態備份已運作。
5. **全部来源顯示與公司駕駛艙新版驗收。** 不再建立 baseline；待主線記錄新版部署、完整回歸、正式同步後案件可見數與全公司准入同事的駕駛艙瀏覽器結果。
6. **正式同版 24 小時觀測與維运交接。** 同事／主管流程驗收、告警與備份責任仍需留具體結果。

背景健康補充：一次 source／HTTPException 使 worker 降級；沒有 people／attendance／jobs 錯誤。其後 14:48:09 UTC 已成功循環，source ready、directory 成功但 review_required。名冊缺帳號的 6 筆已依最新使用範圍排除，不因這個來源品質標記要求補齊或阻擋其他有效帳號；目前准入檢核本來即逐人執行。手動與排程同步競爭 409 是程式與時間線支持的推論，沒有捕獲該次 HTTP 狀態碼，不能寫成已確證原因。沒有為此重啟或放寬同步檢核。

## 繼續工作時先做

先讀本頁及列出的最新安全回執，確認目前雲端版本再動作；不重建既有備份 app、QA instance 或快照資源。未知遠端結果先查回，不重新送件。正式環境變更必須 fresh 完整 map 合併、再次比對與讀回；不要把舊設定檔整份覆蓋。薪資／能力 Base 保持禁止寫回。

本頁可分享的內容不含 token、DB URL、app secret 或金鑰。`.runtime` 指向私有證據，不應將整個資料夾交給一般同事或打包部署。
