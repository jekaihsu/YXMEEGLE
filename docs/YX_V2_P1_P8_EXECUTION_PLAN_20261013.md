# YX v2 P1–P8 execution plan (2026-10-13, rev 3.3 of 2026-10-14)

Owner: the single Claude commander. Parent task `task_6f78140157c0`, continued by `task_ec8184733081` (P1/P2 planning and reviews) then by `task_67bb22a5d7b6` (P1–P8 execution), and now by `task_97a32b5dcb2e` (P1/P2 continuation only; P3–P8 are not dispatched by this task). This plan does not create a second commander. Revision 3 adds the complete P3–P8 specs and issue IDs, records the C-ID architecture decisions, and replaces the old no-push/no-staging rule with the owner's serial merge, push and staging authorization (§4).

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
| **P1** | VCC-126, VCC-127, C-STATE, C-ID | **In progress** | Owner authorization (given) |
| **P2** | VCC-128..132 | **Held** | G-P1-REV: P1 integrated, tested, cross-reviewed, browser evidence, coordinator acceptance |
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
| G-P1-REV | all of P2 | P1-INT green on `scripts/local_ci.sh`; cross-review passes; browser evidence; coordinator accepts | Open |
| G-AMT | P2-131B amounts | Separate approval to show contract amounts (`QUOTE_FINANCE` re-verified) | Open |
| G-RCODE | P2-132B work orders / node instances | R01/02/09/10 work-order and node models verified; until then `unlocated` + Source Health link | Open |
| G-P(N) | phase N+1 | Phase N integration + real tests + independent review + responsive browser evidence + coordinator acceptance | Sequential (§2) |
| G-STG | staging publication of any stage | Exact-SHA artifact prepared from an accepted, pushed `yx-v2` SHA; the parent re-uploads it to the existing staging service through its verified authenticated browser (§10) | **Path available** (CLI 401 no longer the route). No accepted P1 stage is ready to stage yet |
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

### P2 (held; rows in `tasks.tsv`)
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
