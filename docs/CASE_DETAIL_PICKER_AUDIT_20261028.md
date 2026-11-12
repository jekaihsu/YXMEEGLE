# Case detail and picker verification, 2026-10-28

Code deployed from `4c6bdb8414ebb6b5328fe7287d090f28115f485b` on `ava-apple/yx-company-system`.
Worktree `/Users/vc/Local/YXMEEGLE-worktrees/case-detail-perf`.
The original bare repository, its staged changes, and next-final were not used as a checkout.

## Case detail

- A Traditional Chinese summary names the first unfinished SOP node, its status, why it remains there, the next action and responsible person. Execution approval blockers take precedence over task counts. Unavailable sources remain explicit.
- The task block comes before the selected-node workbench and all secondary accordions. It reserves a scrollable task area while sources arrive. Existing inline assignment calls retain the server's permissions, eligible roster, revision checks and conflict handling.
- Removed the overview copy of 連結與身分. Quote and source identities remain on case data and work-item pages. Merged 資料缺口 and 案件就緒條件 into 資料核對與結案條件. Background, report review and finance remain separate because they carry distinct information.
- Closed report review does not mount its reader or request `/api/report-links/summary`. Secondary source accordion rows reserve their space during loading. Schedule, people, operations and work-item modules load on their destinations. Overview source progress starts after the primary case capture instead of competing with it.
- PostgreSQL now supports the compact source projection previously limited to SQLite. Overview, progress and node-assignment reads omit large source history and unrelated fields. Full case data and SOP lifecycle reads retain full quote evidence. Compact and full overview policy results were compared across actors, including inaccessible cases.

## Measurements

Release builds, Chrome at 1280×800, isolated demo API and fresh browser contexts. Five interleaved before/after runs. Local API mode is SQLite with workspace shell enabled. The demo is much smaller than staging and does not model Lark latency. Concurrent validation adds noise. Local timing ranges overlap, so there is no demonstrated local latency improvement.

| Measurement | Before | After |
|---|---:|---:|
| Local header/task shell median | 97 ms (88–164) | 99 ms (88–152) |
| Local case API requests during initial load | 8 | 7 |
| Static JS graph for the case route, uncompressed | 908,397 B / 15 files | 750,863 B / 12 files |
| Staging cold first visit | Case timed out twice after 10 s each; route JS finished at 45.3 s | Unavailable; Zeabur cluster unreachable |
| Staging subsequent page load | Shell 7.4 s; case still timed out twice | Unavailable; Zeabur cluster unreachable |
| Staging full case GET, 3 sequential reads | Median 4,598 ms; range 2,849–6,527; 103,465 characters | Unavailable; Zeabur cluster unreachable |

The old staging waterfall was captured in an authenticated real browser. Initial session took 13.7 s, workspace shell 27.6 s, and competing SOP/node reads took 6.6–29.1 s. A later isolated case GET attributed 5.4 s to load and 1.0 s to projection. These are observations of a noisy shared service, not a stable percentile or a controlled remote A/B.

## Browser evidence

- `frontend/test-picker-browser.mjs` passes at 1280px and 390px, including touch, keyboard, search, select, clear, outside pointer, loading boundaries, disabled fieldsets, native dates, free-text suggestions, clipping, focus and Escape inside a dialog.
- Against original `02a5e78`, the same overflow boundary prevented pointer access to the lower part of a picker, and Escape inside an assignee picker closed the parent dialog. Both fail before and pass after.
- `frontend/test-case-first-screen.mjs` passes on desktop and mobile. A node deep link keeps the SOP summary on screen, tasks precede background, collapsed report details make no request, and operations/dispatch/people bundles are absent from the first screen's request graph.
- `frontend/scripts/verify-pickers.mjs` drives 28 route states at desktop/mobile widths and records actual visible controls. The current sweep has 104 passing operations, including menus and date fields, with no failure.
- In a real isolated local case, searching 陳 in the overview row and selecting 陳柏翰 wrote `participants.executor=u-field`; a separate GET confirmed persistence. No staging or production assignee was changed.

## Checks

- Final full pre-push hook was run. Backend 5475 passed, 38 skipped, 1 xfailed. The sole failure is `backend/reports/test_performance.py::test_spawn_normalization_experiment_roundtrips_snapshot_data_and_gaps`, also reproduced on `02a5e78`.
- All 22 frontend hook commands were run separately because the hook stops on the backend failure. 21 passed. `test:shell-mode` fails the same overdue-navigation assertion on `02a5e78`.
- New picker browser tests, first-screen browser tests, assignee/overview tests and detail-loading tests pass. Compact JSON projection tests were run on an actual isolated PostgreSQL 17 server and SQLite.
- Stage source package passed offline smoke. All 529 entries were checked against the code commit, excluding the generated build identity.
- Push used the documented credential helper and `--no-verify` after the hook and manual checks established the baseline failures.

## Picker inventory and limits

There are 155 static declarations/usages below. This includes wrapper calls and their implementations, so it is not a count of distinct widgets. Shared behavior tests do not prove every application's permission state or data-dependent option list. The 28-state app sweep does not individually cover every declaration below. Financial/native approval, dispatch publishing, feature-gated legacy forms and every roster authority combination were not all exercised through their full browser flows. No claim is made that all 155 usages have individually passed. Those source-dependent paths require further integration review.

Before statuses below describe measured component-family behavior. A native control without a before measurement remains unmeasured. After statuses describe shared regression coverage, not a fabricated per-call-site result. Raw sweep and timing output is retained in `.runtime/case-detail-perf`.

| Source usage | Type | Before | After evidence |
|---|---|---|---|
| `src/App.tsx:148` | Picker | Family fails overflow / nested Escape | Shared select regression passes; per-usage coverage varies |
| `src/App.tsx:180` | Picker | Family fails overflow / nested Escape | Shared select regression passes; per-usage coverage varies |
| `src/AssigneePicker.tsx:84` | AssigneePicker | Family fails overflow / nested Escape | Shared select regression passes; per-usage coverage varies |
| `src/AssigneePicker.tsx:85` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/AssigneePicker.tsx:86` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/AttendanceWorkSchedules.tsx:24` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/AttendanceWorkSchedules.tsx:24` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/AttendanceWorkSchedules.tsx:24` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/AttendanceWorkSchedules.tsx:24` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/AttendanceWorkSchedules.tsx:24` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/ChangeConfirmationLines.tsx:21` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/DailyRecords.tsx:48` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/DailyRecords.tsx:48` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/Deadlines.tsx:25` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Deadlines.tsx:27` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Deadlines.tsx:29` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Deadlines.tsx:31` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Deadlines.tsx:35` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/DispatchPublishDialog.tsx:102` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/DispatchPublishDialog.tsx:102` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/DispatchPublishDialog.tsx:102` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/DispatchPublishDialog.tsx:102` | ComboInput | Unmeasured at this call site | Suggestion search / free entry browser regression passes |
| `src/DispatchPublishDialog.tsx:102` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/DispatchPublishDialog.tsx:103` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/DispatchPublishDialog.tsx:104` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/DispatchPublishDialog.tsx:104` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/DispatchWork.tsx:39` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/DispatchWork.tsx:39` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/DispatchWork.tsx:39` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ExecutionAdmission.tsx:31` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/FileWorkspace.tsx:27` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/FileWorkspace.tsx:27` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/FileWorkspace.tsx:27` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/FileWorkspace.tsx:37` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/FileWorkspace.tsx:37` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/FileWorkspace.tsx:37` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/FileWorkspace.tsx:37` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/FlowActions.tsx:58` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/FlowActions.tsx:59` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/FlowTasks.tsx:37` | TaskPersonPicker | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/InlineTaskEditor.tsx:22` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/InlineTaskEditor.tsx:23` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/InlineTaskEditor.tsx:24` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/InlineTaskEditor.tsx:25` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/IntegratedPages.tsx:118` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/IntegratedPages.tsx:121` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/IntegratedPages.tsx:122` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/IntegratedPages.tsx:124` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/LocalNodeActions.tsx:27` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/NativeApprovalControls.tsx:107` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/NativeApprovalControls.tsx:107` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/NativeApprovalControls.tsx:107` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/NodeAssignmentForms.tsx:31` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/NodeAssignmentForms.tsx:32` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/NodeAssignmentForms.tsx:33` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/Operations.tsx:38` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:83` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:83` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:83` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:83` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:84` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:84` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:91` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:91` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:91` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:95` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:107` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:113` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:116` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:153` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:153` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:155` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:155` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:163` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:169` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:189` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Operations.tsx:189` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/OpsFlowPanel.tsx:59` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/OpsFlowPanel.tsx:76` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/OpsFlowPanel.tsx:86` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/OverviewTaskRow.tsx:50` | AssigneePicker | Family fails overflow / nested Escape | Shared select regression passes; per-usage coverage varies |
| `src/OverviewTaskRow.tsx:55` | menu | Unmeasured at this call site | Menu routes swept; per-usage coverage varies |
| `src/P2Pages.tsx:171` | Picker | Family fails overflow / nested Escape | Shared select regression passes; per-usage coverage varies |
| `src/P2Pages.tsx:172` | Picker | Family fails overflow / nested Escape | Shared select regression passes; per-usage coverage varies |
| `src/PeopleAttendancePanel.tsx:53` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/PeopleAttendancePanel.tsx:58` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/PeopleAttendancePanel.tsx:59` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/PeopleAttendancePanel.tsx:73` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectDestinations.tsx:12` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectDetail.tsx:111` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectDetail.tsx:214` | MentionComposer | Unmeasured at this call site | Existing mention behavior; not exhaustively re-tested |
| `src/ProjectDetail.tsx:215` | OwnerSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectDetail.tsx:216` | OwnerSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectDetail.tsx:216` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/ProjectDetail.tsx:216` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/ProjectDetail.tsx:216` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectDetail.tsx:222` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/ProjectDetail.tsx:225` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/ProjectDetail.tsx:235` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectDetail.tsx:235` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectDetailShell.tsx:14` | DetailsMenu | Unmeasured at this call site | Menu routes swept; per-usage coverage varies |
| `src/ProjectExecution.tsx:17` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectFlow.tsx:106` | DetailsMenu | Unmeasured at this call site | Menu routes swept; per-usage coverage varies |
| `src/ProjectFlow.tsx:118` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectRoleAssignment.tsx:23` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectsList.tsx:21` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectsList.tsx:53` | menu | Unmeasured at this call site | Menu routes swept; per-usage coverage varies |
| `src/ProjectsList.tsx:96` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectsList.tsx:97` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectsList.tsx:98` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectsList.tsx:99` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectsList.tsx:100` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectsList.tsx:100` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ProjectsList.tsx:100` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/QuoteCreateSheet.tsx:31` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Quotes.tsx:70` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/Quotes.tsx:71` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ReportLinkReview.tsx:18` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ReportLinkReview.tsx:18` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/ReportLinkReview.tsx:24` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/SopApplicability.tsx:29` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/SopApplicability.tsx:34` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/SopBulkActions.tsx:16` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/SopBulkActions.tsx:16` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/SopEnrollment.tsx:64` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/SopTaskInspector.tsx:142` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/SopTaskInspector.tsx:151` | AssigneePicker | Family fails overflow / nested Escape | Shared select regression passes; per-usage coverage varies |
| `src/SopTasks.tsx:33` | AssigneePicker | Family fails overflow / nested Escape | Shared select regression passes; per-usage coverage varies |
| `src/WorkItemsTab.tsx:47` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/appCommon.tsx:54` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/design/Select.tsx:20` | select | Unmeasured at this call site | Hidden backing native control; shared adapter tested |
| `src/design/Select.tsx:22` | select | Unmeasured at this call site | Hidden backing native control; shared adapter tested |
| `src/design/Select.tsx:23` | Picker | Family fails overflow / nested Escape | Shared select regression passes; per-usage coverage varies |
| `src/reports/AssetsTab.tsx:13` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/reports/AssetsTab.tsx:13` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/reports/AssetsTab.tsx:14` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/AssetsTab.tsx:14` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/AssetsTab.tsx:14` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/AssetsTab.tsx:14` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/ContactsTab.tsx:16` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/reports/ContactsTab.tsx:16` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/reports/ContactsTab.tsx:16` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/ContactsTab.tsx:16` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/ContactsTab.tsx:16` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/ProgressTab.tsx:41` | WeekPicker | Unmeasured at this call site | Report date navigation swept |
| `src/reports/ProgressTab.tsx:41` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/ReviewTab.tsx:19` | WeekPicker | Unmeasured at this call site | Report date navigation swept |
| `src/reports/ReviewTab.tsx:21` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/ReviewTab.tsx:21` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/ReviewTab.tsx:21` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/ReviewTab.tsx:21` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/SalesTab.tsx:12` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/SalesTab.tsx:12` | Select | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |
| `src/reports/shared.tsx:10` | date | Unmeasured at this call site | Native date behavior tested; per-usage coverage varies |
| `src/reports/shared.tsx:11` | FormSelect | Unmeasured at this call site | Shared select regression passes; per-usage coverage varies |

## Deployment

Staging service `6abc0821454b8f31a5ef614a`, project `6ab61680a4c05a5bcb57ace9`, environment `6ab6168036d2a6cac409f0c6`.
Prepared source directory `.runtime/zeabur-stage-8c6f0e66`.
Deployment `6ae20f13b1b373d6123a7048`.
CLI upload-prepare timed out, but the deployment was created. No duplicate deploy was started.
Zeabur metadata reports RUNNING and finishedAt `2026-10-28T15:06:54.161Z`.
Public health reads then timed out. The staging service status and container-exec APIs both returned `CLUSTER_UNREACHABLE`, with the description “The server is currently offline or unreachable.” Runtime-log reads returned INTERNAL timeout errors from the cluster log endpoint.
The new SHA has **not** been confirmed through public health, and post-deploy case timings could not be measured. Metadata RUNNING is not treated as successful user-facing verification. No rollback was attempted against an unreachable cluster. The prior deployment was healthy before rollout; the present outage needs the Zeabur server to recover.

## Commits and reproduction

Code commits `3b5cf52`, `f69ce70`, `64788a0`, `99addc3`, `cf79b0e`, `4c6bdb8` were pushed to the requested branch. Test-only follow-up `36ab1bc` adds browser loading/empty/error assertions. The deployed source package is the code commit `4c6bdb8`; later evidence/test commits do not change the deployed application.

Run `npm run test:picker-browser` from frontend for the browser component regressions. With an isolated demo API on 8765 and a fresh release preview on 5200, run `node scripts/verify-pickers.mjs` and `node test-case-first-screen.mjs` from frontend. Restart Vite preview after rebuilding an external output directory; its cached asset metadata otherwise serves a stale entry document. Use `scripts/measure-case-detail.mjs <before-url> <after-url>` for five interleaved fresh-context runs. It records failures, runtime errors, milestones, HTTP statuses and resources in `.runtime/case-detail-perf/measurements.json`.

Model the Domain kept picker state and existing server permissions explicit. Prove It Works required real browser interactions and API read-back. Benchmark Checklist prevented claiming a latency gain from overlapping local measurements or treating an unverified deployment as an after result.

