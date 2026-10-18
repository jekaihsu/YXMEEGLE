# Dispatch publish frontend integration verification

The sections through Changed files record round 1. The round 2 results at the end supersede them.

Worktree `/Users/vc/.t3/worktrees/YXMEEGLE/dispatch-s2`, branch `t3/dispatch-s2`. Starting commit `1be34e5`. Only `frontend/` and `output/` are changed by this implementation delegate. No push or deployment.

## Completed frontend checks

The model and mounted React tests read fixtures from the captured backend examples through `frontend/qa/dispatch-api-examples.mjs`.

- `npm run build` passed.
- `npx tsc --noEmit -p tsconfig.json` passed.
- `node test-dispatch-board.mjs` passed, including its nine dispatch-fix tests.
- `node test-contrast.mjs` passed.
- `npm run test:dispatch-publish` passed.
- `node test-api-response.mjs` passed after extending generic API errors to retain their unknown response payload.

These commands run from `frontend/`. Final checks use backend commit `5071939` plus the test-only follow-up `a83ce5a` and all 33 regenerated API examples. Command results and logs are recorded in `checks.json` and the adjacent `.log` files.

## Bugs fixed

- Provisional Chinese phase values and `manual_verifications` caused real preview requests to be refused. The adapter serializes `formal` or `intake`, `verifications`, supported keys and nullable optional fields.
- Work parsing discarded every preview and draft without a task ID. Rows now use a task, preview, draft or command identifier and retain their real source.
- Pickers used only people and resources already present on the board. They now read `/options`, include inactive and unlinked people with explanations, and allow their removal from existing assignments.
- Reassignment used a board-derived proposal. It now reads `/tasks/{id}` for authoritative prefill and system fields.
- Provisional draft POST and cancel endpoints did not exist. Drafts use PUT, GET and DELETE on the real routes and preserve optimistic version conflicts.
- A server draft-list refresh could overwrite local recovery metadata. In-flight command references now survive that refresh.
- Preview crew, resources, source timestamps, conflicts, verification keys, approval decisions and command task IDs did not match the wire shapes. The adapter now reads the captured shapes.
- A member who held the group-leader seat could not reach the approval UI. Company members can open the work view and operate only server-granted approval actions. Assignment remains restricted to PMs and managers.
- PMs could not reopen a preview that had no backend edit action. The work queue now offers a preview-review entry without inventing a new backend action.
- Approval changes in another login were not visible until a new proposal was created. A GET refresh now updates the same preview and its decisions.
- Editing a verification reason left the old approval controls active. Approval and publication now require a preview of the changed content.
- 409 and 422 errors lost blocker and seat-conflict reasons. Dispatch errors retain the real error body and translate all captured blocker codes into Chinese.
- Duplicate-command refusals now load the existing command. Commit retries retain the same UUIDv4. Definitive failed commands returned with 502 are displayed as failures.
- Reconciliation now follows the server's `next_action` instead of assuming every unknown command can be reconciled immediately.
- Publishing remounted the work view and reset its scope to mine. PMs could lose sight of a task they assigned to other people. Refresh now preserves filters and PMs default to all visible work. A mounted UI regression test covers scope retention.
- Work actions could overflow a fixed-height card when wrapping on a phone. Cards now grow to fit their actions.
- Missing estimated hours and revisions in legacy rows no longer display fabricated zeroes.

## Mock browser evidence

The Vite mock harness runs with `node frontend/qa/dispatch-board-vite.mjs` from the repository root. Production code does not import the mock. The final mock smoke run verified the work queue, options-backed form, 8 person-hour preview, approval and publish result. The form had no horizontal overflow at 390 CSS pixels.

- `mock-form-1280.png`.
- `mock-form-390.png`.
- `mock-confirmed-1280.png`.
- `mock-confirmed-390.png`.

These screenshots are explicitly mock evidence. The real FastAPI scenarios are recorded separately below when the other implementation delegate supplies `scripts/dev_dispatch_fake_server.py`.

## Real FastAPI verification

Passed against the real application from `scripts/dev_dispatch_fake_server.py`, using its in-memory fake Lark. No request went to a real Lark tenant. The fake server was started with the existing interpreter at `/Users/vc/Local/YXMEEGLE/.venv/bin/python`, since this worktree has no `.venv`.

The Vite configuration was written outside the repo at `/tmp/dispatch-publish-e2e-runtime/vite.config.mjs`. It uses this worktree's frontend as root, binds to localhost and proxies `/api` to `http://127.0.0.1:8766`. `changeOrigin` is false so the application's Origin guard receives the browser's Host. A separate real app with both dispatch flags off runs at 8767 behind a second Vite port 5200.

Playwright runs headless Chrome with Taipei time and a Chinese locale. It uses the dev login aliases and the visible UI for the main assignment, verification, three approval decisions, publication, reassignment, failed second publication and manager reconciliation. Both approved competing proposals are created through the real preview API to arrange the version race; the first is committed through that API and the second through the UI.

The verified scenarios are recorded in `real-result.json` and `real-network.json`.

- A PM sees progress, needs_me and allowed assignment actions.
- The full assignment form selects people, title, content, case, package, department, deadline, interval, 8 estimated person-hours, instruments and vehicle. It saves a server draft.
- The first preview calculates 4 hours times 2 people as 8 person-hours. Unknown feasibility blocks publication. Reasons are entered through the UI, and the second preview records the correct `person:ref` keys.
- Named group-leader, manager and PM seats are approved by three distinct dev logins. Publication uses a UUIDv4 and returns 200 committed.
- The confirmed task appears in the PM's work view. Its drawer contains 26 display fields, including every one of the 21 V4 extension fields.
- Reassignment loads `/tasks/{id}`, changes the owner and interval, gets three new decisions and updates that same task to revision 2.
- Two approved proposals target the same task. After the first commits, the second returns 409 `preview_stale`. The UI retains the proposal and explains the conflict.
- A one-shot `timeout_after_success` produces 202 `outcome_unknown` and the UI shows 結果不明. The manager follows `next_action` and reconciles the original UUID to committed. Exactly one `v4_task` row carries that command before final verification.
- The draft UI saves an incomplete form with no owner, detects a real 409 version conflict after another request updates it, preserves local content, loads server version 2, saves version 3, lists it and cancels it with DELETE. See `real-drafts.json`.
- A separate app with both flags off hides dispatch navigation, work and assignment controls. Its work endpoint returns 404. See `real-flag-off.json`.
- No page JavaScript errors were recorded. All captured 1280 and 390 CSS-pixel layouts passed the horizontal-overflow assertion.

### Screenshots

Each name below has both `-1280.png` and `-390.png` variants.

- `real-work-needs-me` shows the PM queue and its actions.
- `real-full-form` shows the assignment form.
- `real-unknown-blocked` and `real-verification-recorded` show feasibility and recorded reasons.
- `real-three-seats-approved` shows the approval process.
- `real-confirmed` shows the first committed command.
- `real-task-21-fields` and `real-task-21-fields-bottom` show the confirmed task detail.
- `real-reassigned` shows revision 2 of the same task.
- `real-competing-proposal-409` shows retained content after the losing proposal.
- `real-timeout-unknown` and `real-reconciled` show the same command before and after reconciliation.
- `real-final-queue` shows the final work queue.
- `real-draft-version-conflict`, `real-draft-saved` and `real-draft-cancelled` show draft recovery and cancellation.
- `real-flag-off` shows the disabled feature.

### Reproduce

Install Playwright outside the repo, or use an existing installation. The verification scripts accept its module URL in `DISPATCH_PLAYWRIGHT_MODULE` and the Chrome executable in `DISPATCH_CHROME`. The default Chrome path is the installed macOS Google Chrome app.

```sh
/Users/vc/Local/YXMEEGLE/.venv/bin/python scripts/dev_dispatch_fake_server.py --port 8766
DISPATCH_PLAYWRIGHT_MODULE=file:///tmp/dispatch-playwright-runtime/node_modules/playwright/index.mjs node frontend/qa/dispatch-real-e2e.mjs
DISPATCH_PLAYWRIGHT_MODULE=file:///tmp/dispatch-playwright-runtime/node_modules/playwright/index.mjs node frontend/qa/dispatch-flag-off-e2e.mjs
DISPATCH_PLAYWRIGHT_MODULE=file:///tmp/dispatch-playwright-runtime/node_modules/playwright/index.mjs node frontend/qa/dispatch-drafts-e2e.mjs
```

Start the scratch Vite proxies first. The main script expects a fresh fake database. The flag-off script expects the second app. `DISPATCH_E2E_URL` and `DISPATCH_FLAG_OFF_URL` override the frontend URLs.

## Remaining backend observation and verification limits

Round 1 observed an earlier unknown preview reappearing beside the committed task after its replacement preview was published. Commit `899091e` fixes that backend observation. This is a stale workbench proposal, not a second remote task. `BACKEND_FEEDBACK.md` records the reproduction and the backend join that causes it. The frontend labels preview proposals and written tasks separately and preserves the server's rows. It does not hide distinct proposals by comparing titles.

The browser's competing-proposal 409 is a stale-version conflict on the same task. A simultaneous new-task reservation race was not reproduced in the browser. The captured `reservation_conflict` response is exercised by the model and mounted UI tests. Reconciliation was tested against the fake Lark only. The task required no real tenant writes, push or deployment.

## Changed files

Production changes are in `frontend/src/dispatchPublishModel.ts`, `DispatchPublishDialog.tsx`, `DispatchWork.tsx`, `DispatchWorkflowPage.tsx`, `DispatchPublish.css`, `dispatchAccess.ts` and `api.ts`.

Tests and browser verification are in `frontend/test-dispatch-publish.mjs`, `test-dispatch-publish-ui.mjs`, `qa/dispatch-api-examples.mjs`, `qa/dispatch-publish-mock.mjs`, `qa/dispatch-real-e2e.mjs`, `qa/dispatch-flag-off-e2e.mjs` and `qa/dispatch-drafts-e2e.mjs`.

Only frontend and output paths are committed. The backend agent's commit remains separate.

Model the Domain kept external parsing, identity mapping and wire serialization in one adapter. Type System Discipline kept external response payloads unknown until that adapter parsed them. Prove It Works changed the verification from provisional mock assertions to a repeatable real FastAPI browser run, which found the scope-reset bug.


## Review round 2

Frontend implementation in `/Users/vc/.t3/worktrees/YXMEEGLE/dispatch-s2`, starting from `899091e`. Only `frontend/` and `output/` changed in this implementation. The concurrent backend agent owns backend, scripts and docs changes, committed as `63be12a`. The final browser runs use those changes. No push, deployment or real Lark tenant write occurred.

### Regression tests

`frontend/test-dispatch-round2.mjs` mounts the real React dialog and work view in jsdom. The initial run reproduced all six defects and both variants of defect 6. `round2-red.txt` preserves those failures. `round2-green.txt` records the final model, existing mounted UI and new regression results.

| Defect | Test name | Result |
| --- | --- | --- |
| 1 | R1 saved proposal wins over approved preview and approvals are void | PASS. Edit a reason on the approved preview, save, remount with the saved draft and an older flow proposal, assert the new reason and void seat labels, disabled publication and the next saved payload. |
| 2 | R2 failed reconciliation restores options task and parent obligation | PASS. Recover a command, reconcile to failed, enter the form, assert a named picker and the literal task and parent references in the next preview request. |
| 3 | R3 seat holder sees every hashed proposal field and exclusive interval | PASS. A member seat holder sees 20 read-only summary entries, with literal content, start, end, owner, case and exclusive-end wording. |
| 4 | R4 absent hours stay null omitted and show estimation hint | PASS. Null stays null, is absent from the wire payload, leaves the input blank and shows 系統依組員與時段估算. An explicitly entered zero still serializes as zero. |
| 5 | R5 unresolved display names never expose record IDs | PASS. Missing resource and feasibility names resolve to 名稱未能解析. Named summaries retain their display names. |
| 6 | R6 forbidden read clears open detail and actions | PASS. Open a real drawer, refresh to 403, assert the forbidden message and no dialog. A later successful read does not restore the drawer. |
| 6 | R6 identity epoch clears open detail before new read | PASS. Open a drawer, invalidate the session epoch, re-render and assert no dialog. |
| Wire changes | wire errors use plain Chinese and receipt reasons survive parsing | PASS. Covers changed seat holders, recheck unavailability, unknown department, department/node mismatch, own-preview refusal, search lag and missing base snapshot. |

The domain changes keep saved proposals separate from immutable previews, retain nullable estimates and parse preview case names and command preview references at the boundary. Approval-only entry points no longer create placeholder empty drafts. The summary displays each written proposal field from the preview that owns the hash. Task and parent identifiers are displayed as reference fields; unresolved display names never use those identifiers as names.

### Final commands

Run from `frontend/`.

```sh
npm run build
npx tsc --noEmit -p tsconfig.json
node test-dispatch-board.mjs
node test-contrast.mjs
npm run test:dispatch-publish
```

All five commands pass. The publish suite covers all 40 regenerated backend API examples, the existing mounted UI suite and eight round 2 checks. The board suite includes its nine regression tests. The unrelated nine baseline frontend failures were not part of this run. `git diff --check -- frontend output` also passes.

Before completion, both `docs/dispatch-publish-wire-changes.md` and `docs/dispatch-publish-api-examples.json` were re-read, including the round 2 section. The adapter translates `decision_holder_changed:<seat>`, `recheck_unavailable`, `invalid` with `field: department` and `reason: unknown_department`, `department_not_node_group`, `own_preview`, `already_published`, `search_lag` and `no_base_snapshot`. A 503 retry retains the original command identifier.

### Real browser evidence

Both runs use headless installed Chrome, the real React app, real FastAPI routes and SQLite, the dev server's in-memory fake Bitable, Taipei time and zh-TW locale. The full run uses the unmodified `scripts/dev_dispatch_fake_server.py` on 8768 with a scratch Vite proxy on 5201. The recovery run uses `frontend/qa/dispatch-round2-server.py` on 8769 with a proxy on 5202. That QA-only wrapper imports the existing dev server and adds a one-shot timeout before the fake remote write lands, plus a seeded parent obligation. It changes no backend application code. No browser request was mocked or fulfilled by Playwright.

```sh
/Users/vc/Local/YXMEEGLE/.venv/bin/python scripts/dev_dispatch_fake_server.py --port 8768
DISPATCH_E2E_URL=http://localhost:5201 DISPATCH_PLAYWRIGHT_MODULE=file:///tmp/dispatch-playwright-runtime/node_modules/playwright/index.mjs node frontend/qa/dispatch-real-e2e.mjs
/Users/vc/Local/YXMEEGLE/.venv/bin/python frontend/qa/dispatch-round2-server.py --port 8769
DISPATCH_E2E_RECOVERY_ONLY=1 DISPATCH_E2E_URL=http://localhost:5202 DISPATCH_PLAYWRIGHT_MODULE=file:///tmp/dispatch-playwright-runtime/node_modules/playwright/index.mjs node frontend/qa/dispatch-real-e2e.mjs
```

The two scratch Vite proxies point `/api` to their corresponding backend, with `changeOrigin: false`. Each run starts with a fresh fake database. The full run repeats assignment, drafts, unknown feasibility, three distinct approvals, publication, reassignment, competing-proposal 409 and successful reconciliation. It adds R1 by changing an approved reason, saving, closing, reopening, refreshing approvals, confirming publication remains disabled, and obtaining a fresh preview plus three new decisions. The recovery run adds R2 with a real update command that times out before landing, followed by manager reconciliation that returns 502 failed. The recovered form has named pickers and the original content. Its next preview keeps `task_id: recLegacy` and `parent_task_ref: recObligationQA`.

Results and requests are saved in `real-result.json`, `real-network.json`, `real-recovery-result.json` and `real-recovery-network.json`. Both result files report no page errors. Each screenshot below has `-1280.png` and `-390.png` variants in this directory. Both widths are checked for document overflow.

- `real-draft-reopened-changed` shows the void-approval warning and disabled publication.
- `real-draft-reopened-reason` shows the saved reason after reopening.
- `real-draft-approvals-void` shows the old seat decisions marked invalid.
- `real-reconcile-failed-form` shows the restored content after failed reconciliation.
- `real-reconcile-failed-form-parent` shows the preserved parent.
- `real-reconcile-failed-form-pickers` shows restored named people pickers.
- `real-recovery-seats-approved` shows the separate recovery scenario's seat holders.

Model the Domain kept nullable estimates and preview ownership in the existing model. Test Behavior, Not Implementation changed each regression into mounted UI or literal wire assertions. Prove It Works required real-browser replay and screenshots before completion. Architecture and implementation remained in-thread under the assigned implementation-subagent role. Independent review belongs to the parent task. No nested delegates or PRs were created.
