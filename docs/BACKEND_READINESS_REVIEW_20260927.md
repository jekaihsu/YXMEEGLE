# 公司正式使用：資料、權限與串接差距審查

本檔依實際程式、隔離測試與真實來源證據分類。畫面完成、測試通過與外部端到端驗收是三個不同結果。

## 最高優先發現

**P0 API 私密資料投影缺口已修，待整輪回歸與部署。** 原 `public_ws` 沒有使用者參數，GET workspace、mutation與回執重播會回全部 `approved_leave_delegations`；畫面 Operations.tsx 只是自行過濾。現在所有 public response 傳入實際操作者，以目前 workspace profile 判斷 manager／manage_handover／principal／delegate；未知、停用及已撤權者不取得其他人的請假來源。所有深度的 migration_archive 從 API 剝除，DB 原件保留。核准／財務等伺服器計算先用完整權威資料，再做輸出投影，避免過濾資料改變業務判斷。

修復檔：`backend/workspace_projection.py`、`app.py`、`integration_routes.py`。測試 `test_workspace_projection.py` 涵蓋 GET、寫入回應、回執重播、撤權、本人／代理人、管理權及DB原件不變。本輪連同既有 backend／isolated_live／capabilities 共 **67 項通過**。私有舊備份掃描未發現 secret/access_token/refresh_token/password 等憑證欄位；不把此缺口誇大成已發生憑證外洩。

**P1 整體來源配對未驗收。** 真實九表連線成功不等於全部日報與確認單可配對。不得用ready徽章覆蓋品質狀態，或以未配對日報建立新案。

**P1 正式原生審批、班表及遠端寫回未端到端驗收。** 部分程式與模擬測試已有，不能宣稱公司已可無人工介入完成整鏈。

**P1 人員名冊不是動態公司名冊。** 本轮新需求指定由薪水表單的「人員名單及資料」取得人員並支援標註；現有能力來源讀取人員關聯，但尚未同步成完整 users。交由專職人員 agent 接續；不得讀取薪資數值、猜姓名身份或讓新增名冊自動取得 manager／能力核准權。

## 核定需求與證據對照

| 需求 | 程式／隔離測試 | 真實證據與未完成項目 |
|---|---|---|
| V4＋報價總表；不匯舊Meegle | `deployment/source-tables.json`為兩指定Base九表；`sources.configuration`限制來源，`v4_sources`以來源ID與明確關聯處理。 | 九表 ready 共2,569列；沒有舊Meegle讀取流程。唯讀已驗證，並非遠端寫回。 |
| 確認單身份、多報價同案 | `test_source_identity` 覆蓋多報價同engineeringcode、不確定link保留intake、確認單先到、collision、split、legacy人工歷史保護。 | 真實快取重播：15 formal＋266 intake＝281，6,545 tasks；報價原地修改不新增案。182確認列缺code仍待核對。 |
| 來源更新不得重複建案 | 同source record ID保留project/task ID，完整來源才套用；partial保留舊快照。 | `source-replay-fixed-20260927.json` identity checks true。此證明所測快照與更新，不概括任意未見過的來源結構。 |
| 命名、母子案與歷史編號 | 保留前導零、連字號、子案後綴；只用明確 `字母＋6數字-2數字` 建parent_code，不截短模糊合併。 | 已做匯入與身份保留；沒有把使用者完整新命名格式當成所有歷史資料的強制規則，也尚未驗收完整命名生成器。 |
| 日報配對与來源審核 | source_actor_ids用真實人員ID；daily.review展示來源檢核，不能自動造passed；人工核准前source_fields版本及唯一性guard。 | 535未配對＝403缺reference＋132 unresolved；0 imported，1缺日期。抽查Q確認單與1筆外業日報確實缺部分關聯，只是sample-level，不代表全部都是源空值。詳見 SOURCE_REPLAY_FINDINGS。 |
| 正常下班截止，不以最後打卡取代 | `learning.cutoff`缺班表回pending_schedule、多筆回conflict；`test_learning`拒固定17:00／clockout。 | Attendance實際打卡欄位已查證，排定班表來源未取得；不能顯示排定下班逾期已可判斷。 |
| 代理人在原生請假審批 | `learning_sources.parse_leave`核對定義、雙人、起訖；server verified_at 5分鐘TTL，撤回／未知failclosed；worker只刷新已引用實例。 | 請假definition／代理欄及起訖已有查證。任一正式實例核准→授權→撤回的完整E2E仍未驗收。最新definition讀取probe先回99991672；後續開權限依root實測紀錄更新。 |
| 能力地圖與教育訓練 | 查 exact 能力地圖總表；immutable workspace:id:version；不得PUT既有revision；readback、duplicate、external edit與unknown outcome測試。能力核准需明確capability，manager不自動取得。 | 能力目錄342筆及人員關聯曾唯讀查證；訓練紀錄／能力增列的真實寫回與讀回未驗收。假HTTP通過不等於正式同步完成。 |
| 財務兩人與結清 | `operations`維持PM/admin不同actualactor、有效交付版本、verified receipt、金額與migration guard；`test_workflow_completion`有具體回歸。 | 本機規則已測。沒有把來源actual cost當成已核實實收付款，也沒有遠端財務流程E2E驗收。 |
| 節點跳過PM＋組主管 | `node_skip`獨立申請、原因影響、快照hash、兩位本人票決、PM套用；status approved_skipped，任務原成果保留。財務/結案不可skip。 | 模擬已測：明確p.revision、task、owner、PM/主管、停權、完成／封存與申請內容變更均失效。正式送審仍draft-only；Lark撤回／回呼／核准結果綁定尚未實作，不能當liveverified。 |
| 單案需要的實際交付資料 | input_task_ids仍需completed＋output，waiver不可充當成果；工程範圍排除明列engineering_waivers。 | 總體工程狀態需旁註核准跳過數，避免「工程完成」被理解成每項成果都已交付；已與UX agent交叉確認。 |
| 備份、恢復及升級 | 已保存正式快照並恢復到隔離SQLite、核對rows與附件hash；migration_archive保留原JSON，restart可重入。 | 有實際演練回執，不是只有腳本。仍需每次正式部署核對最新備份點、RPO/RTO與操作責任，不能把一次演練當成每日排程永遠成功。 |

## 待專業正式使用前補齊

- P1：定義公司「案件／財務／人員資料可見」政策。目前只修已存在的請假可見規則，不憑推測縮減原有案件財務顯示。
- P1：取得對應原生審批定義與流程映射、兩人AND語義、不可變請求UUID、真實回執、回呼驗證／補查及最新狀態綁定；有真實隔離驗收後才開正式送審。
- P1：來源已核定的範圍改變需明確版本語義。現有skip以project revision和任務快照失效；source sync並非每個報價／確認單欄位更新都增加project revision。真正原生skip啟用前，應明確哪些來源範圍欄位需要納入approval snapshot，避免把純備註改動與工作範圍改版混為一談。
- P1：動態人員身份對應、正常班表、535日報與缺code確認單來源補正、隔離寫回資源與授權。
- P1：案件級讀寫與並行衝突範圍；目前數百案下單次操作仍約5–10秒，詳見 PERFORMANCE_REFERENCE_REVIEW。先守住權限、審計、跨案交易與去重，再縮小資料範圍。
- P2：維護性拆分、正式監控/告警、工作排程耗時與重試指標、角色使用手冊及清楚的失敗補件入口。

本輪沒有宣稱「全部核定需求已正式接通」。已實作項可繼續隔離驗收，pending項需要真實資料、權限或公司決策；不能以示範動畫、模擬回執或來源連線徽章替代驗收。
