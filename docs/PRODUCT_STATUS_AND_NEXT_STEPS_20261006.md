# 專案狀態與下一步追蹤表

更新日：2026-10-06（Asia/Taipei）  
Git 基準：`ava-apple/yx-company-system` @ `72527bc`（驗證修正；原 22 個 issue 整合基準 `d94a5d9`）
追蹤規則：直接編輯下方編號項目的狀態／負責人／備註；勾選「程式狀態」不等於 GitHub issue 已關閉、PR 已審核或業務已驗收。

## 狀態定義

- **已完成**：此追蹤項所指程式已整合到目前本機基準，且其狀態已由可列出的證據確認。未必代表已部署或已驗收。
- **未開始**：尚無實作開始證據。
- **進行中**：程式／文件／驗收工作已開始，尚未達完成條件。
- **審查中**：已提交待 code review、PR review 或明確階段審查；需寫明是哪一種審查。
- **待驗收**：程式已整合，等待測試、真人／業務或部署驗收。
- **受阻**：有明確阻擋，需記錄解除條件。
- **未知**：現有證據不足，不推定完成或未開始。

## 專案摘要

- 本機主線已整合 22 個 issue 工作分支（#9、#33–#50 中實際存在者、#59–#62、#64–#67）；最後整合 commit 為 `d94a5d9`。Issue 分支 refs 保留，對應 issue worktree 已關閉，現只有主 checkout 與此 worktree。
- 主線目前相對 `origin/main` 領先 114 commits。這批整合與驗證修正尚未推送至 GitHub、沒有已知 PR，因此**不能稱為 GitHub 已合併或 issue 已關閉**。
- GitHub connector 對此 repo 搜尋回傳不可見／不存在（permission/not-found）；故下方 GitHub issue 開關狀態皆標「未能核實」。取得 repo 權限後逐項刷新，不可從本地 merge 推斷遠端狀態。
- 以整合基準 `d94a5d9` 執行本次修正與回歸；最終驗證：後端 1,733 passed／7 skipped、前端 session-epoch 32 checks、company-route 4 checks、production build 全通過，`git diff --check` 通過。測試通過不等於已部署或 GitHub issue 已關閉。
- 優先順序：先確認合併後基準可建置／可啟動並修復核心阻擋，再完成功能／PRD 驗收與 GitHub issue 對帳，最後處理整體 UI/UX redesign。影響可用性的局部 UX 缺陷可隨核心修復一併完成。

## 1. 程式整合與 GitHub issue 對帳

| # | 追蹤項目 | 程式狀態 | GitHub issue 狀態 | 完成證據／剩餘工作 | 負責人 |
|---:|---|---|---|---|---|
| 1 | Issue #9 | 已完成 | 未能核實 | 本機整合：`00c24af`。取得 GitHub 權限後確認 issue 是否 closed，補遠端連結／日期。 | 工程 |
| 2 | Issue #33 | 已完成 | 未能核實 | 本機整合：`98b8846`。遠端 issue 狀態待核。 | 工程 |
| 3 | Issue #34 | 已完成 | 未能核實 | 本機整合：`93bb8bf`。遠端 issue 狀態待核。 | 工程 |
| 4 | Issue #35 | 已完成 | 未能核實 | 本機整合：`44220f8`。遠端 issue 狀態待核。 | 工程 |
| 5 | Issue #38 | 已完成 | 未能核實 | 本機整合：`63df591`。遠端 issue 狀態待核。 | 工程 |
| 6 | Issue #39 | 已完成 | 未能核實 | 本機整合：`1a49e98`。遠端 issue 狀態待核。 | 工程 |
| 7 | Issue #41 | 已完成 | 未能核實 | 本機整合：`6a3bd39`。遠端 issue 狀態待核。 | 工程 |
| 8 | Issue #44 | 已完成 | 未能核實 | 本機整合：`0b73700`。遠端 issue 狀態待核。 | 工程 |
| 9 | Issue #45 | 已完成 | 未能核實 | 本機整合：`169f145`。遠端 issue 狀態待核。 | 工程 |
| 10 | Issue #46 | 已完成 | 未能核實 | 本機整合：`7884508`。遠端 issue 狀態待核。 | 工程 |
| 11 | Issue #47 | 已完成 | 未能核實 | 本機整合：`8e2d3c9`。遠端 issue 狀態待核。 | 工程 |
| 12 | Issue #48 | 已完成 | 未能核實 | 本機整合：`3db0560`。遠端 issue 狀態待核。 | 工程 |
| 13 | Issue #49 | 已完成 | 未能核實 | 本機整合：`e0f27a2`。遠端 issue 狀態待核。 | 工程 |
| 14 | Issue #50 | 已完成 | 未能核實 | 本機整合：`df9f0cd`。遠端 issue 狀態待核。 | 工程 |
| 15 | Issue #59 | 已完成 | 未能核實 | 本機整合：`a984879`。遠端 issue 狀態待核。 | 工程 |
| 16 | Issue #60 | 已完成 | 未能核實 | 本機整合：`53f350e`。遠端 issue 狀態待核。 | 工程 |
| 17 | Issue #61 | 已完成 | 未能核實 | 本機整合：`21989de`。遠端 issue 狀態待核。 | 工程 |
| 18 | Issue #62 | 已完成 | 未能核實 | 本機整合：`9a75604`；目前 HEAD 已無衝突／unmerged entries。最後整合後完整驗證仍待做。 | 工程／QA |
| 19 | Issue #64 | 已完成 | 未能核實 | 本機整合：`d480a17`。遠端 issue 狀態待核。 | 工程 |
| 20 | Issue #65 | 已完成 | 未能核實 | 本機整合：`02180d7`。遠端 issue 狀態待核。 | 工程 |
| 21 | Issue #66 | 已完成 | 未能核實 | 本機整合：`905db40`。遠端 issue 狀態待核。 | 工程 |
| 22 | Issue #67 | 已完成 | 未能核實 | 本機整合：`d94a5d9`。遠端 issue 狀態待核。 | 工程 |
| 23 | Issues #10–32、#36–37、#40、#42–43、#51–58、#63 | 未知 | 未能核實 | 不在本次 22 個整合清單中；確認 repo 全部 open issues 後再新增／標記不適用，不假定不存在或完成。 | PM／工程 |

## 2. 目前核心工作與 PRD 驗收

| # | 工作項目 | 狀態 | 完成條件／下一步 | 負責人 |
|---:|---|---|---|---|
| 24 | 合併後主線完整性檢查 | 已完成 | 2026-10-06 本機完整 gate：後端 1,733 passed／7 skipped；前端 session-epoch 32 checks、company-route 4 checks、production build 通過；臨時 SQLite demo 的 `/`、`/api/health`、demo session、`/api/workspace`、前端 JS asset 均 HTTP 200。後端僅有 Starlette/httpx deprecation warning。 | 工程／QA |
| 25 | 確認 prototype 永久 loading 阻擋 | 待驗收 | 先前記錄的 loading 狀況在 10/06 重新檢視 live 網頁時未重現：儀表板已呈現工作總覽、案件和待辦，不是 loading spinner。仍須以 build SHA 對應該 live 頁面與本機分支，並對本機瀏覽器做視覺驗收；本次 Computer Use 裝置不可用，故不宣稱 UI 驗收完成。 | 前端／後端／QA |
| 26 | 部署版本與本機來源對應 | 未開始 | 加／確認可查的 build SHA，取得正式／staging 實際版本並證明與驗收 checkout 相同。不得只用 HTTP 200 當版本證據。 | Release |
| 27 | Lark 八表同步與關聯品質 | 待驗收 | 對八表記錄來源身分、列／頁數、同步時間、ready/partial/error；以隱私安全 aggregate 說明 matched/ambiguous/missing，不複製個資或金額列。 | 資料整合 |
| 28 | 一般同事核心工作旅程 | 待驗收 | 具權限一般員工本人登入→看指派→開始→交付輸出／附件／留言→完成→主管確認 audit 與下游輸入；記錄同一 build 的結果。 | 業務／QA |
| 29 | SOP、工作量與公司日曆核定 | 待驗收 | 確認必要 SOP／成果、節點責任、組日容量、假日補班及工作日規則；先於隔離環境套用並走代表情境。 | PM／節點主管 |
| 30 | 真實雙人審批與版本綁定 | 待驗收 | 兩位指定本人完成受控測試；核對同一 Lark instance、版本與 evidence，再由授權者 execute-once；覆蓋 rejection、stale version、duplicate 與未配置 adapter。禁止代按。 | 指定審批人／QA |
| 31 | 備份與還原維運 | 待驗收 | 確認密鑰分離保管、常態排程及責任人；用同版 DB+附件還原至隔離環境並校驗 hash，完成同版 24 小時觀測。歷史一次成功不代替常態維運驗收。 | Ops |
| 32 | A01–A16 同版驗收矩陣 | 未開始 | 將每個 PRD acceptance case 標 pass/fail/blocked/not run，附 build SHA、角色、日期與非敏感回執；缺陷建立可追蹤 issue。 | QA／業務 |

## 3. UI/UX 改版

| # | 工作項目 | 狀態 | 完成條件／下一步 | 負責人 |
|---:|---|---|---|---|
| 33 | 整理 UX 痛點與使用頻率 | 未開始 | 訪談／彙整各角色最高頻工作、目前卡點與代表頁面；將 usability blocker 同步納入 #25/#28，不等待全面 redesign。 | PM／設計 |
| 34 | 選一條高價值流程做試改 | 未開始 | 核心需求穩定、主流程可用後，先改 dashboard→我的工作／案件主要流程之一；用使用者回饋確認，再擴展共用元件與次要頁。 | 設計／前端 |
| 35 | 跨頁視覺系統與 responsive 驗收 | 未開始 | 共用字級、間距、狀態色、表單、表格、loading/empty/error 規範；相關裝置實測通過後再結案。 | 設計／前端／QA |
| 36 | 本輪主線檢查發現的三項回歸修正 | 已完成 | 修正正式 Drive root 可被空值清除、pilot copy 同一 workspace ID 衝突及附件複製、isolated backup helper 缺 canonical backend schema。針對性 30 項通過；完整 local CI 1,733 passed／7 skipped 且前端 gate/build 通過。程式已提交：`72527bc`。 | 工程 |

## 4. 最近更新紀錄

| 日期 | 更新 |
|---|---|
| 2026-10-06 | 以目前 HEAD `d94a5d9` 重建追蹤基準；記錄 22 個本機已整合 issue commits、113 commits ahead 與無衝突狀態；GitHub connector 無法看到目標 repo，因此遠端 issue 狀態全部保留未能核實。 |
| 2026-10-06 | 本機完整 local CI 首次發現三項失敗並修正；後端全套及前端 session/route/build gate 重跑全過。live 儀表板重新檢視已呈現內容，舊 loading blocker 暫列待 build 對應與 Computer Use 視覺驗收。 |
| 2026-10-06 | 修正及更新追蹤表提交 `72527bc`；目前分支 `origin/main` ahead 114，工作樹乾淨，未推送。 |

## 維護方式

每次進展直接更新對應編號列的狀態、證據與日期；新工作從下一個號碼追加。GitHub issue 關閉需以 GitHub 當前遠端狀態為證，程式完成需列 commit／驗收證據，部署及業務簽核分開記錄。不要刪除舊狀態而不留更新紀錄。
