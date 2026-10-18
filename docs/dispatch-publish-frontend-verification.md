# Dispatch publish frontend verification

Implemented in `/Users/vc/.t3/worktrees/YXMEEGLE/t3-10dad898`, branch `t3/pm-dispatch-workflow`, based on `0083384c39e82caf816afd71561d2dd85c8214b6`.

## PM behavior

`#view=dispatch&tab=work` opens 工作進度. The home dispatch card links to this view and retains its board link. The work view shows counts from the currently filtered rows, a prominent 需要我處理 list, owner and crew avatars, intervals, case, resources, deadline, command state, and nine-node position. Search covers job, person, case and resources. Scope, group, status and planning status have filters. The drawer displays the 21 extension fields plus title, content, owner, department, task status, deadline and node position.

New assignments open from the board header and each unassigned slot. Assignment, reassignment and detail editing use a focus-trapped four-step dialog. Owner inclusion and crew deduplication happen in the model. Intervals use Taipei time, 15-minute steps, and an explicitly exclusive end. The form shows the crew-times-hours calculation as a hint, while keeping the estimated person-hours field editable. Reassignment retains task ID and parent obligation and requires a new preview and approval process.

Preview shows each person and resource, source times, conflicts, blocker explanations, manual verification reasons, and named approval holders. A manual reason does not override server policy. Unknown capability and leave remain blocked when the server disallows them. Changing proposal content invalidates the preview. Re-preview retains the previous preview during its request. Approval decisions must return the same hash. Returned seats show their reasons. A second seat for an actor who already approved is disabled.

Pending commands show 處理中. Only committed commands show 已確認. Unknown and mismatched outcomes retain their command and draft and explain what remains unverified. Managers can reconcile. Queries and retries use the original command ID. HTTP 409 and 422 retain the draft and reopen the preview for correction. A definitive failed or rejected command offers editing before a new preview.

`canWriteDispatch` extends the shared slice-1 access module. Write entry points require boolean `dispatch_write=true`, PM or manager role, and the existing company-workspace restrictions. Read access accepts the board or write flag. Role and flag checks also apply to the direct dispatch route. The backend remains responsible for workspace settings and write authorization.

First reads use reserved skeleton geometry. Failed refreshes retain last-good rows and their age. HTTP 403 clears visible rows and counts. Week, scope and session changes use the existing request lifecycle and abort controllers. Dialog requests abort on workspace unmount. Action buttons disable during requests and show a reason. Source age is outside the live state region.

## Files

New production modules are `frontend/src/dispatchPublishModel.ts`, `DispatchWorkflowPage.tsx`, `DispatchWork.tsx`, `DispatchPublishDialog.tsx`, and `DispatchPublish.css`.

Integration changes are `App.tsx`, `IntegratedPages.tsx`, `DispatchBoard.tsx`, `dispatchBoardModel.ts`, `HomeDispatchCard.tsx`, `dispatchAccess.ts`, `api.ts`, and `types.ts`. The board parser recognizes published execution slots, `v4_task` provenance and publishing status.

New test files are `frontend/test-dispatch-publish.mjs` and `test-dispatch-publish-ui.mjs`. `test-home-dispatch.mjs` now checks the board and work links separately instead of assuming the first link is the board. `package.json` adds `test:dispatch-publish`.

Synthetic verification uses `frontend/fixtures/dispatchPublishSynthetic.json`, `frontend/qa/dispatch-publish-mock.mjs`, and the extended `frontend/qa/dispatch-board-vite.mjs`. Production imports neither the synthetic fixtures nor the mock.

## Contract assumptions for integration

All new wire parsing, endpoint paths and request serialization are in `dispatchPublishModel.ts`. External values enter as unknown. Unknown enum values become unknown, and unknown action names are excluded. Unsupported feasibility or approval-seat values cannot enable publishing. The original board parser remains the slice-1 boundary.

The authoritative SOP defines endpoint names and domain shapes, but leaves several wire details unspecified. The synthetic adapter makes these explicit assumptions.

- Work responses carry `source.fetched_at` and `source.quality.states`. Work rows carry the optional `preview_id`, `parent_task_ref`, `department`, `scope_version`, `rule_version`, `evidence_version`, `read_back_at`, `acceptance_summary`, and a display string `node_position`.
- Preview feasibility is an array of `{kind,ref,label,state,reasons}`. Required seats are objects with `seat`, `holder`, `status`, `reason`, and `actor`. A holder is `{person_ref,name,avatar_url?}`. Its person reference must correspond to the authenticated actor identity for seat buttons. Source vectors contain schedule and task objects with `fetched_at`.
- Draft persistence uses `POST /api/v2/dispatch/drafts` with `{draft_id,proposal,preview_id,command_id,saved_at}`, returning the saved draft. `GET` returns `{drafts:[...]}`. Cancellation uses `POST /api/v2/dispatch/drafts/{id}/cancel`. These paths and wire shapes are provisional because Addendum A requires persistence without defining endpoints. Local copies are scoped by workspace and user and preserve unsent commands when the server is unavailable.
- Assignment pickers use people, cases and resources represented in the current board plus the selected task. A complete master catalog is not defined in the supplied contract. Completely unrepresented resources need an agreed catalog response or additions to the board before they can be selected. The frontend does not fabricate inventory or case identities.

`docs/dispatch-publish-api-examples.json` was absent from both the shared source checkout and this worktree at verification time. Backend integration must reconcile these assumptions with that file. There was no live Lark write, deployment or push. No `backend/` file changed. The synthetic mock is a UI fixture, not proof of backend transactions, reservations or cross-process races.

## Verification

The model test was written first and initially failed with a missing implementation module. Later literal tests failed before the numeric scope-version and unknown phase/quality fixes. Mounted tests exercise actual React handlers and outgoing request bodies. They cover access, all 21 drawer fields, task and obligation identity, draft identity, pending display, same-ID retry after a server failure and reload with a missing command lookup, command-only recovery without a preview, contradictory HTTP 202 handling, outcome-unknown reconciliation, HTTP 409 retention, last-good reads and HTTP 403 clearing. A regression also verifies that reassignment opens the editable form when the work row already has a preview ID, rather than silently restoring its approval page.

The following final commands pass. Logs and exit codes are under `output/dispatch-publish/`.

- `npm run build`.
- `npx tsc --noEmit -p tsconfig.json`.
- `node test-dispatch-board.mjs`, including its 64 literal checks and nine regression tests.
- `node test-contrast.mjs`.
- `npm run test:dispatch-publish`.
- `node test-home-dispatch.mjs`.
- `git diff --check`.

The existing board SSR tests still emit their layout-effect warnings. No unrelated baseline test suite was changed or used to mask a failure. The nine known baseline failures were outside this verification run.

The real Vite application ran with `DISPATCH_TEST_PORT=5202 node qa/dispatch-board-vite.mjs`. T3 collaborative preview drove the visible controls. Mock state is switchable through `POST /__dispatch-test/state`. Publish scenarios are `loaded`, `work_queue`, `conflict_409`, `pending_202`, `outcome_unknown`, `reconciliation_required`, `failed`, `blocked_unknown`, `forbidden`, `write_flag_off`, `flag_off`, `stale`, and `http_failed`. Existing board scenarios remain supported. `role` and `actor` can select an isolated synthetic identity. `delay` selects request latency.

## Browser evidence

There are 52 PNGs in `output/dispatch-publish/`. Every scenario below has `-1280.png` and `-390.png` variants.

- `work-queue`, `loading`, `stale`, `retained-failure`, `forbidden`.
- `board-entry`, `new-assignment`, `form`, `form-time-resources`, `detail`.
- `preview`, `approvals`, `needs-me-approval`, `needs-me-reconcile`, `returned`, `saved-draft`.
- `confirmed`, `pending-202`, `outcome-unknown`, `reconciled`, `needs-reconciliation`, `failed`, `conflict-409`, `blocked-unknown`.
- `write-flag-off`, `flag-off`.

`browser-evidence.json` records viewport and document width and reserved section positions. All saved widths match their viewport. The cold and loaded work views place 需要我處理 at the same position at both widths. Desktop captures use 1280 by 1500 and mobile captures use 390 by 1900. Escape closes the dialog and restores the trigger. Shift-Tab from the first dialog button wraps to the final enabled dialog action. Steps stack on mobile, and the action bar stays visible while the form scrolls. These keyboard actions were driven on the real 390px page.

Model the Domain shaped the typed proposal, preview, work and command boundary. Type System Discipline shaped unknown enum handling and numeric version parsing. Test Behavior, Not Implementation shaped literal UI text and request-body assertions. Prove It Works found the duplicate local draft ID and verified its fixed behavior on the running app. Those leaf skills were read during this task.

The throughput checkpoint kept contract study, tests, implementation and real-artifact verification sequential because they share one coupled frontend workflow. Architecture and implementation stayed in-thread under the explicitly assigned implementation-subagent role. No nested agents or PRs were created. Independent review remains with the parent task.
