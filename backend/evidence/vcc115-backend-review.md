# VCC-115 backend endpoint review

Workspace: `/Users/vc/orca/workspaces/YXMEEGLE/vcc-115-backend`.
Base: `ava-apple/ui-core`, `16643acb712038fcd4c7826aff27155bb307bb8f`.
Final implementation: `c38f76f1d52c9d20f3debbb1f6fc78fb4621ffab` (ten focused fix commits; evidence commit follows).
Task/dispatch: `task_4eff756a6bb2` / `ctx_2b1c5f096569`.
Execution: Codex, described by the session as GPT-6; exact runtime model variant/effort unavailable. Sequential worker review; no independent reviewer was dispatched.

Ten confirmed defect groups found and fixed; zero confirmed endpoint defects deferred. Ownership stayed within `backend/` and its tests/evidence. No shared design/frontend/dependency files changed, and no push, PR, merge or deployment occurred.

## Fixed findings and regression evidence

| Finding | Previous behavior | Final behavior | Commit | Failing-before evidence |
| --- | --- | --- | --- | --- |
| Calendar collection types | Null/scalar/object lists caused server errors or inconsistent validation | Reject malformed lists/items before mutation; preserve calendar/version | `0d273e5` | 12 failures, `calendar-before.log` |
| Date contract | Python accepted compact/week encodings despite lexical date comparisons; daily filters accepted invalid/reversed ranges | Workflow requires canonical YYYY-MM-DD; daily queries return 422 for invalid ranges | `c01a9fa` | 8 failures, `dates-before.log` |
| Setting scalar types | Objects/strings/booleans could replace connection/numeric settings | Preserve default scalar types and require positive retention/recovery values | `cf99d4d` | 14 failures, `settings-before.log` |
| Mutation authorization | Revoked business grants/capabilities still allowed file-store, approval refresh, Input mapping verification and leave verification | Reauthorize the actor reloaded inside each mutation transaction | `9bdf134` | 2 initial and 2 sibling failures, `authority-before.log`, `authority-siblings-before.log` |
| Approval provider response | Malformed JSON/envelopes crashed; malformed status could be persisted | Sanitized 502, no version/approval changes; legitimate status stays explicitly unverified | `a343c33` | 8 failures, `provider-before.log` |
| Pilot-copy role | A manager demoted after initial identity could still copy a company case | Acquire destination lock and reload active company-manager authority before copying | `b7d3ef3` | 1 failure, `pilot-before.log` |
| SOP draft structure | Missing/object keys or scalar requirements crashed; object labels/duplicate nodes persisted | Require complete unique nodes, task lists, and text requirement keys/labels | `57fa9f9` | 5 failures, `sop-before.log` |
| Simulated cost parts | Scalars/non-object parts caused server errors | Reject malformed parts with 422; keep total/ownership checks | `dab49c9` | 5 failures, `cost-before.log` |
| Routine evidence | Objects/lists/numbers/booleans could be persisted as evidence; an object crashed the routines page | Shared action boundary requires text evidence; accepted text still enters pending review | `402c1d1` | 4 failures, `evidence-before.log`; browser HTTP 200 + React error #31 before, HTTP 422 + zero errors after |
| Redundant freshness reads | Unconfigured refresh read all datasets, making the 319-project shell use 25 queries against a limit of 24 | Preserve requested dataset metadata with scoped reads; shell uses 21 queries | `c38f76f` | 2 failures, `live-read-perf-before.log`; existing opt-in budget failed before |

79 added tests include valid input/authority controls and durable-state preservation checks. Existing tests were not weakened. The role-revocation tests use synthetic identities and provider responses; no colleague sessions or live remote writes were used.

## Page and boundary coverage

Read both requested UI reports and shared token/control/shell/polish/DailyHome styles before review. They established the visual context; this task required backend fixes only.

| Pages | Serving routes/mechanisms reviewed | Relevant coverage |
| --- | --- | --- |
| Dashboard / My Work | session identity, full workspace and indexed shell, task capability projection, action dispatch | Session/roster admission, current ownership/delegation, project visibility, private field projection, SQL/payload budgets |
| Projects / detail | project index and overview, partial detail load, workspace projection, project concurrency | Workspace scoping, hidden/history/reference cases, index fallback, pagination and project version fences |
| Schedule | work schedules in workspace, calendar/schedule actions, attendance sync | Calendar permissions, canonical dates, schedule-only source reads, verified attendance identities and current authority checks |
| Approvals | workspace approvals, legacy refresh, native request/confirm/operate handlers | Per-case actors, distinct financial seats, native receipt/binding consistency, mutation authorization, malformed provider response handling |
| Administration | person/settings/SOP actions, runtime/index health, audit/history, pilot copy | Admin/capability roles, current actor checks, scalar/nested input validation, bounded audit scans and visibility filters |
| Sources | GET/sync, live-read routes and source-sync service, Input verification/registration and file routes | Safe source/person projection, source-policy visibility, authority/policy/generation checks, destination isolation, uploads and CSV/download boundaries |
| Routines / daily records | recurring actions, daily index/mapping actions, normalized source projection | Evidence types, current project ownership, date/range validation, source identity/version checks and private raw-field removal |
| Cockpit | company dashboard over public workspace | Independent source/execution state, verified native review counts, executable workload, pagination/filtering, output whitelist |

Source review concentrated on endpoint transports and their authorization/validation/projection/storage consumers, including `app.py`, `integration_routes.py`, `native_routes.py`, `workflow.py`, `operations.py`, `management.py`, `input_validation.py`, `workspace_projection.py`, `source_case_policy.py`, `case_cutover.py`, `production_access.py`, `business_policy.py`, `shell.py`, `index_reads.py`, `storage.py`, `company_dashboard.py`, `source_projection.py`, and source/directory/attendance/live-read boundaries. This is scoped endpoint review, not a claim of exhaustive review of every backend file or every deployment configuration.

No additional confirmed injection, credential-disclosure, cross-workspace, or N+1 defect remained in the reviewed endpoint paths. Existing boundary/privacy/concurrency/index tests and company-scale SQL/payload budgets support that conclusion; they do not establish live production behavior.

## Verification

All logs, scripts, package inventory, screenshots and machine-readable browser results are durable at:
`/Users/vc/.openclaw/workspace-anya/reports/vcc115-backend-task_4eff756a6bb2/`.

| Command / artifact | Result |
| --- | --- |
| `.venv/bin/python -m pytest backend -q` baseline | 2375 passed, 10 skipped, exit 0 |
| Final `.venv/bin/python -m pytest backend -q` | 2454 passed, 10 skipped, 4 warnings, exit 0 (93.35 seconds) |
| `YX_RUN_PERF=1 .venv/bin/python -m pytest backend/test_perf_budget.py -q -s` | 9 passed, exit 0; shell 21 queries / 164518 raw bytes / 9412 gzip bytes; existing budgets unchanged |
| `npm ci` (frontend) | exit 0 |
| `npm run build` (frontend) | exit 0; TypeScript + production Vite bundle |
| All 22 package `test:*` scripts, invoked by Node/spawnSync | 22 passed, exit 0; `vcc115-frontend-tests.log` records each command/exit |
| `node browser-smoke.mjs` against implementation `c38f76f` | exit 0; 12 surfaces × 1440×1000 / 390×844; 24 captures; no console/page errors, failed HTTP requests or page overflow |
| `node routine-evidence-browser.mjs` | Before: exit 1, API wrongly accepted object and rendered React error #31; after: exit 0, malformed object rejected with 422 and valid text rendered with zero errors |
| `git diff --check` | exit 0 |

Browser routes: dashboard, projects, project overview, project flow, daily records, My Work, schedule, approvals, administration/settings, sources, routines, cockpit. Used the installed Playwright Core/Chromium 1243 binary and the production bundle served by this worktree's own Uvicorn backend at `http://127.0.0.1:8155`. Browser data was isolated demo SQLite at `/tmp/vcc115-browser.db`; response fixtures were not substituted. Sources/cockpit empty or unconfigured demo states are coverage of those states, not proof of populated Lark data. Screenshots include each page at both requested viewports; dashboard desktop and corrected routines phone images were inspected.

Focused passing-after logs: calendar 78 tests; dates 89; settings 112; authority 82; provider 27; pilot 60; SOP 71; cost 77 (command included the finance module twice); evidence 140; coordinator/routes/latency/opt-in performance 81. The full final suite is the authoritative final artifact check.

## Setup, corrections and practical limits

- Created a local venv. Initial system `python3` resolved to 3.9 and produced 44 collection errors because the backend uses Python 3.10+ union annotations; recreated that same local venv with the existing Python 3.12 interpreter.
- `pip install -r backend/requirements.lock` failed: configured package index lacked `annotated-types==0.8.0`. Installed the declared `backend/requirements.txt` in the venv; dependency files were not altered. Exact installed versions are retained in `python-packages.txt`. Locked dependency reproduction remains unverified.
- An initial date fix lacked its `valid_date` import; corrected it before committing and reran all selected tests. An initial SOP test command named a nonexistent test file and returned exit 4; corrected it and ran the real suites. Initial progress-comment minute labels were approximate; later comments use the actual clock.
- Default-suite skips include opt-in performance, unavailable PostgreSQL audit database and a platform-specific backup test. Performance was separately enabled. No production PostgreSQL service or live Lark OAuth/provider was used; formal authority/provider cases are synthetic local HTTP tests.
- Existing historical malformed evidence/settings/templates were not migrated. This task prevents new invalid writes and does not certify every existing production row.
- No requested backend UI-facing fix is deferred; coordinator review and production acceptance remain external to this worker.

Existing warnings: Starlette/httpx TestClient deprecation and three unregistered `perf` marker warnings; no console errors in either browser run. The decision TSV records implementation timestamps retrospectively from commits and final verification at the current clock.

## Changed files

- `backend/app.py`
- `backend/input_validation.py`
- `backend/integration_routes.py`
- `backend/live_read/coordinator.py`
- `backend/operations.py`
- `backend/test_approval_refresh_response.py`
- `backend/test_calendar_validation.py`
- `backend/test_cost_allocation_validation.py`
- `backend/test_date_query_validation.py`
- `backend/test_live_read_coordinator.py`
- `backend/test_pilot_copy_authority.py`
- `backend/test_review_mutation_authority.py`
- `backend/test_routine_evidence_validation.py`
- `backend/test_settings_validation.py`
- `backend/test_sop_draft_validation.py`
- `backend/workflow.py`
- `backend/evidence/vcc115-backend-review.md`
- `backend/evidence/vcc115-decisions.tsv`
