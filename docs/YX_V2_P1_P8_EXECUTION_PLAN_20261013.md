# YX v2 P1–P8 execution plan (2026-10-13)

Owner: the single Claude commander (parent task `task_6f78140157c0`, continued by `task_ec8184733081`). This plan does not create a second commander. It persists the full P1–P8 plan the owner authorized. It covers what is in flight, who owns which files, which gates block what, and how integration is serialized.

Status at writing: P1 foundations C-STATE and C-ID exist as unaccepted candidates. All P1 feature work and all P2 work are held behind them. P3–P8 are **pending complete spec intake**. No acceptance has been inferred from their titles.

VCC-125 remains a hard gate. Nothing in this plan claims production readiness or complete authorization coverage.

---

## 1. Sources of truth

| What | Where |
|---|---|
| Full P1/P2 interface specs (seven issues, v1.1) | `/Users/vc/Documents/Codex/2026-10-13/task-2/library-handoff/extracted/all-seven-interface-specs.md` |
| Issue → Page mapping | same folder, `issue-id-mapping.json`; reference screenshots `*-actual-reference.jpg` |
| Commander P1/P2 spec and task table | `/Users/vc/orca/workspaces/YXMEEGLE/yx-v2-commander/.runtime/task_6f78140157c0/spec.md`, `tasks.tsv` |
| Linear issue bodies captured at planning time | same folder, `issues/VCC-126..132.{json,md}` |
| Reference site (layout analogue only, never acceptance evidence) | <https://pmsolution.zeabur.app/> |

### Issues and v1.1 interface Pages

| Phase | Issue | Interface | v1.1 spec Page | Reference capture |
|---|---|---|---|---|
| P1 | [VCC-126](https://linear.app/vc-studio/issue/VCC-126/p1-implement-my-work-interface-v11) | My Work | [page_211c06e0…](https://chatgpt.com/space/page_211c06e05fc48191a101ba2ab6df4bd6) | `/` overview, 2026-10-13T13:20:30Z |
| P1 | [VCC-127](https://linear.app/vc-studio/issue/VCC-127/p1-implement-source-health-interface-v11) | Source Health | [page_dc5b32d0…](https://chatgpt.com/space/page_dc5b32d0a4c481919fa215cc51b045c8) | `/sources`, 13:29:21Z |
| P2 | [VCC-128](https://linear.app/vc-studio/issue/VCC-128/p2-implement-manager-overview-interface-v11) | Manager Overview | [page_c753f9a5…](https://chatgpt.com/space/page_c753f9a57fa88191ad7322dc979cf116) | `/` overview, 13:20:30Z |
| P2 | [VCC-129](https://linear.app/vc-studio/issue/VCC-129/p2-implement-confirmation-list-interface-v11) | Confirmation List | [page_bd99af28…](https://chatgpt.com/space/page_bd99af28dedc819182d79eca26869631) | `/reports/r01` raw table, 13:30:24Z |
| P2 | [VCC-130](https://linear.app/vc-studio/issue/VCC-130/p2-implement-case-and-confirmation-detail-interface-v11) | Case and Confirmation Detail | [page_28660d53…](https://chatgpt.com/space/page_28660d5339148191aa0d89a1e3d3bfd8) | `/reports/r01` group drilldown, 13:30:54Z |
| P2 | [VCC-131](https://linear.app/vc-studio/issue/VCC-131/p2-implement-contract-detail-interface-v11) | Contract Detail | [page_c218dc50…](https://chatgpt.com/space/page_c218dc5004608191972a0e02bff5edb2) | `/reports/r01` group drilldown, 13:30:54Z |
| P2 | [VCC-132](https://linear.app/vc-studio/issue/VCC-132/p2-implement-work-item-detail-interface-v11) | Work Item Detail | [page_f6b11a0b…](https://chatgpt.com/space/page_f6b11a0b6bc481918a3af035afb4c6c4) | `/reports/r01` raw table, 13:30:24Z |

Related gates and evidence: [VCC-117](https://linear.app/vc-studio/issue/VCC-117/map-lark-source-fields-and-case-node-relationships) is bounded mapping evidence. [VCC-120](https://linear.app/vc-studio/issue/VCC-120) is the existing connected-data views; compare against it before reimplementing anything. [VCC-113](https://linear.app/vc-studio/issue/VCC-113/reviewfix-frontend-work-overview-my-work-case-overview-case-detail)/114 are earlier review work. [VCC-122](https://linear.app/vc-studio/issue/VCC-122/follow-up-13-contract-item-differences-cause-unverified) covers contract-item differences. [VCC-123](https://linear.app/vc-studio/issue/VCC-123/follow-up-unknown-deadline-provenance) covers deadline provenance. [VCC-125](https://linear.app/vc-studio/issue/VCC-125/vcc-124-follow-up-residual-hidden-id-leaks-on-apiaudit-action-409) is the hard release gate. Shared Pages: [phase approval index](https://chatgpt.com/space/page_0cb44163425c8191bd8d8714d46be8c6), [YX scope and workflow](https://chatgpt.com/space/page_75e46aa59b388191991e5d258b10cb0b), [data-operation plan (background only, not a write contract)](https://chatgpt.com/space/page_f9b4da6a5734819190fd72a208738f49).

---

## 2. Phase map

| Phase | Scope | Status | Gate to start |
|---|---|---|---|
| **P1** | VCC-126 My Work, VCC-127 Source Health, shared contracts C-STATE and C-ID | **In progress**: foundations only | Owner authorization (given) |
| **P2** | VCC-128 Manager Overview, 129 Confirmation List, 130 Case/Confirmation Detail, 131 Contract Detail, 132 Work Item Detail | **Held** | P1-REV accepted, plus source/authorization receipts and cross-review (§5) |
| P3 | — | **Pending complete spec intake** | Full spec text, owner approval, P2 final review |
| P4 | — | **Pending complete spec intake** | Same |
| P5 | — | **Pending complete spec intake** | Same |
| P6 | — | **Pending complete spec intake** | Same |
| P7 | — | **Pending complete spec intake** | Same |
| P8 | — | **Pending complete spec intake** | Same |

P3–P8 rule: no task, worktree, file reservation or acceptance criterion may be created for them until their complete specs are read into a commander task, the same way P1/P2 were. Titles, the reference site, and the "later-phase screen" links in VCC-132 are not specs. VCC-132 itself forbids implementing P3/P4.

---

## 3. Models and roles

| Role | Agent | Model / effort | Uses |
|---|---|---|---|
| Commander (single) | Claude | Opus (`claude-opus-5-5`) | Plans, task specs, dependency gates, ordering integration |
| Claude code changes | Claude | Sonnet 5.5 (`claude-sonnet-5-5`), medium | Logic and view-model modules, remediation |
| Claude reviews / hard contracts | Claude | Opus (`claude-opus-5-5`), high | Independent reviews of Codex-authored code; high-risk access modules |
| Codex code changes and reviews | Codex | `gpt-6.1-sol`, medium | Logic modules, reconciliation tests, independent reviews of Claude-authored code |
| Simple isolated UI | AGY (Antigravity) | agent default | Presentational `.tsx`/`.css` built on an accepted view model |
| Integration owner | Claude | Sonnet 5.5, medium | **Only** writer of the shared hub files; serial merges |

This supersedes the older `tasks.tsv` model column (`codex/high`, `claude-opus-5-5/high` for every coder). Owner column assignments in `tasks.tsv` stay as they are. Both Codex and Claude do real logic/coding work, and neither model is used only to review.

**Review pairing:** the reviewer always comes from the other model family than the author. Codex reviews Claude-authored code, and Claude Opus reviews Codex-authored code. A review covers one exact SHA. Any later commit invalidates it.

---

## 4. Ownership, worktrees and integration

### Shared hub files: a single writer

Only the integration owner (`P1-INT`, later `P2-INT`, in `/Users/vc/orca/workspaces/YXMEEGLE/yx-v2` on `ava-apple/yx-v2`) edits these files:

`backend/app.py`, `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/AppShell.tsx`, shared CSS, `scripts/local_ci.sh`, `frontend/package.json`.

Feature workers add new files only. The exclusive file list for each task is in `tasks.tsv`, and no file appears in two tasks.

### Integration rule

1. Each worker commits on its own branch in its own child worktree and reports its exact SHA.
2. An independent cross-model review of that exact SHA passes. Findings get fixed, and the fix gets re-reviewed.
3. The integration owner merges into `ava-apple/yx-v2` one candidate at a time and runs `scripts/local_ci.sh` after each merge. A red result stops the queue.
4. P2 merge order: 129, 130, 131, 132, 128, NAV, UI-a, UI-b, then E2E.
5. Nothing is pushed, deployed or sent externally without a separate owner instruction.

### Current P1 state (verified 2026-10-13)

| Item | Branch / worktree | Exact SHA | Author | Review | State |
|---|---|---|---|---|---|
| P1-C1 C-STATE | `ava-apple/p1-c1` / `p1-c1` | `727f386e94a2ffd21f22264187f52f254002dd55` | Claude Opus | superseded | base of hardening |
| P1-C1 hardening | `ava-apple/p1-c1-hardening` / `p1-c1-hardening` | `1da39c3ec65509ad08561e8f74675eebb6a401db` | Claude Sonnet | `task_3717b15b9345`: **changes requested** (msg_40df7bf9ff4b) | needs remediation |
| P1-C2 C-ID | `ava-apple/p1-c2` / `p1-c2` | `f24889238669794ef356258a0ceb08f6086544f4` | Codex | `task_77ca4877621f` (Claude Opus): PASS with test gaps F1–F8 | superseded by hardening |
| P1-C2 hardening | `ava-apple/p1-c2-hardening` / `p1-c2-hardening` | `44d93b4293f2c1160e6be97280b671c6fe9362da` | Codex (`task_98b8b9481f1d`) | **pending**; coordinator reran 30 tests (pass); owner says C-ID "seems wrong" | needs independent Opus review + contract decisions (§7) |

C1 review defects to fix (from msg_40df7bf9ff4b):
1. `frontend/src/dataState.ts:52-64`: `dataStateCount`/`describeDataState` don't validate direct inputs. Duplicate states, incompatible combinations and empty states with a count all leak the count. Examples: `['partial','partial']`+7, `['partial','complete_empty']`+7, `['complete_empty']`+7.
2. `frontend/src/dataState.ts:37-46,54-64`: sparse arrays (`Array(1)`) pass `every`, so the count leaks.

### Child tasks created by this plan

The tasks are disjoint, and none edits the code of another in-flight task. Exact Orca task IDs, worktrees and models are recorded in the commander report and in `.runtime/task_ec8184733081/children.tsv` in the plan worktree.

Orca Run `run_67505fe63eb0`. Worktrees live under `/Users/vc/orca/workspaces/YXMEEGLE/`; setup hooks were skipped.

| ID | Orca task / dispatch | Agent / model | Worktree / branch (base) | Exclusive files | Purpose |
|---|---|---|---|---|---|
| P1-C1-REM | `task_66025376e1f5` / `ctx_3afab6ecf1f8` | Claude Sonnet 5.5, medium | `p1-c1-remediation` / `ava-apple/p1-c1-remediation` (from `1da39c3`) | `frontend/src/dataState.ts`, `frontend/test-data-state.mjs` (backend `data_state.py` and its test only if a parity gap is proven) | Fix review findings 1–2 with regressions that fail first |
| P1-C2-REV | `task_ebfd09513665` / `ctx_99fa333231e4` | Claude Opus, high | `p1-c2-opus-review` / `ava-apple/p1-c2-opus-review` (from `44d93b4`) | read-only | Independent review of exact `44d93b4`; confirm or sharpen the §7 questions; no fixes |
| P1-C1-REM-REV | created once P1-C1-REM reports | Codex `gpt-6.1-sol`, medium | review worktree at the P1-C1-REM SHA | read-only | Cross-model review of the remediation SHA |

**Results (2026-10-13, all three settled, terminals released, worktrees kept):**

- **P1-C1-REM** committed `0ed93e7609ab689e9ef5c22143fbc3b0be8fc470` on `ava-apple/p1-c1-remediation`. It changes only the two allowed files: direct helpers now reparse through `parseDataState`, and sparse or empty state arrays are rejected. Checks: 180 frontend checks pass, 18 backend tests pass, strict tsc passes. One intended behavior change: a direct `{states:['complete_empty']}` with no count now reads 0, which matches the backend.
- **P1-C1-REM-REV** (Codex): **PASS, no findings** on `0ed93e7`. Report: `/Users/vc/orca/workspaces/YXMEEGLE/worker-evidence/task_3a4624cbce68/review.md`. 41 backend/frontend envelope comparisons agree, and reverting F1 or F2 fails the tests. **G-C1 now needs only coordinator acceptance of `0ed93e7`.**
- **P1-C2-REV** (Claude Opus) on `44d93b4`: **DESIGN-DECISION-REQUIRED.** Report: `/Users/vc/orca/workspaces/YXMEEGLE/worker-evidence/task_ebfd09513665/review.md`.
  - The hardening itself passes: F1–F4 are fixed, 30/30 tests pass, and it has minor items N1–N4.
  - All eight §7 questions are confirmed. C-ID is a one-target, record-keyed resolver with no viewer context. It runs parallel to identity the repo already has: typed one-to-many native relations (`v4_sources.RELATIONS`/`native_records`, `source_entities.update_entities`, `source_work_items`) and the existing `project_id`/`assignments` case identity. As built, it cannot serve the P2 chains.
  - The `/` key collision also affects `source_id` and would break `source_work_items.py:27`.
  - **G-C2 is blocked on the owner's decisions 1–9 in that report.** No C-ID coder is started until they are made.

No other coder is created for C1 or C2. Remaining P1 rows in `tasks.tsv` (127B1/B2/B3, 127F1/F2, 126B1/B2, 126F1/F2, INT, REV) are **held** until their gates in §5 pass. AGY has no authorized task yet because both of its UI tasks depend on accepted view models (127F1, 126F1), and those depend on accepted C-STATE.

---

## 5. Dependency gates

| Gate | Unblocks | Condition (all required) |
|---|---|---|
| G-C1 | 127F1, 126F1 (then AGY 127F2, 126F2) | P1-C1-REM SHA passes Codex review; coordinator accepts C-STATE |
| G-C2 | 127B3 | §7 questions answered by coordinator/owner; Opus review of the resulting C-ID SHA passes; coordinator accepts C-ID |
| G-C1+C2 | 127B1, 126B1 | G-C1 and G-C2 |
| G-RCPT | any field/edge shown as "mapped/accepted" | Supplied VCC-117 same-version source/schema/permission receipt per field and native edge. Absent receipt → `unlocated`; no invented IDs |
| G-DIAG | 127B2 diagnostic layer | Coordinator confirms which **existing** grant is the diagnostic role (default proposal: `company_admin_grant`; not assumed). Otherwise ordinary page-state view only |
| G-P1 | P1-INT | All P1 rows reviewed by the other model family at exact SHA |
| G-P1-REV | **all of P2** | P1-INT SHA green on `scripts/local_ci.sh`; cross-review passes; coordinator accepts C-STATE + C-ID; G-RCPT receipts exist for the sources P2 consumes |
| G-AMT | P2-131B amount display | Separate approval to show contract amounts (VCC-120 omitted them; `QUOTE_FINANCE` visibility must be re-verified) |
| G-RCODE | P2-132B work orders / node instances | R01/02/09/10 work-order and node-instance models verified; until then those sections render `unlocated` with a Source Health link |
| G-VCC125 | any production release | VCC-125 closed; never waived by this plan |

Stop and escalate if any of these comes up: a GET endpoint not listed in `tasks.tsv`, a change to an existing response shape, a missing diagnostic capability, contract amounts, or any field/edge without a receipt.

---

## 6. Per-task delivery and gates

Each worker's `worker_done` and report must contain the items below. A missing item counts as a failed check, not a skipped one.

1. **Deployed/candidate commit:** exact SHA and branch. For UI work, also the exact SHA running in the isolated review instance.
2. **What changed:** changed-file list (must match the exclusive set) and one paragraph on behavior.
3. **Tests:** named tests from `tasks.tsv`, with pass/fail/blocked/not-run recorded separately. Include failing-first evidence for fixes, plus mutation/negative checks for state and identity guards.
4. **Review:** reviewer identity (other model family), reviewed SHA and verdict. A later commit invalidates the review.
5. **Staging/browser (UI-facing rows only).** Run the isolated demo instance: SQLite plus Vite on scratch ports, never the shared worktree or production. Attach one screenshot **per interface** at desktop (≥1180 px) and narrow (≤600 px) widths covering:
   - loading, complete-empty, filtered-empty, unlocated, forbidden, read failure, partial, stale, and unknown.
   - keyboard focus.
   - the drawer-below layout on narrow screens.

   Screenshots carry no personnel or contact data, and synthetic numbers must agree with each other.
6. **Remaining work:** what is still open, including gates the task did not cover.
7. **Specific owner decision:** the single decision the owner must make next for this item, or "none".

Final gates (FINAL-REV): non-authors review the exact final SHA, `scripts/local_ci.sh` passes plus targeted authorization/UI regressions, and the VCC-125 gate is restated. Production deploy is out of scope.

---

## 7. P1-C2 (C-ID) contract questions for the coordinator

These are open design questions. The plan does not guess an answer, and no worker may implement a mapping until each one is answered. Together they may explain the owner's sense that C-ID "seems wrong". The Opus review (P1-C2-REV) is asked to confirm or refine them against `44d93b4`.

1. **Edge grain.** The registry is one record key → one target key (`resolve_edge`). The specs need edges typed by native **source field**, with target table, direction, cardinality and permission boundary (shared gate 2). Today, two verified edges from one record (for example confirmation → case and confirmation → contract line) return `ambiguous_verified_edges`. Should edges be keyed by `(source_key, source_field)` or by edge type?
2. **Cardinality.** The 130/131/132 chains are one-to-many (case → lines → work items). The current contract can only resolve to one target and has no child → parent reverse lookup. Which edges are one-to-one, and is reverse navigation part of C-ID or a separate module?
3. **Stable business identity vs record key.** The specs separate "source context + record_id" (row identity) from "independently verified stable business identities" (grouping, for example a canonical case across V3/V4). C-ID only maps record key → record key. What is the stable case identity, and who issues it?
4. **Native link fields.** `source_entities.update_entities` already resolves native Lark link fields (`native_records`), and C-ID ignores them. Should a native relation ID count as an edge needing an external receipt, or as verified by nature subject to a per-edge receipt? VCC-132 says "use native relationship IDs".
5. **Version.** `SourceRef.version` is not part of `source_key` (`base/table/record_id`). VCC-129 says "source context + record_id identifies one source record version". Does "version" mean V3/V4 source generation (different base, so already distinct) or a revision of one record? If it means a revision, two versions collide on one key.
6. **Receipt format.** The `verification_status`/`verified_by`/`evidence_ref` strings have no schema link to VCC-117 receipts, and no receipts are in the repo. What is the receipt file format and location, and who is allowed to mark an edge `independently_verified`?
7. **Permission boundary.** `resolve_edge` takes no viewer context, but VCC-130/132 require "missing" and "forbidden" relations to stay distinct without leaking the forbidden target. Is that C-ID's job or the caller's (`source_case_policy` / `case_redaction`)?
8. **Key escaping.** `entity_id` joins with `/` and does not escape it (review F7). Should we accept that Lark tokens contain no `/`, or harden the key?

---

## 8. PMSolution reference: what to borrow and what not

The reference site <https://pmsolution.zeabur.app/> is a layout analogue only. Its numbers are not test constants, and its screens prove no YX schema, binding or access.

| Topic | Borrow | Do not borrow |
|---|---|---|
| Comparison fields | Original vs revised amount side by side (131), plan vs actual for the **same item, unit and period** (132), quantity, points, check result, exception | Summing original+revised, totalling mixed units, treating points as % complete, using document counts in place of plan/actual, any new difference formula |
| Sort | Columns sort ascending/descending/clear. Sort by source-modified time descending only if that time is verified, otherwise by source order plus stable ID. Detail evidence sorts date descending plus stable ID, and Source Health puts attention rows first | Treating retrieval time as business-update time |
| Filter | Version, PM, admission, deadline range, source/status filters, Reset Filters, column chooser. Filters, cursor, sort and columns are preserved both ways | Reusing the reference **reporting week** as the to-do or case-visibility filter. Old unfinished work always stays visible |
| Dashboard semantics | The snapshot (stock at a timestamp) and weekly activity (events in a period) stay separate. Each KPI equals its drilldown denominator on the same set. Undefined cards show as unavailable with a reason. Zero is shown only for a complete authorized population | Adding overlapping cards together, totalling R01/R10 or R02/R03/R09 views, routine trend charts, overdue rate |
| Native relationship navigation | Confirmation → contract line → work item → work order / node instance, followed through native IDs, with breadcrumbs and a return route to the exact context. Missing edges show as an explicit unresolved row | Joins by name, case number or suffix, making a report group/day into a case, a collapsed or extra contract node |
| UI/UX | Fixed nav, data-scope and freshness header, sticky identity columns, dense table, a selection-only drawer (below the table on narrow screens), text status labels, keyboard focus, footer totals (matching / loaded / authorized), real server pagination | Local SOP write/complete/approve controls, technical IDs as primary columns, large coverage cards, color-only status |

---

## 9. Safe cleanup rules

- Do not delete any worktree, branch, `.runtime` evidence, stash or report while any task, review or integration still references it. That includes `p1-c1*`, `p1-c2*`, `yx-v2*`, `_reports`, `worker-evidence`, and the `library-handoff` folder.
- Cleanup needs an explicit owner instruction for each item. This plan performs none.
- Before any approved cleanup:
  - Check that `git status` is clean.
  - Check that the branch is merged into `ava-apple/yx-v2`, or archived as a patch with its SHA recorded.
  - Check that no Orca dispatch is live on that worktree.
- Settled Orca worker terminals are released only after their `worker_done` is accepted. Worktrees stay in place.
- Never use bare `git stash`. Never force-push. Never rewrite a reviewed SHA.

---

## 10. Out of scope (unchanged)

The following are out of scope:
- Lark/Base writes.
- New scopes, credentials, roles or grants.
- Approval or SOP-completion shortcuts.
- New formulas.
- Dependency, schema or runtime/security changes.
- Freshness-ceiling increases.
- Production deploy.
- P3–P8 implementation.
- The VCC-122, VCC-123 and VCC-125 fixes.
