# Meegle V1 UI and work views

Implementation starts at `18eb1317d5f9bf605a05f0196c237daede3a9cdb`, branch `t3/meegle-v1-sop-review`. The supplied v0.2 brief is the specification; no companion PRD was available.

## Behavior

Before: SOP task lists did not expose completion policy or review controls. My Work panels omitted imported SOP work; progress/dashboard only exposed aggregate SOP completion.

After: task rows and inspector show routine, important, or formal policy. Routine executors complete directly without upload when no file is required; explicit file obligations offer latest local output selection and the existing uploader. Proof contains file ID, version, and SHA-256. Important executors submit numbered revisions, reviewers see the submitted note/file versions and can approve or return with a required reason. Returned executors see the reason and resubmission action. Formal tasks direct people to formal approval and have no completion button. Authorized actions continue to come from the existing backend.

Review retries preserve request IDs and exact expected/submission revisions. Stale errors reload task data with Traditional Chinese copy. Project SOP counters refresh after task changes.

Both My Work API shapes expose `sop_work` with assigned items and the permission-scoped reviewer queue; its entry is hidden when empty. Project progress and company dashboard expose separate `sop_signals` and matching `sop_items`, with dashboard per-case scopes. Current-state signals distinguish routine completed, important submitted, and important returned. Submitted excludes approved/returned tasks, returned excludes resubmitted tasks. Item IDs include engine and project. Aggregate SOP totals, operational work rows, dispatch publication and external approval retain their existing meanings.

## Verification

Python: `/Users/vc/Local/YXMEEGLE/.venv/bin/python`; all implementation commands ran in this worktree. `npm ci` installed missing frontend dependencies.

- `npm run build`: passed.
- `node test-sop-tasks.mjs`: **28 passed, 0 failed**; covers policy controls, typed latest-file proof, submission state, exact-revision approval/return, reason validation, request-ID retry, stale errors, counter drilldowns and queue visibility.
- Frontend script sweep below: **35 passed, 1 failed** (`test-home-panels.mjs`, identical failure freshly reproduced at `687a98b`).
- Known-base script group: **11 passed, 8 failed** across 19 Node tests, identical pass/fail counts and failing assertions on the complete `687a98b` archive. Failures are in shell-mode, dev-tooling, UX case detail and reports interactions. `test-project-flow-ui.mjs` freshly passes on both. No unrelated failures were chased.
- `python -m pytest backend/test_sop_v1_review.py backend/test_my_work.py backend/test_company_dashboard.py backend/test_project_progress.py backend/test_p2_int_routes.py -q`: **240 passed**. Includes real-app plain/panel My Work, dashboard and progress routes, restricted readers, current reviewers and count/list equality.
- `python -m pytest backend -q`: **4,948 passed, 2 failed, 22 skipped, 1 xfailed** on the first full background run (311.07s). Final full background repeat on the completed backend: **4,948 passed, 2 failed, 22 skipped, 1 xfailed**, 309.37s; the same two failures.
- Both failing tests were rerun on an isolated `git archive 687a98b` checkout without stashing: **2 failed** with the same assertions. `test_home_executable_tasks.py::test_valid_current_proxy_stays_visible_on_historical_data_date` sees an expired delegation; `test_read_scopes.py::test_denied_sop_read_does_not_materialize_case_and_read_grants_work_without_writes` expects a manager SOP denial but gets 200. The latter also failed on the implementation starting HEAD `18eb131` (**1 failed**). No authority code was changed to satisfy either old expectation.
- `git diff --check`: passed.

Frontend sweep command: run `node test-NAME.mjs` separately for:

`session-epoch`, `api-response`, `perf`, `overview-design`, `contrast`, `case-navigation`, `project-disabled-reasons`, `company-route`, `integration-routes`, `my-work-view`, `my-work-return-focus`, `my-work-integrated`, `source-health-view`, `drilldown-context`, `confirmation-list-view`, `case-detail-view`, `contract-detail-view`, `work-item-detail-view`, `manager-overview-view`, `p2-routes`, `pm-glance`, `sop-tasks`, `project-progress`, `project-flow-model`, `project-flow-round2`, `start-sop`, `quotes-ui`, `work-assigned-visibility`, `home-counts`, `unified-home`, `home-layout`, `home-panels`, `node-evidence`, `node-assignment-api`, `node-assignments`, `home-query-refresh`.

Known-base group command: `node --test --test-concurrency=1 --test-timeout=30000 test-shell-mode.mjs test-dev-tooling.mjs test-project-flow-ui.mjs test-ux-case-detail.mjs test-reports-interactions.mjs`. Base comparison uses the full pinned archive plus a fresh frontend build and symlinked installed dependencies.

Logs remain untracked under `output/v1-screens/`: `backend-full-final.log`, `backend-base-failures.log`, `backend-head18-failure.log`, `frontend-results.json`, individual `test-*.log`, `frontend-known-final.log`, `frontend-base-known.log`, `build.log`, and `visual.log`.

## Browser evidence

Used the isolated-review memory workflow with separate SQLite/upload storage, API port 8766, Vite port 5198 and a private Vite cache. Playwright Core was installed at `/tmp/meegle-v1-playwright`; Chrome ran headless. Synthetic ordinary assignee `u-control` had no SOP grants; reviewer `u-pm` used existing authority. UI actions reached the real demo API; no mocked mutation responses. The only enabled SOP-write flag was in this disposable demo process, as needed for the requested visual check. Screenshots were visually inspected after waiting for transitions. After completing one routine task, approving one important task and returning another, My Work shows routine completed=1, important submitted=0, important returned=1; approval does not increase routine completed.

Screenshots in `output/v1-screens/`:

- `01-routine-ready.png`
- `02-routine-completed.png`
- `03-important-submit.png`
- `04-important-submitted.png`
- `05-reviewer-approve.png`
- `05a-reviewer-queue.png`
- `06-reviewer-approved.png`
- `07-reviewer-return.png`
- `08-reviewer-returned.png`
- `09-executor-returned.png`
- `10-my-work.png`

## Limits and rollback

No migrations, roles, capabilities, RBAC changes, feature configuration changes, pushes, deployments, real Lark writes or notifications. Existing unresolved template/evidence semantics remain as recorded in `audit.md`. Upload permissions are unchanged: an SOP-only executor can select available output proof but may need an already-authorized uploader. Typed-file selection was tested in Node/backend tests; screenshots demonstrate no-file routine/review flows. PostgreSQL, live Lark and absent PRD A01–A55 acceptance are not claimed. Counter lists are not paginated; large SOP histories can enlarge projection payloads. Review request IDs survive retries while the task inspector remains mounted; remount recovery uses current server task state.

Rollback: revert this UI/projection commit; the backend policy and review enforcement from the earlier slice remains. Retain all SOP data and existing write gates.

## Changed paths

- `backend/app.py`
- `backend/company_dashboard.py`
- `backend/my_work.py`
- `backend/project_progress.py`
- `backend/sop_import/README.md`
- `backend/sop_import/service.py`
- `backend/test_company_dashboard.py`
- `backend/test_sop_v1_review.py`
- `frontend/src/App.tsx`
- `frontend/src/IntegratedPages.tsx`
- `frontend/src/ProjectFlow.tsx`
- `frontend/src/SopTaskInspector.tsx`
- `frontend/src/SopTasks.tsx`
- `frontend/src/companyDashboardTypes.ts`
- `frontend/src/homeViews/CompanyCards.tsx`
- `frontend/src/projectProgressApi.ts`
- `frontend/src/sopTaskApi.ts`
- `frontend/src/sopTaskModel.ts`
- `frontend/src/useHomePanels.ts`
- `frontend/src/useSopTasks.ts`
- `frontend/test-sop-tasks.mjs`
- `frontend/src/SopWorkInbox.tsx`
- `frontend/src/SopWorkSummary.tsx`
- `docs/meegle-v1/ui-views.md`
