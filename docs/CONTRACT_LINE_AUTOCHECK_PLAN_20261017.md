# Contract line (合約明細工項) as the auto-check anchor: field map, auto-connect rules, plan (2026-10-17)

Status: plan only. Nothing was built and no Lark table was written. Follows `NODE_AUTOCHECK_PLAN_20261016.md`, which this refines (its blocker B1 is split into three separate links below).

Evidence: live read of the V4 Base `H7W6b0PFWaVF1BsgqXJj3pQ9pXb` and the quote Base on 2026-10-17, plus a read of `backend/v4_sources.py`, `source_entities.py`, `source_work_items.py`. Counts only. No names or amounts.

## 1. Short answer

**You are right that 合約明細工項 is the right anchor for the plan side, and I can tell which fields to check.** The plan side is in better shape than I reported: the contract line already links to its reportable item, and the quantities agree exactly.

But the 日報關聯 on the contract table only covers the hop *contract line → 合約填報工項*. The hop *daily report → 合約填報工項* is still empty (0 of 187 外業 and 0 of 348 內業). So the contract side can be auto-checked and auto-connected now, and the done side still needs one more link.

| Hop | Link | Measured today | Auto-connectable from 工編? |
| --- | --- | --- | --- |
| 1. Case → contract line | 所屬成案確認單（日報關聯） | 4 of 591 lines | **Yes**, from 工編號碼 prefix. About 15 to 25 cases resolve uniquely today |
| 2. Contract line → reportable item | 合約填報工項（日報關聯） / 來源合約明細（日報關聯） | 598 of 779 items linked, 369 of 591 lines | **Mostly**: 70% of all items by rule, 98% precise |
| 3. Daily report → reportable item | 合約工項 / 內業工項 | 0 of 187 and 0 of 348 | **No.** Reports hold no usable code, so the entry side must change |

## 2. What the contract table gives us (verified)

- One line per contract item: 591 lines, 工編號碼 filled on 579, 合約項次 on 586.
- Planned quantity per category: 外業數量 on 320 lines, 控制數量 on 274, 圖資數量 on 117, 報告數量 on 74. Together 785 expected reportable items.
- 合約填報工項 holds 779 items (326 外業, 264 控制, 114 圖資, 75 報告), so item count is within 1% of the expected 785. The items exist. Many just lack the link back.
- **Link integrity where it exists is perfect.** Each of the 598 linked items points at exactly one line, and its 基準數量 equals that line's quantity for the item's category on all 598. So the item is a 1:1 copy of one category of one line. It is not an aggregate.
- Money: 合約金額(原始), 分項金額(報出), and per item 合約單價 and 計價權重 (外業 0.5, 控制/圖資/報告 0.1).

## 3. Which fields to check

For a category c in {外業, 控制, 圖資, 報告}:

| Role | Field | Table | Use |
| --- | --- | --- | --- |
| Plan | `<c>數量` | 合約明細工項 | Planned quantity. Same value as 基準數量 on the linked item |
| Plan | `<c>工項` (text) | 合約明細工項 | Item name, used to match item to line |
| Plan | `外業預估工天` | 合約明細工項 | Planned workdays. Filled on 307 lines for 外業, **0 for the other three** |
| Item | `工項類別`, `基準數量`, `標準點數`, `對應營業額` | 合約填報工項 | Category, quantity base, standard points, planned points. 對應營業額 is filled on only 297 of 779 |
| Item | `換算係數`, `單位可推導`, `計價權重`, `合約單價` | 合約填報工項 | Conversion to billing quantity, weight, price |
| Done | `完成數量` (外業) | 外業工作單 | Done quantity. 計價數量-back is the billable version (rework gives 0, 業主追加數量 overrides) |
| Done | `計價數量` / `對外計價數量` (內業) | 內業工作單 | Same idea. 重工 gives 0, 業主數量覆寫 overrides |
| Done | `營業額點數` | both | Done points. Filled 143 of 187 外業, 266 of 348 內業 |
| Signal | `本工項剩餘營業額`, ⚠營業額超過工項餘額, ⚠工項不符, ⚠案件不符 | both | Existing over-run and mismatch flags. Reuse them, do not recompute |

Per reportable item: `progress = min(done / 基準數量, 1)`, where done sums linked reports, excludes 是否重工, honours the override fields. Roll up by category with 標準點數 as weight. Over 100% is an anomaly flag.

Two cautions from the field metadata:

1. **Conversion and price formulas take MAX across lines that share a key.** 換算係數 and 合約單價 look up lines by 來源明細唯一鍵 and use `MAX(...)`. Where lines repeat (section 4), the item may read the wrong line's quantity or amount. Do not trust 換算係數 on items in a duplicate group without a check.
2. **Unit labels are unreliable.** 外業單位 is a select whose options are mostly numbers, and 控制單位 and 圖資單位 are number fields. Show quantities with a unit only after verifying it against the 工項 standard. Quantity comparison itself does not need the label.

## 4. What 工編號碼 is, and what it cannot do

- Shape: engineering code or quote number plus 項次, for example the pattern `C115264-1` or `115588-3`. Prefix = the case, suffix = the contract item number.
- The prefix to quote-number relation is clean: across the 78 distinct prefixes, none maps to two quote numbers, and only 1 of 77 quote numbers maps to two prefixes.
- **It is not a unique line key.** 360 distinct codes cover 579 lines. 120 codes repeat across 341 lines. An independent analysis (2026-10-17, `/tmp/lk/agy/report-rule-b.md`) classified the groups: 101 are different sub-items that share a code, 16 are identical copies (36 lines), and 3 are the same item with different quantities (7 lines). So true duplicates are about 19 groups, and the rest is normal sub-item structure. Matching must therefore use code plus category plus item name, never the code alone (decision D2 is now small).
- It identifies the **case** reliably. 78 case prefixes, of which 16 are real 工程確認單 codes (exact), 27 match a quote 工程編號 exactly (25 uniquely). Separately, 51 of the 74 case numbers on the lines match a 報價編號 in the quote table (letter prefix and suffix stripped, so a looser test).

## 5. How the web uses it today, and why it shows so little

`v4_sources.py` assigns a contract line to a project through the link 所屬成案確認單（日報關聯） or an exact normalized 所屬案件 alias, and only when exactly one candidate exists (`v4_sources.py:383`). The native link is filled on **4 of 591 lines**; how many the alias rule covers in the running app was not measured. `source_work_items.py` assigns an item only through its contract line. The 工編號碼 is not used for assignment anywhere in the backend, and the default field projections do not even fetch it or the category quantities (`sources.py:22`).

The code is deliberately conservative here: no fuzzy matching, never pick between duplicates, keep provenance. The new rules below keep those principles.

## 6. Auto-connect design

General rules, all inherited from the existing diagnosis:

- Match on exact normalized codes only (strip spaces and invisible characters, keep suffixes). No name similarity at the case level.
- Exactly one candidate links. Zero or several give `unknown` with a reason. Never pick.
- A derived link is stored in the app with `match_basis` and the rule version, and shows as "derived, source not yet linked". It is never presented as the Lark link.
- Writing the real link back to Lark is a separate, explicit step (section 7, phase 3).

### Rule A: case to contract lines (hop 1)

1. Take the 工編 prefix of each line.
2. If it equals exactly one real 工程確認單 code, assign the line to that case. 16 prefixes qualify now.
3. Otherwise, if it equals exactly one 報價總表 工程編號, assign it to that quote's case (25 unique today). Those cases have no 確認單 yet, so they feed the planning view only.
4. Otherwise leave unassigned with the reason: no match, or several quotes share the code (the earlier diagnosis found 41 duplicated quote numbers and 21 duplicated engineering numbers).

### Rule B: contract line to reportable item (hop 2)

Key: 工編號碼 + 工項類別 (the category has a quantity on the line) + item name found in the line's `<c>工項` text.

Backtest on the 598 links that exist today (truth known). An independent rerun reproduced these counts:

| Outcome | Count |
| --- | ---: |
| Unique and correct | 418 |
| Unique but wrong | 8 |
| Ambiguous (truth is among the candidates) | 66 |
| No candidate | 106 |

So the rule links 70% of known items with 98% precision (418 of 426). The 8 wrong ones come from stale or cross-wired Lark links and renumbered quote codes, so they are partly source errors. Adding exact quantity equality (`基準數量` equals the line's category quantity) removes one wrong match and 9 ambiguous ones, with no correct match lost (427 correct, 7 wrong). **That check only works for items that already have a quantity: all 181 unlinked items show 基準數量 = 0 because the field is a formula over linked lines.** Allowing an empty line quantity when the item quantity is 0 recovers 14 more (441 correct, precision 98.2%). 14 of the 30 ambiguous unlinked items have candidates with identical quantity, so planned quantity is unaffected; 16 differ. Applied to the 181 unlinked items it resolves 117 uniquely, 30 ambiguous, 34 none.

Do not use the plain 來源明細唯一鍵 for this. It is built from different numbers on the two tables (quote number on the line, 工編 prefix on the item), so it disagrees with 454 of the 598 true links.

### Rule C: daily report to reportable item (hop 3)

No rule can work from current data. The two code fields on reports are 外業 可能確認單工作編號 (0 of 187 filled) and 內業 可能的確認單工編 (132 of 348 filled). The 132 content does not resolve: only 14 of 37 distinct values match any quote 工程編號 and none match a contract line. The real fix is at entry:

1. The reporter picks the 合約工項 / 內業工項 from a list. The list must already be limited to the chosen case, so the existing required fields become usable. This needs the form or field setting in Lark.
2. Short term, for rows that still carry a code, offer a proposal list (case match via the quote 工程編號 for the 14), not an automatic link.
3. Until then, report quantities cannot be attributed. The app reports done-side progress as `unknown`, and shows plan-side data only.

## 7. Plan

Each phase is useful alone. Nothing writes to Lark before phase 3.

### Phase 1: Plan side (no Lark change, app only)

- Derive the link by rules A and B in the app's source import, flag `match_basis`, keep `unknown` for the rest. Touches `v4_sources.py` and `source_work_items.py` only through a small separate module so the existing no-guess behaviour stays intact.
- Case page shows, per category: number of contract lines, planned quantity, number of reportable items, how many are linked, how many are ambiguous or unmatched, and the duplicate groups.
- Acceptance: for the 16 real cases, planned quantity per category equals the sum of the lines (checked by hand on three cases), no line is assigned to two cases, ambiguity is shown and never silently resolved.

### Phase 2: Done side, read-only evidence

- Compute item progress and category progress as in section 3 wherever reports are linked. Label each number with its basis (quantity, points) and show `unknown` otherwise.
- Wire the result into the node evidence rules of the earlier plan: 外業, 控制, 圖資 and 報告 nodes use category progress as the main rule. This stays shadow-only: it suggests, and the manager completes.
- Acceptance: compare against what managers say for the cases that have linked reports. Report agreement per node before widening.

### Phase 3: Repair the source (needs your decision, D1 and D3)

- Produce a proposal report for Lark: for each unlinked item the unique candidate line (rule B), and for each line the unique case (rule A). You apply it by import or through a gated write, never silent.
- Set the report entry list per case (rule C step 1) so new reports link themselves.
- After new links appear, re-run phase 2 and retire the derived links that the source now provides.

### Tests

- Rule A and B: unique, none, ambiguous, duplicated quote numbers, suffix variants (`C115264-1` against `115264-1`), invisible characters, the 8 known wrong matches as a regression set.
- Plan arithmetic: sums per category, duplicate groups, rework and override fields.
- Fail-closed: an unlinked report must give `unknown`, never 0% and never done.

## 8. Decisions needed

| ID | Question | Recommendation |
| --- | --- | --- |
| D1 | May the app show derived (not Lark) links on the case page? | Yes, clearly labelled, never counted as source-linked |
| D2 | What do repeated contract lines with the same 工編 mean (120 groups, 341 lines)? Are they additive items, alternatives or quote versions? | Needs your or the finance owner's rule. Until then, show the group and sum nothing across it |
| D3 | Who fixes the report entry (rule C), and when? | Make the list case-limited and required in the Lark form. Without this, no done-side progress exists |
| D4 | Planned workdays for 控制, 圖資 and 報告 are empty. Compute them from quantity divided by the 指標(每日) standard, or leave progress quantity-based? | Quantity-based only. Do not invent workdays |
| D5 | Treat the 8 wrong rule-B matches how? | List for manual review before enabling any write-back |

## 9. Not checked

- The app's live workspace (only code was read). The claim "4 of 591 lines reach a project" is the Lark link count, which the code requires. It is not a count of what the running app shows.
- Whether the 16 real cases are the active ones.
- The 8 wrong matches were not inspected one by one.
- Report dates: the newest 外業 and 內業 cost sheet is still 2026-08-11, so the done side may be stale in any case.
