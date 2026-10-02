# 第二輪後端一致性與正式使用檢視

本輪先新增本機測試與審查紀錄，主線後續授權修復 S1–S6；已更新 importer、daily provenance、skip scope、唯讀查證撤權和完整來源表缺列保護。未改正式資料、未寫遠端、未改共用 app/workflow。使用者說明舊 535 筆日報來自舊系統搬遷；保留既有 0 配對／535 待配對的歷史匯入觀察，但不得以此推論新日報串接失敗。新日報鏈路另由 visual_redesign 依實際 schema 驗收。

## 可重現的新發現

測試檔 `backend/test_second_review.py`。下表為修復前實際重現，不是尚未修復清單。原四項 `xfail(strict=True)` 已全部移除，原斷言原樣保留並通過；新增來源刪除、上游部分未知、錯 table、成本換版、部分讀取不得判刪等回歸。最新相關測試 **120 passed in 13.75s**，含 visual_redesign 的 15 項新日報測試；正式部署及其他模組完整 suite 由主線執行。

| 編號與優先度 | 已實測行為 | 位置與修復方向 |
|---|---|---|
| S1，P1，影響資料可信度 | 日報同時連一個可解析確認單與一個未知確認單，仍被配到唯一已解析案。已重現 daily_imported=1，預期應待核對。 | `v4_sources.py` 的 daily/contract/reporting 候選建立只保留解析成功者。應保存全部原生關聯與 unresolved 清單；部分未知不可當唯一有效候選。表 ID／base ID 亦納入關聯身分，不依僅 record id。 |
| S2，P1，影響人工配對換版 | 已人工核准日報屬 A 案，之後上游合約原生連結改到 B 案，daily 自己欄值不變；舊 manual review 仍 approved，覆蓋新來源，保持 A 案。 | `operations.py daily_propose/daily_approve` 和 `v4_sources.py` 的 approved review 選取僅比 daily.source_fields。應綁 daily＋實際 traversed contract/reporting/confirmation/cost IDs 與映射相關快照 hash，依賴來源改動即失效，保留歷史。 |
| S3，P1，正式跳過開通前阻擋 | 核准跳過後，報價確認範圍改為新增原跳過工項，既有 waiver 仍 valid。現正式 skip 禁止，此重現僅 demo，不能描述成正式已被越權。 | `node_skip.snapshot` 包含本機 tasks/evidence/files，但沒有 quotes/source_records 或來源範圍版本；source refresh 未保證增加 project.revision。需核定／明確納入來源範圍 hash，至少 confirmation/quotes/contract/reporting，避免 timestamp 每同步造成無謂失效。 |
| S4，P1，授權撤銷競態 | 真 TestClient 路由中，開始查訓練映射時是 manager；遠端讀取途中同公司 PersonRow 降為 member/caps=[]，回應仍 200 並保存 verified mapping。 | `integration_routes.py /api/learning/mappings/verify` 使用初始 actor，只在 I/O 前驗權；`persist_mutation` 只複核 active。應在 token 後、每 HTTP 邊界及提交時重新檢查 actual current user 的 manage_sources 與同公司／app 設定，與 input verify 一致。未進行真外部写入。 |

## 修復與實際資料重播結果

- S1：`native_records` 查每個關聯的 base、table、record 及來源 kind；daily／reporting／contract 有任何原生關聯無法解析，整條來源不當成唯一配對。實際欄位 schema 的 linked_tables 同樣生效。明確新人工配對仍是獨立核對程序，不偽稱原生關聯完整。
- S2：每張日報 `source_provenance/source_version` 包含日報與穿透的 reporting、contract、confirmation、cost 來源快照及未知關聯。pending／approved review 依 hash 失效；舊版沒有 hash 的核對也需重核，歷史不刪。提交核對前再次比目前 hash。外業組長／組員原生帳號一併納入 `source_actor_ids`（S5），不以姓名授權。
- S3：skip 快照加入穩定排序的 quotes/source_records 和合同／填報工項 `source_scope_hash`，不採用 `source_changed_at` 或同步時間。來源欄位變更須重新核准，不能沿舊 waiver；現階段仍為保守完整來源範圍，若日後要排除無關欄位需逐欄核實。
- S4：訓練映射唯讀 verify 在 token 後、每 HTTP 邊界、讀回後及 commit 以目前 user 重新驗權，並檢查 app/worker公司設定未變。主線最新停用訓練政策 `FEATURE_LEARNING=False` 仍保留，正式端點 404；回歸僅在 test monkeypatch 打開以驗證撤權守衛，不恢復正式功能，不觸發能力回寫。
- S6：`import_sources(..., complete_tables=...)` 只有 `status=ready`、base/table/kind 明確、count 與本次該表列數相符的覆蓋表可判斷 absence。標記 `source_missing`、移出案件有效 daily_reports、保留原 fields／來源／原案件歷史至 daily_unmatched，失效 pending/approved 配對且禁止再採用。增量、部分、其他表、沒有覆蓋證據皆不判刪。重新出現可恢复來源日報，但不能復活舊核准。

S6 實際證據：visual_redesign 新增日報、修改、清理完成後的私有快照在本機連續重播。覆蓋是 **外業日報一張完整表**，其他表沿既有 cache；不冒稱九張全新讀取。來源 535 舊列未變，新測試日報 active 1→0，保留 source_missing 歷史 1，全部案件／任務 ID、狀態、output 不變，第二次重播歷史穩定。聚合 `.runtime/new-daily-deletion-fixed-20260927.json`，未再遠端寫入或讀寫正式 DB。

舊九表私有快照再次重播仍 15 formal＋266 intake、6545 任務；重播和本機報價內容更新不新開案、ID 穩定。535 舊日報仍 403 缺關聯＋132 未解析，原數字不掩蓋；此歷史資料的整體 checks_passed=false 不能當作新日報驗收失敗。聚合 `.runtime/source-replay-second-review-20260927.json`。

## 已有防護的實測結果

新增新日報本機測試：一張既有確認單＋一張 native link 日報連續匯入三次，案件／節點／任務 ID 與工作狀態完全不變，只保存一份日報；來源日報檢核已通過也不完成工作。只有日報、沒有確認單時不建立案件，日報保留待配對。

新增跨案件實際 HTTP 測試：同 workspace version 先在 A 案留言，再在 B 案留言，第二個請求回 409；重新讀取 version 後重試，兩案各保存一次，重播 request_id 也不重複。**這是全工作區 CAS 的安全衝突，不是資料遺失；但不同案件操作互相衝突是 P2 效能／協作改善。**目前没有 project-level CAS，不可對前端承諾 409 只刷新單案已可用。

本輪與相關 suite 合併執行曾得 **131 passed / 3 xfailed in 6.18s**（加入 S4 前）；S4 隨後單独 `--runxfail` 真實得到 200≠403，證明撤權缺口。相關 suites 是 source_identity、task_capabilities、node_skip、native_approval、people_directory；沒有遠端測試、沒有全專案測試。

- 多報價同案、確認單原生身分修正、案件代碼碰撞隔離、來源報價變更不新增案、來源 reporting 手工作業保護：`test_source_identity.py`；另有前次實際九表唯讀重播 ID 穩定聚合證據。
- 同人不能投兩席、同人兼任 PM／主管不能送、已完成／財務／封存不能跳過、成果仍需真正交付：`test_node_skip.py`。
- 停用負責人或代理人、過期／撤回／未知請假、未通過資格者不可執行；PM／manager 不自動擁有任務執行權：`test_task_capabilities.py`。
- 真實名冊四欄讀取 69 列、63 帳號，純本機重播保留停權和權限；管理員手動停權不被回職／同步恢復：`test_people_directory.py` 及 `.runtime/people-directory-verification-20260927.json`。正式部署／正式 DB 同步另由主線紀錄。
- 原生審批未知結果不再 POST、撤回與改版不授權、同人／自動核准／任意 APPROVED 不採信：`test_native_approval.py`，目前是獨立純模組，尚未接 app/service/worker，不代表正式端到端完成。

## 原生審批接入的具體邊界

1. **實際定義映射**：主線用管理後台建立三張可維護定義。GET 真實 form/node_list，保存 app、tenant、definition code、fields ids/name/type、AND node IDs 與角色席次。初版 adapter 只支援 input/textarea，不能把任意 UI 控件硬轉文字。工作台帳號同應用 open_id，主管從案件／節點已指定責任取得，不從姓名／HR「內外勤」猜組別。三線變更證據與財務不可省略。
2. **服務與資料模型**：新增 NativeApprovalService；準備／提交／刷新／套用四段分開。每版本 immutable binding 保存於專用 business record（需加入 storage.COLLECTIONS），同 workspace/request/version 唯一，UUID 唯一。保存 actor、scope hash、實際表單、mapping hash、remote receipt、last_attempt/verified_at；敏感表單及來源 token 不混公開能力狀態。
3. **短交易與 CAS**：`POST /api/approvals/{id}/submit` 或 node skip 專用 action 只在 transaction 核對最新人員、案件責任、version 並產生 immutable prepared record；HTTP 在交易外做。adapter checkpoint 在另一短交易以 binding version/attempted=False CAS 原子改為 attempted/outcome_unknown，成功 commit 才能 POST。兩 worker 即使同時領取，也只有一個能通过 checkpoint。不能只用 Python dict 或鬆散 jobs status 當持久化保證。
4. **Worker 狀態**：新 kind native_approval，prepared 首次提交；attempted／lease timeout 一律 UUID GET recovery。未知／讀不到仍 outcome_unknown，不生成新 UUID。worker 每 HTTP 的 authorize 從現在 PersonRow、公司和 workspace 讀取；readback 後再交易核對 scope 和 binding revision，舊回應不覆蓋新版本。輪詢只追蹤明確自身已綁定實例，不掃描員工無關審批。狀態需 mirrored 到申請供 UI 顯示。
5. **工作流程**：確認可投遞並建立 durable intent 後，變更可按核定流程局部凍結；網路未知時保留「送審結果待核對」，不能假稱送審失敗後放行凍結範圍。期限在 pending 期間不改、skip 不改節點。外部核准只提供 proof；scope 不變且額外三線／交付 gate 齊備，再允許 PM 套用。遠端刷新錯誤、撤回、失效清除可用授權但不刪歷史。
6. **套用前重查**：formal apply 不能只讀五分鐘舊 APPROVED，要 GET 定義＋實例後再次 CAS 核對目前 scope。遠端查詢與本機 commit 無法跨系統原子化，保存精確查證時間與結果，後續撤回標記需重核／停止後續授權，不假裝可逆已交付成果。
7. **公開能力**：区分 definition_configured、mapping_verified、submission_implemented、live_validation 狀態、目前可送與阻擋原因。Readonly／有 scope／假測試通過均不能啟用「已完成正式串接」。試辦需指定真正兩位核准人與明確申請範圍，不能代人投票。

## 仍須決策或真實驗收

跨組展延需核實各受影響任務由誰負責主管確認；先用既定責任映射，缺人阻擋送。設計變更的業主／公司主管證據來源和授權採集方式不能借 Lark 核准冒充。來源範圍 hash 要包含哪些非任務欄位需明列，避免把來源成本無關變動或每日同步時間也視為設計改版。正式日報新增的通知／津貼自动化風險需先讀既有 workflow 後規劃測試，不能為了驗收隨意新增真實薪資或發訊。
