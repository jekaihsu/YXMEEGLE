# Automatic node and task checking: database map and plan (2026-10-16)

Status: plan only. Nothing was built, no Lark table was written, no app code was changed.

Evidence base: live read of the V4 Base `H7W6b0PFWaVF1BsgqXJj3pQ9pXb` and the quote Base `JoOqbggsVar0ATsVgbcjh6IIp1g` with the user-login lark-cli on 2026-10-16. Counts below are measured then. This file lists fields, IDs and counts only, with no people, case names or amounts. The raw pulls are in `/tmp/lk/data` (scratch, not committed).

## 1. Answer in one page

**Yes, but only partly, and the blocker is data linkage rather than design.** The database already holds the right *units* for progress. The planned quantity per work item exists, the done quantity per daily report exists, and there are weights and a points system to combine them. What is missing today is the *link from a daily report to a case and a work item*. Without that link a done quantity cannot be attributed to any node.

| Question | Measured answer |
| --- | --- |
| Does a planned unit exist per 外業/控制/圖資/報告 work item? | Yes. 合約明細工項 has 外業數量 on 320 of 591 lines, 控制數量 274, 圖資數量 117, 報告數量 74. 合約填報工項 (779 rows: 326 外業, 264 控制, 114 圖資, 75 報告) has 基準數量 on all 779. |
| Does a done unit exist per daily report? | Yes. 外業工作單 完成數量 is filled on 182 of 187. 內業工作單 計價數量 is filled on 245 of 348. |
| Is the done unit linked to the case or line item? | **No.** 外業工作單 所屬案件 and 合約工項 are 0 of 187. 內業工作單 所屬案件 and 內業工項 are 0 of 348. 合約填報工項 → 已填報外業工作單 is 0 of 779. |
| Is there a case to plan join key by text instead? | Partly. 合約明細工項 所屬案件 text matches a real 確認單 code on 140 of 591 lines (16 of 73 distinct case codes). |
| Are the human check boxes usable as evidence? | Not yet. 外業 經理檢核/控制組檢核/工務助理檢核 are ticked on 3 of 187. 內業 品管檢核/雅雯檢核/報表 are 0 of 348. 檢核狀態 is empty on all 187 external and 213 cost sheets. |
| Are sales-stage dates usable? | Yes. 報價總表 (423 rows): 詢價日期 373, 報價日期 273, 回傳單日期 211, 提供給PM日期 279, 第一次聯繫日期 329, 確認單回傳開會日期 147. |
| Are billing and settlement facts usable? | Barely. 報價總表 累計已請款 / 累計已入帳 / 累計計價 / 營業額進度 are 0 of 423. 行政結算 has 0 rows, 採購單 0, 支出單 1. Only 工程確認單 案件已入帳 / 入帳日期 and PM告知可請款日期 (47) exist. |

So the work splits into: (A) repair or bridge the linkage so quantities reach cases, (B) a read-only evidence engine that turns table facts into a per-task and per-node verdict, (C) wire the verdict into the existing node flow without letting it complete anything on its own.

Recommended principle, consistent with the earlier SOP design ("不偽造完成", unknown stays unknown): **automatic checks produce evidence and proposals. A person still submits and a manager/approver still approves.** Automation may mark a task done only when the fact is a hard system quantity, and that is one explicit decision for you (section 9, D1).

## 2. How the SOP and the nodes fit together today

Three layers already exist and the auto-check should attach to the lowest stable one.

1. **Source SOP (Meegle template 334662 v137).** 62 nodes, 71 edges, 52 source task identities. Compiled in `backend/sop_topology.py` and `backend/sop_execution.py`. Readiness gates are behind the workspace setting `sop_topology_gate = enforce`.
2. **App SOP (`backend/policy.py`).** Nine nodes: 業務 → PM → 確認單 → 外業 → 控制 → 圖資 → 報告 → 計價 → 結算. Each has grouped tasks with stable `TASK_KEYS` (27 keys) that map back to source states (`SOURCE_NODES`) and required evidence slots (`REQUIREMENTS`, e.g. field needs `dispatch`, `field_report`, `permits`).
3. **Node assignment (Lark 節點指派 `tblcPZPmezkyeVb7`, 任務 `tblsoyGcC6K5AipF`).** Per-case owners, deadlines, free-form tasks and status, key `<工程確認單編號>|<節點>`. 9 node rows and 0 task rows exist today.

Gap between layer 2 and 3: the app SOP knows *what evidence a node needs*, and the Lark node row knows *who owns it and its status*, but nothing yet computes *whether the evidence exists*. That computation is the new piece.

## 3. Database map

### 3.1 The case spine

```
報價總表 (quote Base, 423)  --報價編號/工程編號 text-->  工程確認單 (106; 16 real)
        |                                                      |
        | 此案確認單 link (16)                                  | 合約明細（日報關聯） link (1 form only)
        v                                                      v
   sales dates                              合約明細工項 (591)  --合約填報工項（日報關聯）--> 合約填報工項 (779)
                                             per-line planned quantity                  per-reportable-item, category, 基準數量,
                                             by 外業/控制/圖資/報告                      標準點數, 對應營業額, 計價權重
                                                                                              ^                    ^
                                                              外業工作單.合約工項 (0/187) ----+                    |
                                                              內業工作單.內業工項 (0/348) -------------------------+
```

Everything on the bottom row is where progress is computed, and both arrows into 合約填報工項 are empty in live data.

### 3.2 Table dictionary (V4 Base unless noted)

| Table | ID | Rows | Grain | Role for auto-check |
| --- | --- | ---: | --- | --- |
| 工程確認單 | `tblmSQrcCs9vPQZx` | 106 (16 real) | one per case | Case identity, planned workdays per department (外業/控制/圖資/報告總工天), 狀態, 案件已入帳, 入帳日期, 報價單/確認單 PDF attachments, 啟動 SOP button |
| 合約明細工項 | `tblobs4qPy2w9MZ6` | 591 | contract line | Planned quantity and workdays per 外業/控制/圖資/報告, contract amount |
| 合約填報工項 | `tblwQPYk3c9RvCU7` | 779 | reportable item | 工項類別, 基準數量, 標準點數, 對應營業額, 計價權重, 本工項剩餘營業額 |
| 外業工作單 | `tbl5zPLS0ExWNEty` | 187 | one external job line in a day | 完成數量, 計價數量, 營業額點數, 附件 (photos/reports), checks, many ⚠ flags |
| 外業成本單 | `tbl8wRYCUCvbSoJG` | 213 | one team-day | 工作日期, 組別, crew, 工作單列 link (155 linked), 零產出歸屬案件 (0) |
| 內業工作單 | `tblrCo8KeZiuJUNh` | 348 | one internal job line | 計價數量, 營業額點數, 暫填案號 (132), checks |
| 內業成本單 | `tblKwSDRg6WaGHYr` | 201 | one person-day | 內業組別 (控制/圖報A/圖報B), 工作日期 |
| 行政工作單 / 行政成本單 | `tblHsH4ocQSG08g5` / `tbl7ngrBD2jSx6Cz` | 188 / 59 | admin item | 行政工項, 件數. **No case field**, so it cannot be attributed to a case |
| 工作預排 | `tblZz6Mkhv9gHrB2` | 312 | scheduled assignment | 開始/結束日期, 組別, 人員, 條類型 (出工 307). 案件 link filled on 270 but points at table `tbljGNdDxLs8ihuE`, which is not in this Base |
| 節點指派 / 任務 | `tblcPZPmezkyeVb7` / `tblsoyGcC6K5AipF` | 9 / 0 | node / task | Our own status and ownership |
| SOP 案件總覽 | `tbl3jzXUO8oyfvcu` | 1 | one per case | Lookup roll-up of node status (目前節點, 已完成節點, 總節點) |
| 人員名單 | `tblfaCO2xPUNptQH` | 67 | person | 所屬組別, 職級, Lark account (used for approval authority) |
| 行政結算 / 採購單 / 支出單 / 約定帳戶 | `tblpHFaVfmgZVkoD` / `tblC76IUep5pZSX6` / `tbligcwRyAGhxL2e` / `tblepBPXwx3txJTT` | 0 / 0 / 1 / 36 | finance | Intended settlement evidence, currently empty |
| 津貼匯整總表 / 明細 | `tblC8181oxaBcT0d` / `tblbxh8QQaY6N3DL` | 122 / 287 | person-month allowance | Gated on 案件已入帳. Downstream consumer, not evidence |
| 報價總表 (quote Base) | `tblENZvYAya93Twa` | 423 | one per quote | Sales-stage dates, 狀態 (成案 114 / 舊案 25), 此案確認單 link (16), PM告知可請款日期 (47) |
| 外業/控制/圖資/報告營業額 (quote Base) | `tbl27u3CgMYiuDrC` etc. | ~1,000 each | standard rate tables | 指標(每日) per work item name. Reference data for planned workdays, not progress |

### 3.3 Existing "units" you pointed at

Two parallel unit systems already exist, and both can drive progress.

- **Quantity unit (physical).** Planned: 合約明細工項 `外業數量` etc., converted through 換算係數 = 合約數量 / 基準數量. Done: 外業工作單 完成數量, 內業工作單 計價數量. Re-work (是否重工) zeroes the billable quantity. 業主追加數量 overrides it.
- **Points unit (value).** `營業額點數-公式 = 完成數量 / 有效基準 × 有效標準點數`, with a frozen copy of 基準/係數/單價/點數 taken at report creation. Planned points per item are 對應營業額, and 本工項剩餘營業額 = 對應營業額 − Σ done points. Points are comparable across 外業/控制/圖資/報告, so they allow a case-level roll-up.
- **Time unit.** 工程確認單 外業總工天 / 控制總工天 / 圖資總工天 / 報告總工天 (planned) versus the count of distinct 外業成本單 / 內業成本單 days for the case (actual). This is a fallback progress signal that needs only the case link, not the line-item link.

Lark already computes quality flags we can reuse as signals instead of rewriting them: ⚠案件不符, ⚠工項不符, ⚠營業額超過工項餘額, ⚠已結案新列, ⚠負值, ⚠未掛明細, ⚠營業額異常, 案件關聯檢核, 人力方案檢核.

## 4. What blocks automation today (ranked)

| # | Finding | Evidence | Effect |
| --- | --- | --- | --- |
| B1 | Daily reports carry no case or line-item link | 外業 0/187 and 內業 0/348 for both links | No progress can be attributed to any node |
| B2 | 90 of 106 工程確認單 rows are empty shells | 工程確認單編號 is a formula from 所屬案件, which is empty on 90 rows. Only 16 real forms, 12 of them match a contract line by code | Case spine is thin. Node rows keyed on the code only exist for real forms |
| B3 | Provisional case codes on 內業 do not match anything | 132 filled, 0 match a 確認單 code, 1 matches a contract-line code (after stripping prefix and suffix) | The documented workaround cannot be used as is. The cause is **not verified**. It may be older cases outside V4, or a different code format. Needs a 10-row manual sample |
| B4 | Planned values are incomplete | 對應營業額 on 297 of 779. 控制/圖資/報告預估工天 on contract lines is 0 of 591 although 274/117/74 quantities exist. 確認單 控制/圖資/報告總工天 is 0 of 106 | Points-based plan is missing for most items. Quantity-based plan still works from 基準數量 |
| B5 | Human check boxes are unused | See section 1 | Cannot treat a ticked check as the "done" evidence yet. Use as an optional strengthener |
| B6 | Billing and settlement facts are not recorded in Lark | Section 1 last row | Those two nodes stay mostly manual or app-evidence based |
| B7 | 工作預排 案件 link target is outside the Base | Target `tbljGNdDxLs8ihuE` is not in the table list | Schedule cannot be tied to a case with current scopes |
| B8 | Admin items have no case | 行政工作單 has no 所屬案件 | 行政公務 (permits, insurance) cannot be auto-checked per case |

B1 to B3 decide everything. Fix those first or the rest is paper.

## 5. Evidence model

Every check is a small declarative rule, evaluated against the case, returning one of three states. This reuses the fail-closed stance of `sop_topology` (unknown stays unknown).

| Result | Meaning |
| --- | --- |
| `met` | The evidence exists and satisfies the rule |
| `unmet` | The data is present and says the condition is not satisfied (for example 62% of planned quantity) |
| `unknown` | The data needed is missing, unlinked or ambiguous. Never counted as met, never counted as failed. Shown as "cannot verify" with the reason |

Signal kinds, ordered from strongest to weakest:

| Kind | Example | Trust |
| --- | --- | --- |
| S1 System quantity | Σ 完成數量 ≥ planned for the node's 工項類別 | High, once linked |
| S2 Date stamp | 回傳單日期 present, 提供給PM日期 present | High. Someone entered a real date |
| S3 Record exists | 工程確認單 with 所屬案件, 報價編號 filled | Medium |
| S4 Attachment present | 外業工作單 附件 not empty, 確認單 PDF | Medium. Presence only, not content |
| S5 Human check | 外業經理檢核 ticked | High where used, unused today |
| S6 Native approval receipt | Lark approval for 跳過/展延/變更/財務 | Highest. Already handled by the app |
| S7 App evidence | Files and links uploaded in the app per node requirement (`REQUIREMENTS`) | Medium. Already stored by the app |

A rule composes signals, for example `field.delivery = S1(外業 quantity ≥ 95%) AND (S4(完工報告 attachment) OR S7(field_report))`.

Node verdict is derived from its task verdicts and drives the existing flow:

| Node evidence status | Condition | What the app does |
| --- | --- | --- |
| `no_evidence` | no task is met | nothing |
| `partial` | some met, none unmet-by-quantity | show checklist with met/unmet/unknown per task |
| `ready_for_review` | all required tasks met | prompt the node manager to complete, which then goes to 待審核 as today |
| `anomaly` | contradicting data (over 100%, report after case closed, ⚠ flags) | warn the manager. Never blocks silently |

This does not change the approval chain: manager completes, node manager or above approves, reject returns to 進行中.

## 6. Progress formulas (the "unit" idea)

All formulas are per case and per node, over the line items whose 工項類別 equals the node.

```
planned_qty(item)   = 合約明細工項.<類別>數量              (via 合約填報工項.來源合約明細)
done_qty(item)      = Σ 完成數量 (外業) or Σ 計價數量 (內業) over linked reports, excluding 是否重工 = 是,
                      using 業主追加數量/業主數量覆寫 when set
item_progress       = min(done_qty / planned_qty, 1)             (over 100% is an anomaly, not extra progress)
node_progress_qty   = Σ item_progress × 標準點數 / Σ 標準點數      (points as weight; fall back to equal weight if 標準點數 is missing)
node_progress_pts   = Σ done points / Σ 對應營業額                 (only when 對應營業額 is present for every item)
node_progress_days  = distinct work days with a cost sheet / 確認單 <類別>總工天     (fallback, needs only case link)
```

Choice of which to show: points when complete, else quantity, else days, and always label which one was used so nobody reads a day-based estimate as a quantity.

"Done" thresholds are policy, not math, so they are decisions: suggested `ready_for_review` at ≥ 95% of planned quantity with no unlinked or flagged reports in the last N days, plus the completion evidence in section 7 for that node.

Stall detection also comes for free: planned remaining > 0, no new report for X working days, node 進行中 → raise to the manager. This ties into the existing 每五日 reminders in the SOP.

## 7. Node by node

Legend for readiness today: **Green** can be checked from data that exists now. **Amber** works after a specific fix. **Red** has no usable data, so it stays manual or app-evidence.

SOP state IDs come from `SOURCE_NODES` in `backend/policy.py`.

### 7.1 業務 (sales). Readiness: **Green**

Source states: 14, 26, 15, 16, 25, 28, 17. App tasks: `demand_quote`, `quote_provide`, `quote_followup`.

| Task | Rule | Source | Today |
| --- | --- | --- | --- |
| `demand_quote` 業主需求與報價編號 | 詢價日期 and 報價編號 present | 報價總表 | 373 and 374 of 423 |
| `quote_provide` 提出報價並通知業主 | 報價日期 present, 報價單 PDF attached | 報價總表, 工程確認單 | 273 dates. PDF presence not measured |
| `quote_followup` 報價追蹤與回簽 | 回傳單日期 present and 狀態 = 成案 | 報價總表 | 211 dates, 114 成案 |
| (state 17 contact) | 第一次聯繫日期 present | 報價總表 | 329 |

Gaps: 業主需求佐證文件 and 已通知業主截圖 are files, so they stay as app evidence (S7). Join from the quote to the case relies on 報價編號 / 工程編號 text, since the explicit link exists for only 16. The earlier diagnosis already found duplicate quote numbers (41) and duplicate engineering numbers (21), so a join that hits more than one quote must return `unknown`, never pick one.

### 7.2 PM. Readiness: **Amber**

Source states: 4 (assign tasks part), 40 prerequisites. App tasks: `assign_owners`, `approve_schedule`, `project_folder`.

| Task | Rule | Source |
| --- | --- | --- |
| `assign_owners` | every applicable downstream node row in 節點指派 has at least one owner | 節點指派 (our own table) |
| `approve_schedule` | scheduled 出工 entries exist for the case | 工作預排 (blocked by B7) |
| `project_folder` | case Drive folder exists | app Drive records |
| handoff | 提供給PM日期 present | 報價總表 (279) |

Fix: resolve B7 (read the table behind `tbljGNdDxLs8ihuE`, or add a case link inside V4).

### 7.3 確認單 (confirmation). Readiness: **Amber**

Source states: 83, 4, 39, 38, 41. App tasks: `prepare_confirmation`, `issue_handoff`, `group_confirmation`.

| Task | Rule | Source |
| --- | --- | --- |
| `prepare_confirmation` | 工程確認單 exists with 所屬案件, 案件關聯檢核 = OK, 人力方案檢核 clean, 確認單 PDF attached, planned workdays > 0 for each department that has contract quantity | 工程確認單, 合約明細工項 |
| `issue_handoff` | 提供行政回傳確認單時間 present | 報價總表 (100) |
| `group_confirmation` | one 任務 per department (外業/控制/圖資/報告) done | 任務 (human, auto-seeded) |
| meeting | 確認單回傳開會日期 present | 報價總表 (147) |

Auto-seeding: when a form has contract quantity for a category, create the group-confirmation task for that department. This is the cleanest place to start using the 任務 table. Fix B2 (empty shells) and B4 (planned workdays missing for 控制/圖資/報告) first.

### 7.4 外業 (field). Readiness: **Amber, highest value**

Source states: 40, 42, 78, 43, 44. App tasks: `dispatch_prerequisites`, `field_daily`, `field_delivery`.

| Task | Rule | Source |
| --- | --- | --- |
| `dispatch_prerequisites` | at least one 出工 entry scheduled before first report | 工作預排 (B7) |
| `field_daily` | `node_progress` from section 6 at ≥ threshold | 外業工作單 → 合約工項 → 合約明細工項 (B1) |
| `field_delivery` | `field_daily` met AND completion attachment on at least one report in the last batch (S4) or app `field_report` evidence | 外業工作單.附件, app |
| permits (state 2) | stays app evidence `permits` | no case in 行政工作單 (B8) |

Time-unit fallback available today if only the cost sheet carries the case: 外業出工天 planned vs distinct 外業成本單 days. Note 外業成本單 has no case field of its own, and the case is only reachable through its 工作單列, which is the broken link.

Useful extras once linked: ⚠營業額超過工項餘額 means over-delivery. 是否重工 count means rework. 零產出 reports mean weather or client delays, which is context for the manager rather than progress.

### 7.5 控制, 7.6 圖資, 7.7 報告. Readiness: **Amber**

Source states: 75, 76, 77 (daily), 47 (delivery, shared by all three). App tasks: `control_daily`, `control_delivery`, `mapping_daily`, `mapping_delivery`, `report_daily`, `report_delivery`.

| Task | Rule | Source |
| --- | --- | --- |
| `*_daily` | `node_progress` for 工項類別 = 控制 / 圖資 / 報告 at ≥ threshold | 內業工作單 → 內業工項 → 合約填報工項 (B1) |
| `*_delivery` | `*_daily` met AND 成果繳交日期 / app deliverable evidence present | app `deliverable` evidence. No V4 field exists for delivery date |

Important detail for the group split: 內業成本單.內業組別 has 控制 / 圖報A / 圖報B, so the group cannot distinguish 圖資 from 報告. Use the line item's 工項類別 for the node, and the group only for ownership. Lark's own ⚠工項不符 flag already encodes this.

Planned quantity for these three is thinner (274, 117, 74 lines, no 預估工天), so quantity-based progress works and day-based does not.

### 7.8 計價 (pricing). Readiness: **Amber**

Source states: 55, 48, 56, 74, 59. App tasks: `pricing_quantity`, `billing_conditions`, `billing_batches`.

| Task | Rule | Source |
| --- | --- | --- |
| `pricing_quantity` 核對成果及計價數量 | Σ 計價數量 by category equals what the technical nodes delivered, with no ⚠ flags | 外業/內業工作單 |
| `billing_conditions` | PM告知可請款日期 present | 報價總表 (47) |
| `billing_batches` | billed amount ≤ Σ 計價金額 (計價數量 × 單價 × 計價權重) for the case, and invoice proof in app evidence | computed, app |

Computable now: the billable amount per case, once B1 is fixed (the formula 計價金額 already exists in 外業工作單). Not computable: what has already been billed, because 累計已請款 is empty (B6).

### 7.9 結算 (settlement). Readiness: **Red**

Source states: 60, 72, 68, 71, 69, 70, 59. App tasks: `payment_reconciliation`, `settlement_documents`, `closure_survey`.

| Task | Rule | Source |
| --- | --- | --- |
| `payment_reconciliation` | 案件已入帳 = true and 入帳日期 present | 工程確認單 |
| `settlement_documents` | a 行政結算 row exists for the case | 行政結算 (0 rows today) |
| `closure_survey` | 狀態 = 已結案, closure proof and survey evidence in app | 工程確認單.狀態, app |

Only the first rule has data today. Settlement is the least automatable node, and that is fine. It carries the financial approvals, which already go through native Lark approval.

### 7.10 Cross-cutting checks

- Case health: 案件關聯檢核, 狀態 (執行中 vs 已結案/中止) versus reports still arriving (⚠已結案新列).
- Rework and zero-output rate per category.
- Allowance gating: 津貼 rely on 案件已入帳. If we surface it in the settlement check, payroll and node status agree.
- Conditional branches from the source SOP (下包, 展延) stay with `sop_topology` applicability. The auto-check must treat a not-applicable node as excluded, not as met.

## 8. Proposed plan

Phases are ordered so each one is useful alone and nothing writes to Lark until phase 3.

### Phase 0: Make the data linkable (owner action, plus small app work)

| Step | What | Who |
| --- | --- | --- |
| 0.1 | Take a 10-row sample of 內業 暫填案號 to find out why 0 of 132 match (B3) | us, 30 minutes with you |
| 0.2 | Decide the repair for B1. Options below | you |
| 0.3 | Clear or hide the 90 empty 確認單 shells, or mark them so the engine ignores them (B2) | you |
| 0.4 | Read the table behind `tbljGNdDxLs8ihuE` or add a case link to 工作預排 (B7) | you / us |

Options for B1, in order of preference:

1. **Make the link mandatory at entry.** 所屬案件 and 合約工項 are documented as 必填, but the required flag cannot be set by CLI. Set it in the Lark form/field UI, plus a Lark automation that rebuilds the link from 工編 text, which the field descriptions say is already how 合約填報工項 → 合約明細 is maintained.
2. **Backfill by rule.** For historical rows, match the stored code text uniquely to one case. Anything ambiguous stays unlinked. The earlier V4 diagnosis already set this rule (no fuzzy name match, never pick between duplicate quotes). The app does not write to Lark for this. It produces a proposed-link report that you apply.
3. **App-side provisional join only** (no Lark change). Works for rows with a unique code and keeps `match_basis`, as the existing provisional-code path does. Weakest, because it hides the Lark problem.

### Phase 1: Evidence engine in shadow mode (read only)

- New backend module (name proposal: `backend/node_evidence/`) that reads the datasets the live-read layer already caches and evaluates the rules for a case. Same pattern as `node_assignment`: pure rule model, thin Lark boundary, feature flag `NODE_EVIDENCE_ENABLED` default off.
- Rules live as versioned data, one per task key, in the same spirit as `sop_source_contracts.json`, so changing a threshold is a data change with review rather than a code change.
- Output per case: per task `met/unmet/unknown` with the reason and the source record IDs, per node the evidence status and the progress number with its unit label.
- Show it as a read-only column in the existing case node list (no new page). Managers see "Evidence: 3 of 5 met, field progress 62% by quantity".
- Acceptance: run over all 16 real cases and compare against what the managers say by hand. Count agreement per node. Do not proceed until the disagreements are explained.

### Phase 2: Suggestions that save clicks (still no automatic completion)

- "Ready for review" banner prompts the manager when a node reaches `ready_for_review`.
- Auto-seed 任務 rows: one group-confirmation task per department with contract quantity, and one delivery task per node with a deadline from the planned dates. Writes only to the allowlisted 任務 table through the existing node-assignment writer.
- Stall and anomaly alerts through the existing mention-notification path.
- Pre-fill the completion checklist in the guided node-completion dialog with the evidence it already found, so the person only adds what is missing.

### Phase 3: Limited automatic task completion (only if you choose it, D1)

- Allowed for tasks whose rule is purely S1/S2 (quantity at threshold, date present), writing 已完成 with `done_by = system` and the rule version, so it is auditable and reversible.
- Node completion still needs a manager and approval. Rejection still returns a node to 進行中, and the rule then re-evaluates on the next read.
- Rollback: the feature flag turns it off. System-completed tasks are marked so they can be listed and reverted.

### Tests to write with each phase

- Rule unit tests: met, unmet, unknown, ambiguous join, duplicate quote numbers, 重工, 業主追加數量, over 100%.
- Fixtures from the real schema shapes, no real names or amounts.
- A regression case for each blocker: unlinked report must produce `unknown`, never `unmet`.
- Concurrency and staleness: evidence computed from cached Lark data is labelled with its fetch time, and writes still require a fresh read as node assignment does.

## 9. Decisions needed from you

| ID | Question | Recommendation |
| --- | --- | --- |
| D1 | May the system mark a task 已完成 on its own when the rule is a hard quantity or date? | Not at first. Run phases 1 and 2, compare for two weeks, then enable per task key |
| D2 | Threshold for "field work is done". 100% of planned quantity, or a tolerance? | 95% plus a completion attachment, adjustable per category, because contracts routinely end slightly under or over |
| D3 | How should B1 be repaired? | Option 1 for new rows plus Option 2 as a one-off backfill report for history |
| D4 | What are the 90 empty 確認單 rows? | Needs your answer. If they are intentional placeholders, add a status so the engine can skip them |
| D5 | Where does 成果繳交日期 (delivery date) live? | Add one date field per technical node on 節點指派 (or reuse 完成時間 of the delivery task). Today no V4 table holds it |
| D6 | Should 外業經理檢核 / 品管檢核 become required evidence? | Yes for 控制/圖資/報告 delivery once people actually tick them. Today they are unused, so the engine ignores them |

## 10. Illustrative rule and result

Rule (data, not code):

```json
{
  "id": "field_daily", "node": "field", "version": 1,
  "all_of": [
    {"signal": "quantity_progress", "category": "外業", "op": ">=", "value": 0.95,
     "needs": ["report.case_link", "report.item_link", "item.planned_qty"]},
    {"signal": "no_open_flags", "flags": ["⚠案件不符", "⚠工項不符", "⚠負值"], "window_days": 14}
  ],
  "on_missing": "unknown"
}
```

Result for one case:

```json
{
  "task": "field_daily", "state": "unknown",
  "reason": "report_link_missing", "detail": "14 reports for this case code have no 合約工項 link",
  "progress": {"unit": "days", "value": 0.62, "note": "fallback, quantity unavailable"},
  "sources": ["tbl5zPLS0ExWNEty", "tbl8wRYCUCvbSoJG"], "fetched_at": "2026-10-16T12:30:00+08:00"
}
```

## 11. What I did not check

- Attachment presence on 工程確認單 PDF and 報價單 PDF, and on report 附件 (only field existence was read).
- The content of the Drive folders and the app's own `workspace.db` evidence. Those are the S7 signals and need a separate read.
- Whether the 16 real forms are the cases people are working on now. Roster of "active cases" should come from you.
- The cause of B3, and the target of 工作預排.案件 (B7).
- Dates: the newest cost-sheet date is 2026-08-11 and the newest schedule date is 2026-08-19, so the report tables look at least two months stale relative to today (2026-10-16). Either daily reporting moved elsewhere, or entry stopped. Worth asking before building on it.
