# YX v2 P1–P8 execution plan (2026-10-13, rev 3.7 of 2026-10-14)

Owner: the single Claude commander. Parent task `task_6f78140157c0`, continued by `task_ec8184733081` (P1/P2 planning and reviews) then by `task_67bb22a5d7b6` (P1–P8 execution), then by `task_97a32b5dcb2e` (P1 continuation), and now by `task_7bab31d03ad7` (P2 onward, one phase at a time). This plan does not create a second commander. Revision 3 adds the complete P3–P8 specs and issue IDs, records the C-ID architecture decisions, and replaces the old no-push/no-staging rule with the owner's serial merge, push and staging authorization (§4).

**Rev 3.7 owner direction (2026-10-14, base `ava-apple/yx-v2` = `7ae4a9d47a85dc2a35b0f994a3eced7e06ab3f41`, clean, equal to `origin`):**
- **P2 starts now without staging acceptance.** G-P1-REV no longer blocks P2; P1 stays integrated with its documented gaps (§4.4d). P3 starts only after P2 acceptance, then P4–P8 one phase at a time, each after the prior phase passes.
- The Opus commander (`task_7bab31d03ad7`) plans and performs exact-SHA cross-model reviews only. It writes no application code.
- Real coding goes to **both** Claude Sonnet `claude-sonnet-5-5` medium and Codex `gpt-6.1-sol` medium, with disjoint file ownership in separate Orca-managed child worktrees. AGY is used only for simple presentational UI after contracts settle.
- **The root coordinator owns serial integration into `ava-apple/yx-v2`** (and any push). Children and the commander commit locally only and never push, merge or deploy. This supersedes the commander-merge/push clauses of §4.2.
- Deployment and cleanup are on hold. Every worktree and all evidence are preserved. Staging (§10, G-STG) is not a precondition for any phase in this continuation.
- Unchanged: Lark read-only, no new scopes/credentials/roles/grants/permissions, no guessed relationship/formula/mapping, field allowlists and unknown-versus-zero preserved, contract amounts hidden (G-AMT), VCC-125 open, no authorization-complete or release claim.
- Review budget: one cross-model review per meaningful change; delta-only re-review for fixes; one focused-test run plus one build/type pass per integration; no repeated broad reviews.
- P2 wave 1 children: §4.6.

**Status at rev 3.3 (2026-10-14, `ava-apple/yx-v2` = `416e1bdff6bf4ffaa1a2e54c956f7fab0efe6c52`):**
- C-STATE, C-ID v2, the 127F1 Source Health view model and the 126F1 My Work view model are integrated. **None of them is wired to a route yet** (§4.4b). P1 interfaces are therefore not delivered; only helper/view-model artifacts exist.
- In flight (§4.4c): the C-ID N1/N2 boundary fix, the 127B1 and 126B1 backend read models, and the AGY 127F2/126F2 presentational components.
- P2 is held until G-P1-REV passes. P3–P8 are specified but out of scope for this continuation.
- Staging: the parent has verified that its authenticated cloud browser can re-upload a reviewed project folder to the existing staging service. The old CLI-only blocker is retired (§10). The commander prepares the exact-SHA artifact; the parent performs the upload.

VCC-125 remains a hard gate. Nothing in this plan claims production readiness or complete authorization coverage.

---

## 1. Sources of truth

| What | Where |
|---|---|
| P1/P2 interface specs (7 issues, v1.1) | `/Users/vc/Documents/Codex/2026-10-13/task-2/library-handoff/extracted/all-seven-interface-specs.md` (94885 bytes, SHA256 `2fc0ccf1201d13624dab40d4dab72206fb981306391eb1fcc053f2284c156c60`, re-read 2026-10-14). The `local_spec` paths inside `issue-id-mapping.json` point to an unreadable `/workspace/scratch/...` location; this extracted file is the readable authority. Owner-only ChatGPT Pages are not used to infer anything. |
| P1/P2 issue → Page map and screenshots | same folder: `issue-id-mapping.json`, `*-actual-reference.jpg` |
| P3–P8 interface specs (14 interfaces, v1.1) | `/Users/vc/Documents/Codex/2026-10-13/task-2/library-handoff/p3-p8-extracted/all-fourteen-interface-specs.md` (per-interface `*-spec.md` are identical copies) |
| P3–P8 bundle | `yx-p3-p8-interface-handoff-20261013.zip`, SHA256 `37f928da7804a2d741a0c7f370b445dd38c5f697a3cf5ddfd9cad47c36ae1bae`, 820436 bytes, version 0. Hash and size re-verified by the commander on 2026-10-13. |
| P3–P8 map, image provenance | `document-issue-map.json` (its issue IDs are null for 13 of 14 at snapshot), `manifest.json` (image SHA-256/capture/dimensions), `bundle-manifest.json` |
| Commander P1/P2 spec and task table | `/Users/vc/orca/workspaces/YXMEEGLE/yx-v2-commander/.runtime/task_6f78140157c0/spec.md`, `tasks.tsv` |
| Child records for this continuation | `.runtime/task_67bb22a5d7b6/children.tsv` and `spec-*.txt` in the plan worktree |
| Reference site | <https://pmsolution.zeabur.app/>. Used only as visual and UI/UX reference evidence. It is never authority for formulas, data, permissions, schema or YX bindings, and its numbers are never test constants. |

### 1.1 Issues, Pages and reference captures (all 21 verified in Linear, status Backlog, 2026-10-13)

The commander verified the 14 P3–P8 IDs with a read-only Linear listing. Titles match the map's interface names. They were added here, not recreated. All 14 P3–P8 screenshots were pixel-inspected by the coordinator. The Document/Delivery Workspace and R03 captures are one reused image (same SHA-256 `c1ca3e3f013a…`); the manifest documents that reuse as a nearest analogue.

| Phase | Issue | Interface | v1.1 spec Page | Reference URL · capture (UTC) | Screenshot file (sha256 prefix) |
|---|---|---|---|---|---|
| P1 | [VCC-126](https://linear.app/vc-studio/issue/VCC-126/p1-implement-my-work-interface-v11) | My Work | [page_211c06e0…](https://chatgpt.com/space/page_211c06e05fc48191a101ba2ab6df4bd6) | `/` · 13:20:30Z | P1/P2 bundle |
| P1 | [VCC-127](https://linear.app/vc-studio/issue/VCC-127/p1-implement-source-health-interface-v11) | Source Health | [page_dc5b32d0…](https://chatgpt.com/space/page_dc5b32d0a4c481919fa215cc51b045c8) | `/sources` · 13:29:21Z | P1/P2 bundle |
| P2 | [VCC-128](https://linear.app/vc-studio/issue/VCC-128/p2-implement-manager-overview-interface-v11) | Manager Overview | [page_c753f9a5…](https://chatgpt.com/space/page_c753f9a57fa88191ad7322dc979cf116) | `/` · 13:20:30Z | P1/P2 bundle |
| P2 | [VCC-129](https://linear.app/vc-studio/issue/VCC-129/p2-implement-confirmation-list-interface-v11) | Confirmation List | [page_bd99af28…](https://chatgpt.com/space/page_bd99af28dedc819182d79eca26869631) | `/reports/r01` raw · 13:30:24Z | P1/P2 bundle |
| P2 | [VCC-130](https://linear.app/vc-studio/issue/VCC-130/p2-implement-case-and-confirmation-detail-interface-v11) | Case and Confirmation Detail | [page_28660d53…](https://chatgpt.com/space/page_28660d5339148191aa0d89a1e3d3bfd8) | `/reports/r01` drilldown · 13:30:54Z | P1/P2 bundle |
| P2 | [VCC-131](https://linear.app/vc-studio/issue/VCC-131/p2-implement-contract-detail-interface-v11) | Contract Detail | [page_c218dc50…](https://chatgpt.com/space/page_c218dc5004608191972a0e02bff5edb2) | `/reports/r01` drilldown · 13:30:54Z | P1/P2 bundle |
| P2 | [VCC-132](https://linear.app/vc-studio/issue/VCC-132/p2-implement-work-item-detail-interface-v11) | Work Item Detail | [page_f6b11a0b…](https://chatgpt.com/space/page_f6b11a0b6bc481918a3af035afb4c6c4) | `/reports/r01` raw · 13:30:24Z | P1/P2 bundle |
| P3 | [VCC-133](https://linear.app/vc-studio/issue/VCC-133/p3-implement-document-and-delivery-workspace-interface-v11) | Document and Delivery Workspace | [page_f032f426…](https://chatgpt.com/space/page_f032f426e8548191b62d9f8add891df3) | `/reports/r03` · 13:22:23.365Z | `document-delivery-workspace-actual-reference.jpg` (c1ca3e3f013a) |
| P3 | [VCC-134](https://linear.app/vc-studio/issue/VCC-134/p3-implement-r03-report-quality-review-interface-v11) | R03 Report Quality Review | [page_cb729390…](https://chatgpt.com/space/page_cb72939040108191af74db09808b9413) | `/reports/r03` · 13:22:23.365Z | `r03-report-quality-actual-reference.jpg` (c1ca3e3f013a) |
| P4 | [VCC-135](https://linear.app/vc-studio/issue/VCC-135/p4-implement-r01-field-quality-review-interface-v11) | R01 Field Quality Review | [page_6c616efe…](https://chatgpt.com/space/page_6c616efe9424819189be1e879c26cb14) | `/reports/r01` · 13:21:10.105Z | `R01-actual-reference.jpg` (3a0c94580d5c) |
| P4 | [VCC-136](https://linear.app/vc-studio/issue/VCC-136/p4-implement-r02-internal-quality-review-interface-v11) | R02 Internal Quality Review | [page_3ce4f194…](https://chatgpt.com/space/page_3ce4f1944c3881918b94f104f33cfa84) | `/reports/r02` · 13:21:38.725Z | `R02-actual-reference.jpg` (918f58630bec) |
| P4 | [VCC-137](https://linear.app/vc-studio/issue/VCC-137/p4-implement-r09-internal-plan-versus-actual-interface-v11) | R09 Internal Plan vs Actual | [page_e3d337c8…](https://chatgpt.com/space/page_e3d337c87d1c8191b1c698386ea71199) | `/reports/r09` · 13:27:33.621Z | `R09-actual-reference.jpg` (ff01e4d62df7) |
| P4 | [VCC-138](https://linear.app/vc-studio/issue/VCC-138/p4-implement-r10-field-plan-versus-actual-interface-v11) | R10 Field Plan vs Actual | [page_d8e957c3…](https://chatgpt.com/space/page_d8e957c3546881919b60bd4f13d66592) | `/reports/r10` · 13:28:04.066Z | `R10-actual-reference.jpg` (e538db3384d6) |
| P4 | [VCC-139](https://linear.app/vc-studio/issue/VCC-139/p4-implement-r11-administrative-reporting-interface-v11) | R11 Administrative Reporting | [page_f749e875…](https://chatgpt.com/space/page_f749e8757dec8191ac0312e39deb0d95) | `/reports/r11` · 13:28:40.598Z | `R11-actual-reference.jpg` (d8a0bdbd4418) |
| P5 | [VCC-140](https://linear.app/vc-studio/issue/VCC-140/p5-implement-r05-business-quotations-interface-v11) | R05 Business Quotations | [page_92847e19…](https://chatgpt.com/space/page_92847e192714819195c5adef5342bf1f) | `/reports/r05` · 13:23:22.347Z | `r05-actual-reference.jpg` (462294dbaa28) |
| P5 | [VCC-141](https://linear.app/vc-studio/issue/VCC-141/p5-implement-r06-billing-source-detail-interface-v11) | R06 Billing Source Detail | [page_900b4bfa…](https://chatgpt.com/space/page_900b4bfaca808191b78018f3a6eb9bfa) | `/reports/r06` · 13:23:45.703Z | `r06-actual-reference.jpg` (826cc32b72de) |
| P6 | [VCC-142](https://linear.app/vc-studio/issue/VCC-142/p6-implement-r07-asset-workspace-interface-v11) | R07 Asset Workspace | [page_8783a3f5…](https://chatgpt.com/space/page_8783a3f508c88191966336635e3babbc) | `/reports/r07` · 13:24:17.646Z | `r07-actual-reference.jpg` (3291f5dd1c26) |
| P6 | [VCC-143](https://linear.app/vc-studio/issue/VCC-143/p6-implement-asset-detail-interface-v11) | Asset Detail | [page_49ee2cfa…](https://chatgpt.com/space/page_49ee2cfadc308191b423fd4b6c73e65a) | `/reports/r07` · 13:25:48.997Z | `asset-detail-actual-reference.jpg` (f6a25b33391b) |
| P7 | [VCC-144](https://linear.app/vc-studio/issue/VCC-144/p7-implement-client-directory-and-detail-interface-v11) | Client Directory and Detail | [page_0bf6c5a0…](https://chatgpt.com/space/page_0bf6c5a0b12c8191abd46c5ad7e56cad) | `/reports/r08` · 13:26:53.746Z | `a21-actual-reference.jpg` (2a7e068da823) |
| P7 | [VCC-145](https://linear.app/vc-studio/issue/VCC-145/p7-implement-r08-client-contact-activity-interface-v11) | R08 Client Contact Activity | [page_50473aee…](https://chatgpt.com/space/page_50473aee774c81918e0c4adadb2d0891) | `/reports/r08` · 13:26:16.913Z | `a22-actual-reference.jpg` (4163035926da) |
| P8 | [VCC-146](https://linear.app/vc-studio/issue/VCC-146/p8-implement-r04-authorized-hr-reporting-interface-v11) | R04 Authorized HR Reporting | [page_433dc99c…](https://chatgpt.com/space/page_433dc99cc3448191b7a164efdf189091) | `/reports/r04` · 13:22:57.237Z | `a23-actual-reference.jpg` (f05e42f70dd7) |

All reference captures were taken at a 1180 × 757 viewport before the approved privacy crop.

Related gates and evidence:
- [VCC-117](https://linear.app/vc-studio/issue/VCC-117/map-lark-source-fields-and-case-node-relationships): bounded mapping evidence. Its receipts are not in the repo.
- [VCC-120](https://linear.app/vc-studio/issue/VCC-120): existing connected-data views. Compare against it before reimplementing anything.
- [VCC-121](https://linear.app/vc-studio/issue/VCC-121/follow-up-535-unresolved-reports-42-attachments-unlinked-to-cases): unresolved report/attachment links. Discovery gap for P3.
- [VCC-122](https://linear.app/vc-studio/issue/VCC-122/follow-up-13-contract-item-differences-cause-unverified) and [VCC-123](https://linear.app/vc-studio/issue/VCC-123/follow-up-unknown-deadline-provenance).
- [VCC-125](https://linear.app/vc-studio/issue/VCC-125/vcc-124-follow-up-residual-hidden-id-leaks-on-apiaudit-action-409): hard release gate.

Shared Pages: [phase index](https://chatgpt.com/space/page_0cb44163425c8191bd8d8714d46be8c6), [YX scope and workflow](https://chatgpt.com/space/page_75e46aa59b388191991e5d258b10cb0b), [data-operation plan (background only, not a write contract)](https://chatgpt.com/space/page_f9b4da6a5734819190fd72a208738f49).

---

## 2. Phase map and strictly sequential gates

| Phase | Scope | Status | Starts only after |
|---|---|---|---|
| **P1** | VCC-126, VCC-127, C-STATE, C-ID | **Integrated with documented gaps** (§4.4d) | Owner authorization (given) |
| **P2** | VCC-128..132 | **In progress** (rev 3.7, wave 1 §4.6) | Owner direction 2026-10-14: starts now without staging acceptance |
| **P3** | VCC-133, VCC-134 | Specified, not dispatched | P2 accepted (integration + real tests + independent review + responsive browser) |
| **P4** | VCC-135..139 | Specified, not dispatched | P3 accepted |
| **P5** | VCC-140, VCC-141 | Specified, not dispatched | P4 accepted |
| **P6** | VCC-142, VCC-143 | Specified, not dispatched | P5 accepted |
| **P7** | VCC-144, VCC-145 | Specified, not dispatched | P6 accepted |
| **P8** | VCC-146 | Specified, not dispatched | P7 accepted |

The full approved specs are authoritative, so Linear bookkeeping is not a precondition for starting a phase.

Within a phase, disjoint work runs in parallel. No coding task, worktree or file reservation for phase N+1 is created before phase N is accepted. Plan and spec analysis may proceed earlier.

A blocked source, grant or undefined business rule stays explicitly blocked or deferred with a visible reason. It is never labelled accepted to advance a phase. A phase may be accepted with documented, spec-permitted gaps: the safe UI, explicit `unlocated`, and calculations shown as unavailable.

---

## 3. Models and roles

| Role | Agent / model / effort | Uses |
|---|---|---|
| Commander (single) | Claude Opus `claude-opus-5-5` | Plan, specs, gates, architecture decisions from the specs, integration order, reports |
| Logic and coding | Codex `gpt-6.1-sol`, medium, **and** Claude Sonnet `claude-sonnet-5-5`, medium | Backend read models, view models, reconciliation tests. Both families get real coding rows in every phase. |
| Plans and reviews only | Claude Opus `claude-opus-5-5`, medium (high before rev 3.3) | Planning and independent review of Codex-authored SHAs. **Opus writes no code**: per the owner's preference, relayed by the coordinator at 15:28Z, code changes use Claude Sonnet 5.5 medium, including hard identity, access and redaction contracts. |
| Reviews of Claude-authored code | Codex `gpt-6.1-sol`, medium | Independent review of Claude-authored SHAs |
| Simple isolated UI | AGY (Antigravity), agent default | Presentational `.tsx`/`.css`, only after the view model is reviewed |
| Integration | Commander, in `/Users/vc/orca/workspaces/YXMEEGLE/yx-v2` | The only writer of the shared hub files. Serial merges. |

Rules:
- **Review pairing:** the reviewer always comes from the other model family. A review covers one exact SHA, and any later commit invalidates it.
- **Launch receipts:** each `worker-start` JSON records the requested and effective agent/model/effort, and a copy is kept in `.runtime/task_67bb22a5d7b6/start-*.json`. If a requested configuration is unavailable, report it; never substitute silently.

---

## 4. Ownership, integration, push and staging

### 4.1 Shared hub files: single writer

Only the integration owner edits these files:
- `backend/app.py`
- `frontend/src/App.tsx`, `api.ts`, `types.ts`, `AppShell.tsx`
- shared CSS
- `scripts/local_ci.sh`
- `frontend/package.json`

Feature workers add new files only, and each task's file set is exclusive. Phase N file sets are fixed at phase start against the then-current `yx-v2` HEAD, after inspecting real paths. §8 lists the proposed names.

### 4.2 Integration, push and staging rule (replaces the rev 1–2 "nothing pushed/deployed" clause)

The owner now expressly authorizes the following:

1. Each worker commits in its own child worktree, branched from the **newest verified `ava-apple/yx-v2`**, and reports its exact SHA.
2. An independent cross-model review of that exact SHA passes. Findings are fixed, and the fix is re-reviewed.
3. The commander merges into `ava-apple/yx-v2` **serially, one candidate at a time**. Each merge is `--no-ff` and keeps reviewed SHAs (no rebase). After every merge, `scripts/local_ci.sh` runs on the result. A red result stops the queue. After a conflict resolution, the affected checks and the review rerun.
4. After each independently accepted stage, the commander pushes `ava-apple/yx-v2` to `origin` with a normal push, never a force push. The commander records the local SHA and the `git ls-remote` remote SHA.
5. After each accepted stage, the commander prepares the exact-SHA staging artifact, and the parent re-uploads it to the **verified existing Zeabur staging service** (§10). The record contains:
   - source SHA;
   - build/stage inventory hash;
   - deployed SHA;
   - `/api/health`;
   - authenticated browser evidence.

   If the upload or the post-upload verification fails, the code stage stays ready, and the exact blocker is reported. No credential, scope or service is created or changed.
6. **Never:** a production deploy, a merge to or push of `ava-apple/yx-company-system`, a force push, or rewriting a reviewed SHA.
7. P2 merge order: 129, 130, 131, 132, 128, NAV, UI-a, UI-b, E2E. Later phases use the order given in §8.

### 4.3 Current state (verified 2026-10-13, rev 3)

| Item | Branch / worktree | Exact SHA | Author | Review | State |
|---|---|---|---|---|---|
| P1-C1 C-STATE (remediated) | `ava-apple/p1-c1-remediation` | `0ed93e7609ab689e9ef5c22143fbc3b0be8fc470` | Claude Sonnet (`task_66025376e1f5`) | Codex `task_3a4624cbce68`: **PASS, no findings** | **Accepted, integrated** |
| `yx-v2` integration | `ava-apple/yx-v2` / `yx-v2` | `69f7d4add1d19dc23bb93a1a2fa062858e8d324a` | commander merge of `0ed93e7` onto `6ab9b06` | covered by the C-STATE review (merge only adds the 4 C-STATE files) | `scripts/local_ci.sh` **exit 0**: 3050 passed, 20 skipped, 1 xfailed, all frontend checks passed. Log: `worker-evidence/task_67bb22a5d7b6/local_ci_69f7d4a.log` |
| P1-C2 C-ID hardening | `ava-apple/p1-c2-hardening` | `44d93b4293f2c1160e6be97280b671c6fe9362da` | Codex (`task_98b8b9481f1d`) | Opus `task_ebfd09513665`: hardening PASS, **not fit for P2** (design) | superseded by C2-V2 |
| P1-C2-V2 base | `ava-apple/p1-c2-v2` / `p1-c2-v2` | `799fe4a432077c848daaa998d98a0ce329a45615` (= `69f7d4a` + `--no-ff` merge of `44d93b4`; 30/30 pass) | commander | — | worker running |

Before C-STATE was integrated, the commander re-verified it:
- `_ci-venv/bin/python -m pytest backend/test_data_state.py`: 18 passed.
- `node frontend/test-data-state.mjs`: 180 checks passed.

### 4.4 Child tasks (Run `run_25ff399808aa`; earlier Run `run_67505fe63eb0` is settled)

| ID | Orca task / dispatch | Agent / model | Worktree / branch (base) | Exclusive files | Reviewer |
|---|---|---|---|---|---|
| P1-126F1 | `task_75322defe946` / `ctx_a97df7fed145` | Claude `claude-sonnet-5-5`, medium | `p1-126f1` / `ava-apple/p1-126f1` (`69f7d4a`) | `frontend/src/myWorkView.ts`, `frontend/test-my-work-view.mjs` | Codex `gpt-6.1-sol` medium |
| P1-127F1 | `task_9350171345dd` / `ctx_86bd20e4559b` | Codex `gpt-6.1-sol`, medium | `p1-127f1` / `ava-apple/p1-127f1` (`69f7d4a`) | `frontend/src/sourceHealthView.ts`, `frontend/test-source-health-view.mjs` | Claude Opus high |
| P1-C2-V2 (superseded) | `task_d08b2b98793b` / `ctx_c194365a7b22`, retry `ctx_00739c5756e7` | Claude `claude-opus-5-5`, high: launched in error; fenced by coordinator under the code = Sonnet rule | `p1-c2-v2` (`799fe4a`) | same as C2-V2-S | — |
| P1-C2-V2-S | `task_f3b133db9e24` / `ctx_a24da445cd6c` | Claude `claude-sonnet-5-5`, medium | `p1-c2-v2` / `ava-apple/p1-c2-v2` (on preserved `ad0bd9a` ← `1cc6f18` ← `799fe4a`) | `backend/source_identity.py`, `backend/test_source_identity_contract.py` | Codex `gpt-6.1-sol` medium |
| P1-126F1-REV | `task_cbb71f8fae80` / `ctx_3d96b6dcd0dc` | Codex `gpt-6.1-sol`, medium | `p1-126f1-review` (`06dc8aa`) | read-only | **CHANGES-REQUESTED**: F1 forbidden weekly leak, F2 stale null→0, F3 invented labels |
| P1-126F1-FIX1 | `task_fdc4abe1afb0` / `ctx_463694fdcd9b` | Claude `claude-sonnet-5-5`, medium | `p1-126f1` → `80d80be435922da5d2bc03f83c3a314a4ad8af7e` | same as 126F1 | re-review below |
| P1-126F1-REV2 | `task_7d65050ebbbc` / `ctx_be942b3c7e43` | Codex `gpt-6.1-sol`, medium | `p1-126f1-review2` (`80d80be`) | read-only | running |
| P1-127F1-REV | `task_14e34b145b79` / `ctx_f61245d3d7c2` | Claude `claude-opus-5-5`, high (review only) | `p1-127f1-review` (`4e7749967efd9c716601ed4da7a790a0b90c7aac`) | read-only | running; also judged against the receipt rule (§7 D3) |

Model notes:
- 127F1 swapped to Codex (the `tasks.tsv` row said Claude) so that both families code in P1.
- C2-V2 was first launched on Opus in error and has been reassigned to Sonnet. The Opus commits `1cc6f18` and `ad0bd9a` are preserved without rewrite.

Settled children from earlier continuations stay recorded in `.runtime/task_ec8184733081/children.tsv`:
- P1-C1-REM `task_66025376e1f5`
- P1-C1-REM-REV `task_3a4624cbce68`
- P1-C2-REV `task_ebfd09513665`

Their worktrees are preserved.

### 4.4a Integration log (2026-10-14)

| Order | Row | Reviewed SHA | Final review | yx-v2 merge | CI / push |
|---|---|---|---|---|---|
| 1 | C-STATE | `0ed93e7` | Codex `task_3a4624cbce68` PASS | `69f7d4a` | `local_ci` green; pushed with plan at `7870953` |
| 2 | 127F1 Source Health view model | `2cd9a2c7aa1390c1a6d0db9e6f954cb4b9b4e69f` (2 correction rounds) | Opus `task_9968bba181e2` PASS-WITH-FINDINGS (H1/H2 low test notes) | `04e8388` | first run: 1 flaky two-process contention test (`test_ops_sync_workspace_store`, no backend diff, 5/5 isolated passes); rerun green, 3050 passed |
| 3 | C-ID v2 | `78b495b` (Opus `1cc6f18`/`ad0bd9a` preserved, Sonnet `697593d`/`171a145`/`78b495b`) | Codex `task_e173b53f4708` PASS-WITH-FINDINGS (N1 nit; N2 inherited: `native_records` raises on malformed raw link table shapes, so a future input boundary must validate them) | `2ea1e53` | pre-push CI 3211 passed; **remote `ava-apple/yx-v2` = `2ea1e530cbdd74b1c85ea4c0824309e7751d3688`** |
| 4 | 126F1 My Work view model | `0cbd2446ae88f6eb72ae348eebb4cde9e5c5afe3` (3 correction rounds; the third was authorized by the coordinator) | Codex `task_22a233bc69e4` PASS-WITH-FINDINGS (R1 nonblocking: no repo test pins `parent.verified===true`) | `b444931` | pushed with this plan revision |

Review history, with every report under `worker-evidence/<task>/review.md`:
- 126F1: `task_cbb71f8fae80`, `task_7d65050ebbbc` and `task_c8d663374cdb` were each CHANGES-REQUESTED; `task_22a233bc69e4` passed.
- 127F1: `task_14e34b145b79` and `task_b8f63dad0a92` were CHANGES-REQUESTED; `task_9968bba181e2` passed.
- C-ID: `task_442cb2c2f880` and `task_2b6bc084dbac` were CHANGES-REQUESTED; `task_e173b53f4708` passed.

Commander decisions taken during review:
- 127F1 G5: a present non-boolean stage flag fails closed.
- 127F1 G6: the mapping label is `對應未驗證`, and mapped/accepted stay literal false/null.
- 126F1: no derived in-progress status, and `workflow_state` is shown verbatim. The coordinator approved this.

Residual nonblocking notes (H1/H2, N1/N2, R1) are carried to the F2 UI and B rows.

**Next ready P1 rows (G-C1 and G-C2 reviews passed; coordinator acceptance pending):**
- 127B1: Codex.
- 126B1: Sonnet.
- 127B3: Codex. It must output `receipt_missing` only, with no receipt acceptance.
- AGY 127F2 and 126F2: presentational UI built on the integrated view models. They need G6 label copy and must handle `dataState:null`.
- 127B2 stays blocked on G-DIAG.

### 4.4b Actual wiring at `416e1bd` (verified 2026-10-14 by source inspection)

| Interface | Existing route / component | Existing API | New artifacts and wiring state |
|---|---|---|---|
| VCC-126 My Work | `#work` → legacy `MyWork` in `frontend/src/App.tsx:126` (behind `FullWorkspaceGate`) | data from `GET /api/workspace` | `frontend/src/myWorkView.ts` is a **view model only**, imported by nothing but its test. `GET /api/my-work` and `/api/my-work/activity` do not exist; they are approved in the commander `tasks.tsv` P1-INT row |
| VCC-127 Source Health | `#sources` → legacy `Sources` in `frontend/src/App.tsx:159` | `GET /api/sources` (`backend/app.py:782`) through `visible_source_snapshot` → `public_source_cache` field allowlist → `case_redaction.apply` | `frontend/src/sourceHealthView.ts` is a **view model only**. `GET /api/source-health` does not exist; it is approved in P1-INT |
| C-STATE | — | — | `backend/data_state.py` and `frontend/src/dataState.ts`: used only by tests and the two view models |
| C-ID | — | — | `backend/source_identity.py`: used only by its tests. No importer or route |

Backend and source adapter gaps:
- 127B1: a source-health projection from the existing source cache plus live-read freshness.
- 126B1: a my-work projection from the existing workspace/home-queue state.
- 126B2: weekly activity and actions.
- 127B3: receipt-state exception lists (`receipt_missing` only).
- 127B2: diagnostic access, gated by G-DIAG.
- P1-INT: route registration, nav and replacing the legacy body.

Authorization and data boundaries for P1-INT:
- Every new GET goes through `identity` → `production_access.require_access` → `source_case_policy.filter_visible_cases` / `visible_source_snapshot` → the existing field allowlists (`public_source_cache`) → `case_redaction.apply`. No new grant, role or scope is added.
- Unknown-versus-zero and C-STATE semantics are preserved end to end.

**VCC-125 impact** (re-read 2026-10-14, Backlog). The residual leaks are on `/api/audit`, action 409 errors and `GET /api/projects/{id}`.
- New P1 GETs must not reuse those paths.
- My Work and Source Health may only *link* to the existing case route, and that route inherits the P2-3 leak.
- Therefore no P1 route may claim complete authorization coverage, and VCC-125 stays a release gate.

### 4.4c Continuation children (`task_97a32b5dcb2e`, Run `run_69a66146a98c`; records in `.runtime/task_97a32b5dcb2e/`)

| ID | Orca task / dispatch | Agent / model | Worktree / branch (base `416e1bd`) | Exclusive files | Reviewer (other family) |
|---|---|---|---|---|---|
| P1-C2-N | `task_91d611b7f9d0` / `ctx_5b76505db52a` | Claude `claude-sonnet-5-5`, medium | `p1-c2-n` / `ava-apple/p1-c2-n` | `backend/source_identity.py`, `backend/test_source_identity_contract.py` | Codex `gpt-6.1-sol` medium |
| P1-127B1 | `task_50231ff50986` / `ctx_bdb4d2fdef07` | Codex `gpt-6.1-sol`, medium | `p1-127b1` / `ava-apple/p1-127b1` | `backend/source_health.py`, `backend/test_source_health.py` | Claude Opus `claude-opus-5-5` medium |
| P1-126B1 | `task_c94f5b3156f0` / `ctx_2709e42eedc0` | Claude `claude-sonnet-5-5`, medium | `p1-126b1` / `ava-apple/p1-126b1` | `backend/my_work.py`, `backend/test_my_work.py` | Codex `gpt-6.1-sol` medium |
| P1-127F2 | `task_c85dcc2b9f77` / `ctx_6672e60bbf04` | AGY (antigravity), agent default | `p1-127f2` / `ava-apple/p1-127f2` | `frontend/src/SourceHealth.tsx`, `frontend/src/source-health.css` | Codex `gpt-6.1-sol` medium |
| P1-126F2 | `task_de0e26027d09` / `ctx_075d4b849643` | AGY (antigravity), agent default | `p1-126f2` / `ava-apple/p1-126f2` | `frontend/src/MyWorkTable.tsx`, `frontend/src/my-work-table.css` | Codex `gpt-6.1-sol` medium |

Held rows:
- 127B3 (Codex): waits for C2-N acceptance, because N2 is its input boundary.
- 126B2 (Codex): waits for 126B1.
- 127B2 (Sonnet): waits for G-DIAG.

P1 merge order: C2-N, 127B1, 126B1, 127B3, 126B2, F2 ×2, P1-INT (the commander wires the three approved GETs and the `#work`/`#sources` bodies), then P1-REV.
Because the file sets are disjoint, rows merge in the order they are accepted. The order above is the default.

Review and correction rounds in this continuation (every report is under `worker-evidence/<task>/`):

| Row | Candidate SHAs (author task) | Reviews (other family) | State |
|---|---|---|---|
| C2-N | `771d6ef` (`task_91d611b7f9d0`) → `0dab393` (FIX1 `task_4da5febd32de`) → `a139fd4f25a9c4938207f9a180a67e5a2bc8ad9b` (FIX2 `task_0a796693ed10`, final round) | Codex: `task_a99046fad671` CHANGES-REQUESTED (standalone constructor key; recursive sibling loss); `task_02fc6a882f2e` CHANGES-REQUESTED (all-null link dict; diagnostic collapse); REV3 `task_73719da5a4f5` running | not accepted |
| 127B1 | `4b85a91` (`task_50231ff50986`) → `e1b25a9a925b2741924e05358b50d4629efd0711` (FIX1 `task_0b128e71a49a`) | Opus: `task_e946714db749` PASS-WITH-FINDINGS (2 Medium); `task_0b7b3793ade6` **PASS-WITH-FINDINGS**. Its R1 (Low) is accepted as fail-closed: with `viewer_filtered=True`, a healthy table plus a filtered-empty table gives page `unknown` | **accepted, integrated** |
| 126B1 | `bd4084a` (`task_c94f5b3156f0`) → `693b4eb` (FIX1 `task_815d0d2c4467`) → FIX2 `task_db0f5930291f` running (final round) | Codex: `task_ef2cc07991fb` CHANGES-REQUESTED (F1–F4); `task_b7d16e94a335` CHANGES-REQUESTED (R1 critical: malformed known-other tasks; R2: hidden demo disables the redaction default) | correcting |
| 127F2 | `5a744b5` (AGY `task_c85dcc2b9f77`) → `77ce146ee7cb3bea314f1e88b4169d7e02c01ffd` (AGY FIX1 `task_16f8b81774fe`) | Codex: `task_ab85c1d21f7b` CHANGES-REQUESTED (keyboard intercept; derived copy/counts; ARIA; focus); REV2 `task_4dd025a77a0c` running | reviewing |
| 126F2 | `3bbed53` (AGY `task_de0e26027d09`) → AGY FIX1 `task_33fc638f1538` running | Codex: `task_cf4b3a41b3d5` CHANGES-REQUESTED (keyboard intercept; ARIA; claimed mutation checks were not real) | correcting |

**P1-INT obligations already recorded from reviews:**
- On the real path, pass `viewer_filtered=False` to `build_source_health` only after re-verifying that `visible_source_snapshot` does not narrow rows for the viewer.
- Resolve the `page_state: None` → unknown rendering with a separately reviewed view-model change.
- My Work's supervisor toggle stays tied to the existing per-item authorization.
- Both AGY reports list view-model copy follow-ups.

### 4.4d Integration log (continuation)

| Order | Row | Reviewed SHA | Final review | yx-v2 merge | CI / push |
|---|---|---|---|---|---|
| 5 | 127B1 Source Health read model (pure, unwired) | `e1b25a9` | Opus `task_0b7b3793ade6` PASS-WITH-FINDINGS | `d4e13156213043b9b6ca77a843554bd6529894b0` | `scripts/local_ci.sh` **exit 0**: backend 3258 passed, 20 skipped, 1 xfailed; frontend checks passed. Log: `worker-evidence/task_97a32b5dcb2e/local_ci_d4e1315.log`. Pushed with this plan revision |
| 6 | 127F2 Source Health component (AGY, unwired) | `6c12b521d4a033cc852c19137bf8c283ad3095c1` (3 AGY rounds) | Codex `task_cf4e1661eaf4` PASS-WITH-FINDINGS (held-Space repeat; unused code) | `69b7f9776e15e32d551e651cf0d35247911d7642` | The first `local_ci` failed only `test_two_process_contention…` (no backend diff). That test passed 3/3 in isolation, and the full rerun exited 0. **Pushed** (remote = `69b7f97`). The parent separately diagnosed a baseline flake, which still awaits an owner decision |
| 7 | 126F2 My Work component (AGY, unwired) | `fd31af5417d692d15d656758200cb5f555a1f615` (3 AGY rounds) | Codex `task_5c4d4990cff1` PASS-WITH-FINDINGS (unused duplicate DOM id) | `ce55be419f0385f07e7e9d2f345999623aceac40` | `local_ci` exit 0 on the first run; push held |
| 8 | C-ID N1/N2 boundary fix | `30207464ac6098f0fc049ef5172efffa584fc7be` (Sonnet: 2 rounds plus 2 coordinator-authorized rounds; the FIX4 first dispatch hit a session cap and was retried with lineage) | Codex `task_e1654ecfdf61` **PASS, no findings** (after REV1–REV4 CHANGES-REQUESTED) | `793ad27a0d45fc1626e622d1c461615512b30e65` | `local_ci` exit 0 (3349 passed); push held |
| 9 | 126B1 My Work read model | `a1dc3e38ade0555fb08ec988b57b528472f5903e` (Sonnet: 2 rounds plus 2 coordinator-authorized rounds) | Codex `task_14468312d341` **PASS** (after REV1–REV4 CHANGES-REQUESTED) | `534c0f025cb61fe24910e0806037a4b7c986ce9c` | `local_ci` exit 0 (3437 passed); push held |

Binding decisions made during these rounds:
- **126B1:** authority and review hashes come only from the original visible task set. Sanitized copies are used only for indexing. Failure is fail-closed per node/section. Viewer-owned records are never removed, and known closed status, unknown outcomes and known assignment are preserved.
- **C-ID:** malformed diagnostics are always unresolved with a null target, and carry a structural locator. Ordinary rows keep their 8-component identity. Table-only and nullable containers are native no-ops, exactly as `native_records` treats them.

**P1-INT** `task_c7e639e9e6ed` / `ctx_28c92afc7c3a`: Claude Sonnet 5.5 medium, worktree `p1-int`, branch `ava-apple/p1-int`, from `534c0f0`. It is the sole writer of the hub files and registers only `GET /api/source-health` and `GET /api/my-work`.

| 10 | P1-INT route wiring | `6c926551e5c75e8f1392d2cd5b02f865a2a085a9`. Sonnet `task_c7e639e9e6ed` produced `0a7cbb3`, which labelled `page_state` null as 資料正常. That violated the owner's correction `msg_2da3335aa577`, so FIX1 `task_ac643adf1d11` restored null → unknown | Codex `task_606546259acc` PASS-WITH-FINDINGS, with isolated demo browser evidence in `worker-evidence/task_606546259acc/screens` | `6e1476efd4db68afc02f6cd8f37909b4bd6624f5` | `local_ci` exit 0 (3452 passed) |
| 11 | P1-INT-FIX2/FIX3 | `c2d38b7ac7189847839b160e4df940bc20a90ff0`. N1/W1 by `task_d9a56995101d`; F1–F3 from the Opus P1-REV, fixed by `task_3e8884438106` | Opus P1-REV `task_05984fe4777c` on `6e1476e`: CHANGES-REQUESTED (F1 Medium: evidence unknown → none). Codex P1-FINAL-REV `task_089ad14fcd65` on `50ddfdb`: PASS-WITH-FINDINGS (W1b Low) | `50ddfdb50ab0b43e81e031c5a676ca5295d47830` | `local_ci` exit 0 (3453 passed). Codex P1-FINAL-REV `task_089ad14fcd65` **PASS-WITH-FINDINGS**: one Low, W1b (Back after navigating from a different row restores the selected row, never BODY). **Pushed** with a normal fast-forward: remote `ava-apple/yx-v2` = `50ddfdb` (`ls-remote` verified) |

Push note: the remote reached `534c0f0` through a push that was not made by the commander, while the commander was holding pushes for the contention-flake decision.

**Exact-SHA staging artifact (prepared, not deployed):** `worker-evidence/task_97a32b5dcb2e/stage-50ddfdb/`.
- Contents: `git archive 50ddfdb` → `yx-v2-50ddfdb.tar` (SHA-256 `a9c9c15b94f0c132c9b0626010c75bd573661671e4581556f6e7bf9beb1f9957`) and the extracted `project/` folder.
- Inventory: 833 files. The `stage_inventory.inventory_digest` value is `184bb78bc72d49e976c27c1cbf90134ce4613261df7ec5052b41c2238e8ae86b`, verified by `verify_stage_inventory`.
- `scripts/verify_stage_package.py`: exit 0, all checks ok (receipt in the same folder).
- The parent re-uploads `project/` to the existing staging service only after coordinator acceptance (§10). No credential, service or production change.

**Routes now in code** (they become delivered only once P1-FINAL-REV and coordinator acceptance pass):
- `GET /api/source-health` returns the page state only, with `diagnostic=False`. It passes `viewer_filtered=None` because `visible_source_snapshot` narrows rows.
- `GET /api/my-work` returns the full-workspace load with B1 redaction and `as_of`.
- `#sources` and `#work` render SourceHealth and MyWorkTable. The legacy views remain at `tab=legacy`.

`page_state` null is always unknown, because no per-request complete-read evidence exists (`source_health.py:67`).

**Documented P1 gaps** (not delivered; none is labelled done):
- 126B2 weekly activity: `/api/my-work/activity` is not registered.
- 127B2 diagnostics: G-DIAG.
- 127B3 mapping exception lists: G-RCPT, G-RSCHEMA.
- Per-request complete-read evidence: Source Health stays unknown.
- My Work fields: next_deliverable, work_item_title, document → workspace link, work-item detail link, and attached evidence (shown as unknown). Each needs a verified source relation.
- Retry on the new Source Health page.
- Browser captures of the remaining C-STATE states.
- VCC-123 deadline provenance: every effective due date is unknown.
- VCC-125: open release gate.


### 4.6 P2 children (rev 3.7; commander `task_7bab31d03ad7`, Run `run_78850e7617f6`; records and specs in `.runtime/task_7bab31d03ad7/` of the commander worktree)

All rows branch from `7ae4a9d`, live in Orca `new-child` worktrees under `/Users/vc/orca/workspaces/YXMEEGLE/p2-*`, commit locally and are integrated by the root coordinator only. Effective agent/model/effort is recorded in `start-*.json`.

| ID | Orca task / dispatch | Agent / model | Worktree / branch | Exclusive files | Reviewer (other family) | State |
|---|---|---|---|---|---|---|
| P2-129B Confirmation List read model | `task_fdfb6ebb821f` / `ctx_e70eb9bd4e3b` | Claude `claude-sonnet-5-5` medium | `p2-129b` / `ava-apple/p2-129b` | `backend/confirmation_list.py`, `backend/test_confirmation_list.py` | Codex `gpt-6.1-sol` medium | dispatched |
| P2-130B Case/Confirmation Detail read model | `task_7dadd7a6da03` / `ctx_c4c7409a7885` | Claude `claude-sonnet-5-5` medium | `p2-130b` / `ava-apple/p2-130b` | `backend/case_detail.py`, `backend/test_case_detail.py` | Codex `gpt-6.1-sol` medium | dispatched |
| P2-131B Contract Detail read model | `task_1c6df5239e18` / `ctx_a8cd8bf90fd1` | Codex `gpt-6.1-sol` medium | `p2-131b` / `ava-apple/p2-131b` | `backend/contract_detail.py`, `backend/test_contract_detail.py` | Opus commander | dispatched |
| P2-132B Work Item Detail read model | `task_dd50a157ceec` / `ctx_43dee71a62c5` | Codex `gpt-6.1-sol` medium | `p2-132b` / `ava-apple/p2-132b` | `backend/work_item_detail.py`, `backend/test_work_item_detail.py` | Opus commander | dispatched |
| P2-128B Manager Overview read model | `task_680721c42b16` / `ctx_59f19ab6b2f1` | Codex `gpt-6.1-sol` medium | `p2-128b` / `ava-apple/p2-128b` | `backend/manager_overview.py`, `backend/test_manager_overview.py` | Opus commander | dispatched; `confirmation_population` is injected (protocol: rows with `row_key`, `project_id` or None) and bound to the reviewed 129B function at P2-INT |
| P2-NAV return context | `task_dcf510090854` / `ctx_624d8d2efe24` | Claude `claude-sonnet-5-5` medium | `p2-nav` / `ava-apple/p2-nav` | `frontend/src/drilldownContext.ts`, `frontend/test-drilldown-context.mjs` | Codex `gpt-6.1-sol` medium | dispatched |

**Review and fix record (P2 wave 1; reports under `worker-evidence/<task>/`, commander reviews and verifications under `worker-evidence/task_7bab31d03ad7/`):**

| Row | Candidate chain | Reviews | Result |
|---|---|---|---|
| 129B | `e4fce38` → FIX1 `b04439d` (Sonnet `task_a95f8c126b93`) → FIX2 `d7498baa5b7dd2d0c2fb60ee1d59f62c198b7aa9` (`task_651d07c11d60`) | Codex `task_51df6473e67f` CHANGES-REQUESTED (5); Codex delta `task_1b16ab71fd82` CHANGES-REQUESTED (1 Medium, unknown-read retention) | FIX2 commander evidence-verified (parent: no third review cycle) |
| 130B | `f3dd460` → FIX1 `b4accaa` (`task_6274b89cf7f4`) → FIX2 `9747c165175e6dbdda7b973aa3b366b04f8c6b65` (`task_22adf4b6a623`) | Codex `task_d0d1b4f82c78` CHANGES-REQUESTED (F1–F5); delta `task_dc035024832d` CHANGES-REQUESTED (F1); delta `task_66fdc4d7e733` running | commander evidence-verified; awaiting delta check |
| 131B | `07443f4c0baf90dafe6106c06a6eba9fb902b264` | Opus commander PASS-WITH-FINDINGS (R1 Low, R2 INT obligation) | ready |
| 132B | `3626478` → FIX1 `e0015ba9fe5e0161a6b096832d6543079f4be28d` (`task_532709293abf`) | Opus CHANGES-REQUESTED (F1 Medium) → delta PASS-WITH-FINDINGS (L1 Low) | ready |
| 128B | `b480b4b8b33420ba0f9be638a3d74db507683598` | Opus commander PASS-WITH-FINDINGS (L1 residual gap, L2 polish); a duplicate reviewer `task_50cfda02b2f7` was stopped by the coordinator | ready |
| NAV | `b3e1bc6` → FIX1 `a52908053ea42ebadb95b630e98330d86b42638d` (`task_8e3e989fa7a1`) | Codex `task_7cf92742dbbc` CHANGES-REQUESTED (F1 hash envelope; F2 → P2-INT); delta `task_47da52c6a9c3` PASS | ready |

P2-F1 view models dispatched from `7ae4a9d` (new files only): 128F1 Sonnet `task_72dbe16e6f60`, 129F1 Codex `task_372a1b5fce1b`, 130F1 Codex `task_95c9f3e727b2`, 131F1 Sonnet `task_b4132a99398a`, 132F1 Sonnet `task_c8ad12122165`.

**Proposed serial order for the root:** A1 129B → A2 130B → A3 131B → A4 132B → A5 128B → A6 NAV (focused test per merge; one full backend pytest and one frontend build/tsc at A6) → B P2-INT-B (Sonnet; `backend/app.py` + `backend/test_p2_int_routes.py`; exactly `GET /api/manager-overview`, `/api/confirmations`, `/api/case-detail/{project_id}`, `/api/contract-detail?key`, `/api/work-item-detail?key`) → C F1 ×5 → D AGY UI-a/UI-b → E P2-INT-F (Sonnet; frontend hub files plus new `P2Pages.tsx`; NAV F2 vocabulary adapter) → F P2-E2E (Codex). Specs: `spec-p2-int-b.txt`, `spec-p2-int-f.txt`.

Held P2 rows (file sets fixed now, dispatched when their input is reviewed):
- **P2-UI-a / UI-b** AGY presentational components (file sets as in `tasks.tsv`), after the F1s are reviewed.
- **P2-INT** Sonnet: the only writer of the hub files; registers only the five approved P2 GETs through the existing authorization chain (§4.4b). The root coordinator merges.
- **P2-E2E** Codex: `backend/test_p2_reconciliation.py`, `frontend/test-p2-navigation.mjs`.

Gate decisions binding on P2 wave 1 (from the approved specs; no owner question needed):
- Contract amounts are output as `withheld` with reason G-AMT; no values and no derived values.
- Work orders (132) are `unlocated` with a Source Health link until G-RCODE.
- Effective due dates are unknown unless a verified formal field is proven (VCC-123); the 129 deadline-range filter is `unavailable` and never hides rows.
- Edge verification is `receipt_missing` (D3); native IDs are used for read-only navigation only.

P2 integration order is unchanged from §4.2 item 7 (129, 130, 131, 132, 128, NAV, UI-a, UI-b, E2E), executed by the root coordinator.

### 4.5 Remaining P1 rows and owners

| Row | Owner | Depends on |
|---|---|---|
| 127B1 source health read model | Codex `gpt-6.1-sol` medium | G-C2 |
| 127B2 diagnostic access | Claude Sonnet medium | 127B1 + G-DIAG |
| 127B3 mapping receipts | Codex `gpt-6.1-sol` medium | G-C2; G-RCPT for any "mapped" output |
| 126B1 my-work read model | Claude Sonnet medium | G-C2 |
| 126B2 activity/actions | Codex `gpt-6.1-sol` medium | 126B1 |
| 127F2 / 126F2 presentational UI | AGY | Reviewed 127F1 / 126F1 |
| P1-INT hub wiring | commander | all P1 rows |
| P1-REV final exact-SHA cross-review | Codex + Opus | P1-INT |

---

## 5. Dependency gates

| Gate | Unblocks | Condition | State |
|---|---|---|---|
| G-C1 | 126F1, 127F1 | C-STATE reviewed and accepted | **Passed** (`0ed93e7`, integrated at `69f7d4a`) |
| G-C2 | 127B1, 126B1 (dispatched); 127B3 (held for C2-N) | C2-V2 final SHA implements §7 D1–D8 (D3 as revised) + F6/N1–N4, Codex review passes, coordinator accepts | Review passed (`78b495b`, Codex `task_e173b53f4708` PASS-WITH-FINDINGS); integrated at `2ea1e53`. Residual N1 (equal bool/float version components kept) and N2 (`native_records` raises on list/dict link `table_id`) are being fixed at the C-ID boundary by P1-C2-N; the protected `v4_sources.py` stays unchanged. Final C-ID acceptance follows the C2-N cross-review |
| G-RCPT | any field/edge shown as mapped/accepted | Supplied VCC-117 same-version source/schema/permission receipt per field and native edge type. Absent → `unlocated` / `receipt_missing`; no invented IDs | **Open, hard evidence gate** (no receipts in repo) |
| G-RSCHEMA | trusting receipt content | Receipt schema, location and verifier authority defined by owner/VCC-117 | **Open, unresolved** |
| G-TOKEN | asserting Lark token alphabet | Evidence on whether base/table/record tokens can contain `/`. Until then C-ID rejects such components (D8) | **Open, unresolved** |
| G-DIAG | 127B2 diagnostic layer | Coordinator confirms which existing grant is diagnostic (proposal: `company_admin_grant`). Otherwise page-state view only | Open |
| G-P1-REV | (formerly all of P2) | P1-INT green on `scripts/local_ci.sh`; cross-review passes; browser evidence; coordinator accepts | **Superseded for P2 start** by the rev 3.7 owner direction; P1 gaps stay documented |
| G-AMT | P2-131B amounts | Separate approval to show contract amounts (`QUOTE_FINANCE` re-verified) | Open |
| G-RCODE | P2-132B work orders / node instances | R01/02/09/10 work-order and node models verified; until then `unlocated` + Source Health link | Open |
| G-P(N) | phase N+1 | Phase N integration + real tests + independent review + responsive browser evidence + coordinator acceptance | Sequential (§2) |
| G-STG (on hold, rev 3.7) | staging publication of any stage | Exact-SHA artifact prepared from an accepted, pushed `yx-v2` SHA; the parent re-uploads it to the existing staging service through its verified authenticated browser (§10) | **Path available** (CLI 401 no longer the route). No accepted P1 stage is ready to stage yet |
| G-VCC125 | any production release | VCC-125 closed; never waived | Open |

Stop and escalate on any of these: a GET endpoint not listed in the task table, a change to an existing response shape, a missing diagnostic capability, contract amounts, payroll/HR data beyond the existing allowlists, or any field or edge without a receipt.

---

## 6. Per-task delivery and evidence

Each worker's `worker_done` and report must contain all of the following. A missing item counts as a failed check.

1. **Candidate/deployed commit:** exact SHA and branch. For UI work, also the SHA running in the isolated review instance and, once staged, the deployed staging SHA.
2. **What changed:** a file list matching the exclusive set, plus a behavior paragraph.
3. **Tests:** named tests, recorded separately as pass, fail, blocked or not-run. Fixes need failing-first evidence. State and identity guards need mutation/negative checks. The real framework is required; a shim does not count.
4. **Review:** reviewer identity from the other family, the reviewed SHA and the verdict.
5. **UI evidence** (UI-facing rows and phase acceptance), captured on synthetic, privacy-safe data only:
   - Widths: one screenshot per interface at desktop (≥1180 px) and narrow (≤600 px). P3+ also needs tablet and enlarged text/zoom (200%), with the actual dimensions and zoom recorded.
   - States: loading, complete-empty, filtered-empty, unlocated, forbidden, read failure, partial, stale, unknown.
   - Interaction: keyboard focus, the drawer below the table on narrow screens, return navigation.
   - Each capture records the actual candidate or deployed SHA, what changed, the remaining work, and the specific owner decision.
   - Reference comparison (§9) per page: displayed fields, sorting, filtering, dashboard semantics, native relationship navigation, UI/UX.
   - Screenshots are evidence kept under `worker-evidence/`. They are **not** uploaded to Library.
6. **Remaining work:** open gaps, including gates the task did not cover.
7. **Owner decision:** the single specific owner decision or action needed next, or "none".

---

## 7. C-ID architecture decisions (rev 3; supersede the rev 2 question list)

The Opus review `task_ebfd09513665` confirmed that C-ID at `44d93b4` is a one-target, record-keyed resolver with no native-edge, cardinality or caller-permission model, so it cannot serve the P2 chains. The approved specs already decide the architecture below; the commander records it here and does not wait on the optional clarification. C2-V2 implements it (spec: `.runtime/task_67bb22a5d7b6/spec-c2-v2.txt`).

| # | Question | Decision | Spec basis |
|---|---|---|---|
| D1 | Edge grain | Typed edges. An edge type declares source kind/table, native field name and optional field ID, target kinds, direction, and cardinality one\|many. Instances are keyed by (source_key, edge_type). "Ambiguous" means only: more than one verified target on a cardinality-one type. | Shared gate 2 ("source field, target, direction, cardinality and permission boundary") |
| D2 | Native links | The existing native resolver is the source of instances (`v4_sources.native_records`/`RELATIONS`, plus the field-ID links in `source_work_items`). It is reused, not reimplemented. Missing targets stay explicit unresolved rows. | VCC-132 "use native relationship IDs"; gate 2 |
| D3 (revised by owner, 15:35Z) | Verification | **No caller-supplied string is ever an authoritative receipt.** No code path may mark an edge accepted, mapped or verified on the strength of a free-form receipt, `verified_by` or `evidence_ref` value. That includes legacy `resolve_edge`, which returns an explicit unresolved reason instead. Receipt schema and verifier authority must come from existing trustworthy read-only evidence. Until real VCC-117 evidence exists, every edge type and instance is `receipt_missing` (`unlocated` for mapping). Native edge IDs remain usable for read-only navigation. | Gate 1; G-RCPT; owner decision |
| D4 | Reverse navigation | Part of C-ID, built from the same forward instances so parent→child and child→parent agree by construction. | VCC-130 round-trip; "one-to-many and many-to-many" tests |
| D5 | Permission boundary | Stays in callers (`production_access.require_access`, `source_case_policy`, `case_redaction`). C-ID takes no viewer and has no `forbidden` outcome. Callers redact target keys and reasons. | Commander spec "every new endpoint goes through…"; existing route authorization |
| D6 | Stable cross-version identity | Only the existing `project_id` from the existing `assignments` mapping, which is built from verified import mapping and human pairing reviews. Provenance `assignment`. No new issuer, no grouping by name, case number or suffix. | Gate 2 "independently verified stable business identities" |
| D7 | Versions | `SourceRef.version` stays separate from `source_key`. A version-qualified tuple key keeps source versions separate. `entity_id`, `sources.source_id` and stored IDs are unchanged. | VCC-129 "one source record version" |
| D8 | `/` in keys | The slash-delimited `entity_id` is not mutated. `SourceRef` rejects components that are empty, non-string, padded or contain `/`, so a would-be collision becomes an explicit unresolvable reference. Token encoding remains an unresolved evidence gate (G-TOKEN). | No evidence to re-key; unknown must not become a wrong join |
| F6 | Validation | Confirmed by commander probe on `799fe4a`: `SourceRef.from_entity(..., version=True)` and `SourceRef('', '', '', '', '', None)` are both accepted. Fix: `__post_init__` validation shared by both paths. `bool` is not a version, and `source_key` must equal the joined components. Focused commit first, then re-review of the exact final SHA. | Review F6 |
| N1–N4 | Minor findings | Reject padded or malformed targets. Raise `TypeError` on a mapping or non-iterable registry. Flag contested cardinality-one edges. | Review N1–N4 |

These remain explicit evidence gates, and no values are invented for them:
- the missing VCC-117 receipts (G-RCPT);
- the receipt schema and verifier authority (G-RSCHEMA);
- Lark token encoding (G-TOKEN).

---

## 8. Phase-by-phase interface plan

Common to every interface:
- the nine C-STATE states;
- unknown is never 0;
- a selection-only drawer, placed below the table on narrow screens;
- keyboard access to filters, headers, rows and Back;
- text status labels;
- filter, sort, cursor and context preserved across drilldown and return;
- source time and completeness always visible;
- source context + record_id row keys;
- no joins by name, case number or suffix;
- aggregation at source grain before joins;
- one canonical fact set for table, KPI, chart, drilldown and existing export;
- R01/R10 and R02/R03/R09 totals are never added;
- the V4 transactional cutoff 2026-10-07 20:10:44 Asia/Taipei is verified per source and never applied to asset masters;
- fetch time is not source-updated time;
- Lark stays read-only, with no new scope, credential or role.

Child template per interface (file names are proposals, fixed at phase start):
- `B`: backend read model, `backend/<iface>.py` + test.
- `F1`: view model, `frontend/src/<iface>View.ts` + test.
- `F2`: AGY presentational `.tsx`/`.css`, after F1 is reviewed.
- `INT`: hub wiring by the commander.

Within each phase, B and F1 of one interface go to different families, alternating across interfaces so both families code.

### P1 (in progress)
- **VCC-126 My Work.**
  - Fields: task identity, case/work item, assignee, workflow state, next deliverable, effective due date (verified formal field only, else unknown), pending reason, handoff/confirmation state.
  - Filter: all unfinished history. No week filter; weekly activity is a separate dataset.
  - Navigation: task → drawer, case/work item → detail, document → workspace.
  - Actions: no Complete/Approve.
- **VCC-127 Source Health.**
  - Ordering: attention-first sort.
  - Timestamps: last attempt, last success and source updated are separate; a summary uses the oldest snapshot.
  - Mapping states: located/readable/mapped/presented/accepted are distinct.
  - Access: forbidden sources leak nothing; the diagnostic layer only with existing access; retry repeats the authorized read only.

### P2 (in progress; rows in §4.6)
- 128: Manager Overview. Each KPI equals its same-set drilldown denominator.
- 129: Confirmation List. One row per source version; cursor pagination.
- 130: Case/Confirmation Detail. Parent↔child round-trip with no forbidden-child leak.
- 131: Contract Detail. Original and revised amounts are never summed; units are isolated; amounts gated by G-AMT.
- 132: Work Item Detail. Native edges only; rework is a distinct instance; plan/actual only for the same unit and period.

### P3 (after P2 acceptance)

#### VCC-133 Document and Delivery Workspace
- **Fields:** document name/type, version, parent case/work item/task, owner, delivery/review state, effective due date with its meaning, last update, authorized file/source entry point.
- **Expansion and drawer:** expanding a row shows version history and submission events. The drawer shows native parents, handoff/approval summary, formal Drive/Input source and history.
- **Filters:** case, document type, responsible person, delivery state, version, search.
- **Left nav:** All / Input / Output / Daily-report Evidence / Relationships Awaiting Confirmation.
- **Sort:** most recently updated first, using verified source-updated time only, with a stable ID tie-break.
- **Dashboard semantics:** linked/unlinked count cards never replace delivery information.
  - Not uploaded, awaiting delivery, delivered and unknown are distinct.
  - Pending review is not approved.
  - An empty view is not proof that nothing is outstanding.
- **Identity:** document → version → submission event → delivery/review state stay separate keys. Case, work item and task parent types are never collapsed.
- **Dates:** the effective approved due date, the pending requested date and the estimated date stay separate. No invented N-day deadline.
- **Navigation:** parent → 130/132; Report Review → R03; relationship issue → Source Health. Return preserves filters and selection. Forbidden attachments are never preloaded.
- **Reference comparison:** borrow the R03 quality-table structure, field switching and gap messaging. Replace its columns with document/type/version/parent/owner/delivery/review/deadline. The reference empty state does not validate a populated journey.
- **Gates:** native parent relations; document/version/submission definitions; status authority; VCC-121 gaps stay discovery gaps.

#### VCC-134 R03 Report Quality Review
- **Fields:** the 12 configured default columns: Work Order No., Person, Related Case, Case Code, Office Work Item, Billable Qty, Revenue Points, Final Revenue Points, Quality Check, Ya-wen Check, Check Time, Rework Flag. Key Fields/All Fields; All Fields only from the verified schema.
- **Tabs:** Quality Work Orders / Deliveries / Client Replies / Raw Table. Table/Chart toggle; existing export.
- **Filters and date basis:** reporting-date / check-date / no-week. The `v4-internal-work` (`tblrCo8KeZiuJUNh`) dateField is NOT configured, so date/week filtering is blocked until the actual field is bound. Unbound dates never hide records.
- **Dashboard semantics:**
  - Delivery and Reply areas: `report-delivery` is unlocated, so they show the explicit gap. There are no fake N+1/2/3 counts or zero/pending/completed states.
  - R02/R03/R09 totals are never added.
- **Navigation:** work order → 132; document → VCC-133. Delivery/reply links activate only when the edge is verified.
- **Reference comparison:** borrow the raw-table layout, field modes, Table/Chart and check-date entry.
- **Gates:** quality-table read access; actual date field; work order → native work item; delivery/reply source location.
- **P3 merge order:** 134B, 133B, 134F1, 133F1, UI ×2, E2E. Proposed owners: 133B Sonnet, 133F1 Codex, 134B Codex, 134F1 Sonnet.

### P4 (after P3 acceptance)

#### VCC-135 R01 Field Quality Review
- **Fields:**
  - Group summary: group, work orders, checked, failed, failure rate (when defined), modified, SOP violations (when defined), revenue points, planned points, variance.
  - Group × Mon–Sun matrix and this week's errors.
  - Detail: date, work order, case, work item, qty, original and revised revenue, check result, exception, notes, SOP annotations.
- **Sort:** by group name initially. Numeric columns sort numerically.
- **Filters:** week, version, group chips, raw-table search, filters and column chooser.
- **Dashboard semantics:**
  - 4 cards: work orders, groups, original revenue, checked denominator.
  - Failure rate uses only the approved checked-only denominator. A zero denominator shows unavailable, never 0%.
  - A missing SOP/exception field shows an availability warning.
  - Plan variance uses the comparable subset only.
  - R01 + R10 are never added.
- **Navigation:** group → group details; group-day cell → that group's work orders that day; work order → source/132. Return preserves week and group. SOP writes are not reproduced.
- **Sources:**
  - `v3-field-work` `tbl97f1uXqi7Qz0k` (date 出工日期).
  - `v3-field-cost` `tblQCy3eU0wsUj1I`.
  - `v4-field-work` `tbl5zPLS0ExWNEty` (date 工作日期-薪資; this is not a synonym of the V3 date).
  - `v4-field-cost` `tbl8wRYCUCvbSoJG`.
  - Field IDs are unverified.
- **Edges:** work order → cost parent → person/group → case/work item. Orphans go to a visible list.

#### VCC-136 R02 Internal Quality Review
- **Fields:**
  - Group subtotals and personnel: distinct headcount, work orders, checked, failed, failure rate (when defined), modified, SOP, revenue/planned points, variance.
  - Person × day matrix.
  - Separate Owner Progress tab: case, work no., this week's points, progress %, days to delivery, latest work day. Progress % and days to delivery show — with a reason until defined.
- **Sort:** no approved default beyond group summary first. None is invented.
- **Filters:** group/person chips, Simple/Detailed, week/version.
- **Dashboard semantics:**
  - Headcount is deduplicated across groups by native person.
  - Unmatched-parent work orders are listed, never dropped.
  - A+B are not separately additive.
- **Navigation:** person → day → work order → 132; owner-progress case → 130. Native person identity is preserved across group switches.
- **Sources:**
  - `v3-internal-work` `tblTP5Naz52FBpFg`.
  - `v3-internal-cost` `tbl8JdWLLwlPFuoF`.
  - `v4-internal-work` `tblrCo8KeZiuJUNh` (dateField unconfigured).
  - `v4-internal-cost` `tblKwSDRg6WaGHYr`.

#### VCC-137 R09 Internal Plan vs Actual
- **Views:**
  - Person-day: planned, actual, matched, planned-no-actual, actual-no-plan, achievement rate (when defined), person/group, points.
  - Case: case no., project, planned/actual person-days, revenue, work orders, result.
  - Exceptions: 6 categories. They are not enumerated in the spec, so they are a discovery gate and are never invented.
  - Milestones and remaining points: a separate, explicitly undefined area.
- **Sort:** person-day table first, by person name. Exceptions filtered by category.
- **Filters:** Personnel/Cases grain; All / Planned+Done / Planned-Not-Done / Unplanned-Done chips; category chips.
- **Dashboard semantics:**
  - Overall person-days are deduplicated by native person + day. Case sums may exceed the overall total.
  - Multi-person schedules are expanded; cost-only actuals are kept.
  - Unknown actual ≠ Unplanned Done. A match ≠ delivery completion.
  - Person-day and case denominators stay separate across view switches.
- **Navigation:** person-day → source; case → 130; work order → 132.
- **Sources:** `v3-schedule` `tblN8c3WN44233aG` (dateField unconfigured), `v4-schedule` `tblZz6Mkhv9gHrB2` (開始日期), and the R02 internal work/cost tables. The V3 case resolver is unverified.

#### VCC-138 R10 Field Plan vs Actual
- **Views:**
  - KPIs: planned/matched/unplanned group-days, case intersection, actual group-days, work orders, revenue.
  - Tabs: Case Comparison / Exceptions / Pending Inspection.
  - The N+1/N+2 milestone area is explanation-only.
- **Sort:** case table first. Consecutive dates may collapse for display only and expand to daily rows.
- **Filters:** result chips; Unplanned Done / Planned Not Done / Work-order Exception chips.
- **Dashboard semantics:**
  - A match is native group + business day + native case.
  - Duplicate or all-zero case numbers produce warnings and are never keys.
  - No inferred cost-table dependency.
  - Plan = 1 with an unavailable actual means unknown.
  - No N+1/N+2 overdue counts.
- **Navigation:** case → 130; work order → 132; pending inspection → the original Lark work order (read-only).
- **Sources:** R01 field-work tables and the schedules; V3 cases. The V3 schedule and cases dateFields need discovery.

#### VCC-139 R11 Administrative Reporting
- **Fields:**
  - Per person: work orders, recorded work person-days (not attendance), revenue points, planned points (when defined), variance, exceptions, overtime hours (verified source only).
  - Totals: work orders, cost records, submitters, revenue.
  - Scheduled-only people are kept.
- **Sort:** personnel summary first.
- **Filters:** personnel, version, week. Tabs: Summary / Exceptions / Raw Table.
- **Dashboard semantics:**
  - No check field, so no checked/failed/failure rate.
  - One point per person-day and full shared value per participant are unapproved; derived values show unavailable.
  - The historical "26 missing cost parents" figure is not an expected count.
- **Navigation:** person → that week's person-day; work order → source; missing-cost-parent row → Source Health. Return preserves the person.
- **Sources:** the V4 admin work/cost table IDs are **not located** and must be found through existing authorized discovery. Admin work date fields are unconfigured.
- **P4 merge order:** 135, 136, 137, 138, 139, then UI and E2E. The R01/R10 and R02/R09 pairs share source adapters, so each pair gets one shared fact-adapter row (owner: Codex) before the report rows.

### P5 (after P4 acceptance)

#### VCC-140 R05 Business Quotations
- **Fields:**
  - Cards: current-period record count and prior-week difference; raw fieldwork-confirmation revenue only with a verified common definition. No growth rate without a comparable basis.
  - Charts: daily counts, quotation-owner distribution, status distribution.
  - Table: the 10 observed columns (報價編號, 工程編號, 詢價日期, 回傳單日期, 工程名稱, 業主類型, 報價負責人, 案件負責人, 報價日期, 報價期限). All 33 runtime fields are inventoried before any complete selector is shown.
- **Default:** table on the inquiry-date basis. No invented stable order.
- **Date bases:** 8, each enabled only once mapped to a real field: 詢價, 回傳單, 報價, 報價期限, 確認單回傳開會, 合約開始, 內業期限圖或報, 不依週.
- **Dashboard semantics:**
  - A quotation is not a win or an admitted case; no won/admitted KPI until defined.
  - Blank revenue is unknown, never 0 or −100%.
  - Points and currency are separate.
  - The one-day chart/table discrepancy is tested.
- **Navigation:** chart segment → table filter; clear → overview. Row → source; verified edge → 129/130.
- **Source:** `quotes` `tblENZvYAya93Twa`.

#### VCC-141 R06 Billing Source Detail
- **Default:** the authorized raw receivables-view table, with a read-only successful-fetch snapshot time (not an as-of date) and one compact pending-rules notice.
- **Tabs:** receivables stock, billing events and receipt events, each with its own date semantics. Unbound tabs state the gap. Historical as-of is disabled.
- **Fields:** the 59 runtime fields are inventoried first.
- **Dashboard semantics:**
  - No oversized unknown-balance cards.
  - Empty ≠ zero company receivables.
  - No receipt-week filter on stock.
  - No partial-billing, split-payment, tax, currency or discount formulas.
- **Drawer:** currency, tax basis, formula explanation, split-receipt evidence.
- **Source:** `tblWsSaOcy4nKuGI` view `vewUGIqzfl` (v3). View scope and table scope are labelled separately.
- **Owners:** 140B Sonnet / 140F1 Codex; 141B Codex / 141F1 Sonnet. Merge 140, then 141.

### P6 (after P5 acceptance)

#### VCC-142 R07 Asset Workspace
- **Subpages:** 8: Equipment, Lent-not-returned, Reservations & returns, Equipment maintenance, TAF, Vehicles, Vehicle maintenance, Rates.
- **Fields:**
  - Equipment: name, number, rental class, availability, custodian group, available/abnormal/maintenance counts.
  - Loans: asset, loan date, group, elapsed days.
  - Maintenance: count, latest date, elapsed, cost.
  - TAF: no cost column.
  - Vehicles: plate, status, mileage, next maintenance, reminders, insurance expiry.
- **Default:** equipment, all statuses.
- **Filters:** the date filter applies to event subpages only, never current stock.
- **Dashboard semantics:**
  - Lending, availability and rental type are independent and never summed as exclusive categories.
  - Rates are not assets.
  - The two vehicle sources are never added.
  - Missing dates are never overdue.
  - Blank placeholder rows are identified separately.
  - Loan/return pairs match by event ID or native edge only; a historical return never clears a newer loan.
- **Navigation:** asset → VCC-143; event → source record. Return restores the subpage and filters.
- **Sources:** 14 listed tables (`tblHZFEypeKfWOsF`, `tbl4DLVKuXf4yaEy`, `tblvIt8V2ZHnqAFX`, `tblYUUwi0MEGuLZ0`, `tblVLETpvLxMNwaC` 借出日期, `tbl2qFvPOihhe3R1` 歸還日期, `tbl5qdqsc4W7zYsS`, `tblDaO9z94PSjuVq`, `tblnq7QP6Zqcp6rA`, `tbl2PlmDyO1ciy2E`, `tblfgeEtMuBTg72O`, `tblg3Fo23T6Gos6S`, `tblTQv8l5ntnbwyp`). The non-official `tblZmvrjDC5Q3sIp` is excluded from the main screen.

#### VCC-143 Asset Detail
- **Top:** identity card (equipment no. + custodian, or plate + mileage) and a return path to R07.
- **Left sections:** Overview / Loan-Return / Reservations / Maintenance / TAF / Rates.
- **Main:** the event table, sorted by event time descending with ID as the tie-break, plus the selected loan→return relationship.
- **Dashboard semantics:**
  - An unmatched event means return status needs verification; no completed chain is drawn.
  - TAF has no expiry without a validity period.
  - Missing rates are unknown.
- **Navigation:** event → source; document → VCC-133 or the original file. Return restores the R07 subpage and filters.
- **Owners:** shared asset fact adapter Codex; 142B Sonnet; 142F1 Codex; 143B Codex; 143F1 Sonnet.

### P7 (after P6 acceptance)

#### VCC-144 Client Directory and Detail
- **Fields:** a 9-field schema (name, type, tax ID, contact, company phone, mobile, fax, address, email), each with its own field permission. The directory summary shows name/type and already-authorized ordinary contact fields only. Tax ID, address and mobile appear in authorized detail only.
- **Top:** return to R08, name search, type filter.
- **Main:** left client list (position preserved); center tabs Basic / Related Cases / Contact Activity. The contact-event source is unlocated and stated as such.
- **Sort:** no business order is specified; none is invented.
- **Navigation:** case → 130 (verified edge only); event → R08; source → the same native record. Return restores the search and list position.
- **Source:** `owner-contacts` `tbl4fmZN6cBB7u1d` view `vewiP0FJer`. `contact-log` is unlocated.
- **Fixtures:** no real contact values in fixtures or screenshots.

#### VCC-145 R08 Client Contact Activity
- **Default:** reach the activity tab from the directory. While the source is unlocated, show a labelled shell with no events, counts or follow-up rules.
- **Counts:** directory and event counts stay separate.
- **Filters:** case/client/responsible-person, enabled only once source-backed.
- **Drawer:** time, summary, to-do, next follow-up and parent case, only after source and rule approval.
- **Gating:** the observed 5 directory records are not 5 events. Next and pending follow-up stay gated.
- **Owners:** 144B Sonnet / 144F1 Codex; 145 is shell-only F1 Codex plus AGY.

### P8 (after P7 acceptance)

#### VCC-146 R04 Authorized HR Reporting
- **Access:** only within the existing `HR_VIEWERS` and field allowlists, applied to queries, aggregates, exports, caches and revocation. Unauthorized viewers get no rows, names or counts. Rosters are never disclosed. No payroll amounts.
- **Tabs:** Recruitment / Weekly Attendance / Weekly Travel-Outings / Monthly Overtime.
  - Recruitment shows unlocated/unauthorized ("cannot be determined"), never 0.
  - Weekly Attendance is the default.
  - Monthly Overtime has its own month selector that persists into detail and return; it does not inherit the week.
- **Fields:**
  - Attendance: expected/present person-days, late, early, missing punch, leave, travel, outing.
  - Travel: type, person, group, start/end, duration, reason.
  - Overtime: weekday/holiday/total hours, distinct persons, form count.
- **Sort:** travel by start time. The direction is unspecified, so it is validated, not invented.
- **Dashboard semantics:**
  - No denominator, half-day or missing-punch rules until approved.
  - Future days are never absences.
- **Identity:** open_id first. An ambiguous name match stays unknown.
- **Sources:** `salary-overtime` `tblomH0DXCzXgenE`; `v3-people` `tblmlpA6nG5Ou7NQ`. `hr` is unlocated.
- **Owners:** B Claude Sonnet medium (access-critical; Opus reviews) / F1 Codex. Fixtures are synthetic only.

---

## 9. Reference comparison rules (pmsolution.zeabur.app)

The reference is visual and UI/UX evidence only. Every per-page screenshot report compares these six dimensions, citing the capture in §1.1.

| Dimension | Borrow | Do not borrow |
|---|---|---|
| Displayed fields | Configured column structure, field modes (Key/All), original vs revised side by side, plan vs actual for the same item, unit and period | Treating configured labels as a verified schema; summing original + revised; mixed-unit totals; points as % complete |
| Sorting | Asc/desc/clear; numeric sort for numeric columns; verified source-modified time desc, else source order + stable ID | Retrieval time used as business-update time; invented business priority |
| Filtering | Version, week/date-basis controls bound to verified fields, chips, Reset, column chooser; filters preserved both ways | Reference reporting week as a to-do or stock filter; receipt-week on receivables; filters on unbound date fields |
| Dashboard semantics | Snapshot vs period activity kept separate; KPI = same-set drilldown denominator; undefined cards shown unavailable with a reason | Adding overlapping reports (R01/R10, R02/R03/R09); zero for unknown; reference formulas (N+1/N+2, half-day, one point per person-day) |
| Native relationship navigation | Native-ID chains with breadcrumbs and an exact return context; explicit unresolved rows | Joins by name, case number or suffix; collapsed nodes; suffix-paired loan/return |
| UI/UX | Fixed nav, scope/freshness header, sticky identity columns, dense tables, selection-only drawer (below on narrow screens), text labels, focus, server pagination | Local SOP write/approve controls, technical IDs as primary columns, oversized coverage cards, colour-only status |

---

## 10. Staging target and browser evidence

**Existing staging target (inspected 2026-10-13, read-only):**
- Repository operator: `scripts/workbench_cloud_setup.py`, app `yx-workbench-staging`. Zeabur project and environment IDs are in that script; the staging service ID is in `scripts/verify_frozen_release_source.py` (`SERVICES['staging']`).
- Origin: `https://yongxiang-workbench-staging.zeabur.app`. `GET /api/health` → 200 `{"status":"ok","mode":"lark","database":"postgresql"}`.
- The health endpoint does not expose a build SHA. The deployed SHA must come from the Zeabur deployment record or the stage inventory receipt (`stage_inventory`, `verify_stage_package`).

**Staging path (rev 3.3; replaces the CLI-only blocker):** the local Zeabur CLI credential still returns 401, but it is no longer the route. The parent has verified that its authenticated cloud browser can re-upload a reviewed project folder to the exact existing staging service. Steps:
1. The commander exports the accepted, pushed `yx-v2` SHA with `git archive <sha>` into `worker-evidence/<task>/stage-<sha>/`. It records the SHA, a file-list SHA-256 inventory and the archive hash, and runs `scripts/local_ci.sh` on that SHA.
2. The parent uploads exactly that folder to the existing staging service only (service ID in `scripts/verify_frozen_release_source.py` `SERVICES['staging']`).
3. The commander or parent checks `/api/health` and captures authenticated browser evidence using an existing demo/staging account. The deployed SHA is taken from the upload record or the inventory, because health does not expose it.

No credential, scope, service or production target is created or changed.

**Isolated browser evidence:** run the local demo instance (SQLite + Vite on scratch ports, `DEMO_MODE`, synthetic data), never production data.
- Capture desktop 1280×800 and narrow 390×844.
- From P3 on, also capture tablet 820×1180 and 200% zoom.
- Store under `worker-evidence/<task>/screens/`, with the exact SHA in the file name.

Once G-STG clears, repeat the captures against staging, authenticated with an existing demo/staging account only.

---

## 11. Reporting

- Commander → coordinator: through `orca orchestration` (status, escalation, `worker_done`). Root owns Slack and Linear; the commander sends no Slack or Linear messages and only reads Linear.
- Completion reporting to Anya goes through the existing authenticated OpenClaw route, if available, only for task completion. No new endpoint or channel is invented.
- The final owner report gives, per page:
  - completed, deferred and blocked capabilities;
  - exact candidate, remote and deployed SHAs;
  - tests (pass/fail/blocked/not-run);
  - reviewer and verdict;
  - staging and browser evidence;
  - the reference comparison;
  - the owner decision.

---

## 12. Cleanup

None in this continuation. Every worktree, branch, `.runtime` record, report, `worker-evidence` and `library-handoff` folder is preserved:
- `p1-c1*`, `p1-c2*` (including `p1-c2-v2`), `p1-126f1`, `p1-127f1`, `yx-v2*`;
- `_reports`, `worker-evidence`, `library-handoff`.

Later cleanup needs an explicit owner instruction per item, plus all of these checks:
- a clean status;
- the branch merged into `yx-v2` or archived with its SHA;
- no live dispatch on it.

Settled Orca terminals are released only after their `worker_done` is accepted. Never use bare `git stash`, never force-push, never rewrite a reviewed SHA.

---

## 13. Out of scope

- Lark/Base writes.
- New scopes, credentials, roles or grants.
- Approval or SOP shortcuts.
- New or guessed formulas or mappings.
- Dependency, schema or runtime/security changes.
- Freshness-ceiling increases.
- Production deploy.
- Merges to `ava-apple/yx-company-system`.
- Payroll data.
- The VCC-122, VCC-123 and VCC-125 fixes.
- Any later-phase coding before the previous phase is accepted.
