# UI control spacing and Work Overview hero

Completed in `/Users/vc/orca/workspaces/YXMEEGLE/ui-core`, branch `ava-apple/ui-core`, from base `16bea2b`. Task `task_3f96455dc306`, dispatch `ctx_47d13c63b172`. Agent: Codex (exact runtime model/effort not exposed).

## Changes

- `frontend/src/design/tokens.css`: shared 44px control minimum, 10px vertical inset, 16px field/tab inset, 20px action-button inset.
- `frontend/src/design/controls.css`: centrally applies these dimensions to legacy and design-system buttons, tabs/segments, inputs, selects, textareas, icon actions and text actions. Selects reserve 32px at the native arrow; search wrappers retain their existing horizontal inset. Checkbox/radio/range/color/hidden input sizing is excluded. Larger page-specific textarea minima remain effective.
- `frontend/src/main.tsx`: imports the shared policy once. Sizing declarations use `!important` deliberately to beat existing high-specificity and lazy-loaded page overrides; layout, color, material, focus and state rules remain local. No per-page control fixes were needed.
- `frontend/src/DailyHome.css`: removes the blue left border and raised-shadow override from the Work Overview hero; uses 24px/32px desktop padding, 20px phone padding, 12px content gaps, a 1.35 title line height and a 1.65 subtitle line height. Existing rounded neutral surface, glass tokens and primary CTA styling are retained. Both full-workspace and shell heroes use this rule; business logic and labels are unchanged.
- This report is the explicitly requested evidence artifact outside `frontend/`. No backend, dependency, lockfile or unrelated page logic changed.

Shared-control commit: `2a71abab2f26286f7708db645b517f70ded64423`. Hero and this report form the separate second commit (read `git log -2 --oneline` for its final hash).

Verified Git blob hashes: `controls.css` = `6b9934dcba58ac5f31fb7ae9c34bad6d095aee9b`; `DailyHome.css` = `779162ac7fcce2ceeb1e4344ab17ee8bbc2deda8`.

## Environment and target flow

Flow: Work Overview -> hero CTA -> assigned task (full workspace), or My Work (shell); filters/pickers -> updated local page state; dialog -> cancel without saving.

Browser plugin not available. Used installed Playwright Core 1.63.0 and its existing Chromium 1243 binary; installed no packages. Final visual evidence comes from the built frontend at `http://127.0.0.1:5197`, with 1440×1000 and 390×844 viewports. A temporary Vite config at `/tmp/yx-ui-spacing-evidence/vite-qa.config.mjs` proxies `/api` to the existing local demo service at `http://127.0.0.1:8124`. The normal repository Vite config was not edited. The source app also ran with the same temporary config at `http://127.0.0.1:5187`.

The current workspace lacks a usable standalone backend Python environment: the existing sibling venv executable is missing and system Python has no Uvicorn/FastAPI. QA therefore used the already-running demo API, without modifying or restarting it. Its source revision is not asserted to match this frontend commit. Final main-route QA uses the real Vite HTTP proxy rather than browser response fixtures. The shell hero check separately injects `workspace_shell` and deterministic shell counts into demo responses because the available service defaults to full workspace mode; that is component/visual fixture coverage, not live shell API acceptance.

## Verification

| Check | Result / evidence |
| --- | --- |
| Typecheck and production bundle | PASS: `npm run build` executes `tsc -b && vite build`, exit 0; 1655 modules transformed |
| Existing frontend tests | PASS: all 22 `test:*` scripts, each exit 0 |
| Page identity and meaningful content | PASS: Work Overview, Case Overview, Case Detail, Case Flow, Daily Records, My Work, Schedule, Administration at both widths |
| Framework overlay | None seen in inspected screenshots/DOM |
| Console health | No collected page errors or console errors on 16 main-route checks; no warnings/errors on interaction checks |
| Responsive containment | No page-level horizontal overflow on the 16 main-route checks; wide tables and tab strips remain internally scrollable |
| Shared control dimensions | PASS: computed button, icon, text-action, input and select heights >=44px on all recorded main-route checks |
| Hero hierarchy | PASS: 24px/32px desktop or 20px phone padding, 12px gaps, equal neutral left/right borders; shell also checked in dark mode at XL text |
| Interaction proof | PASS: full hero CTA opened p7 PM task; shell CTA opened My Work; case search reduced to one matching case; date and owner pickers changed values; workday dialog opened/cancelled; add-task dialog rendered text/select/date/number controls |

Visual correction: initial schedule arrow controls retained a legacy 35px height; central authoritative minimum/auto height fixed it. An initial QA case URL used nonexistent `p-001`; corrected to the actual demo case `p1` and reran. Early dialog screenshots were captured mid-animation; final evidence waits for the transition to finish. An early result-audit heuristic requiring >300 body characters falsely rejected the compact Daily Records phone page; final audit checks page-specific content and known error states instead.

## Commands and exit codes

Commands run from the workspace unless marked frontend. Logs and replayable QA scripts are in `/tmp/yx-ui-spacing-evidence/`.

| Command | Exit / status |
| --- | --- |
| `npm run build` (frontend; initial and final) | 0; final output `final-build.log` |
| `npm run dev -- --host 127.0.0.1 --port 5186` (frontend) | Started; initial browser QA redirected API requests to demo service |
| `npm run dev -- --config /tmp/yx-ui-spacing-evidence/vite-qa.config.mjs --host 127.0.0.1 --port 5187` (frontend) | Started successfully |
| `npm run preview -- --config /tmp/yx-ui-spacing-evidence/vite-qa.config.mjs --host 127.0.0.1 --port 5197` (frontend) | Started successfully; serves final built app |
| `node /tmp/yx-ui-spacing-evidence/final-visual-qa.mjs` | 0; 16 route/viewport captures plus schedule dialog and people-table states |
| `node /tmp/yx-ui-spacing-evidence/final-interactions.mjs` | 0; both viewport interaction flows and form captures |
| `node /tmp/yx-ui-spacing-evidence/final-shell-hero.mjs` | 0; desktop, phone, dark/XL shell hero fixture |
| `node /tmp/yx-ui-spacing-evidence/verify-results.mjs` | 0; all recorded content/overflow/control-height assertions |
| `git diff --check` | 0 |
| Initial sibling-venv Uvicorn startup | 127; executable does not exist |
| Initial system `python3 -m uvicorn ...` startup | 1; module unavailable; existing demo service used instead |
| Initial inline result audit | 1; overly strict body-length heuristic, corrected as described above |

| Existing test command (frontend) | Exit |
| --- | --- |
| `npm run test:view-data` | 0 |
| `npm run test:audit-pagination` | 0 |
| `npm run test:audit-project-switch` | 0 |
| `npm run test:session-epoch` | 0 |
| `npm run test:daily-records` | 0 |
| `npm run test:comment-draft` | 0 |
| `npm run test:input-recovery` | 0 |
| `npm run test:native-approval-version` | 0 |
| `npm run test:native-approval-a11y` | 0 |
| `npm run test:financial-draft` | 0 |
| `npm run test:form-draft` | 0 |
| `npm run test:freshness-wiring` | 0 |
| `npm run test:data-freshness` | 0 |
| `npm run test:company-cockpit` | 0 |
| `npm run test:source-lifecycle` | 0 |
| `npm run test:execution-admission` | 0 |
| `npm run test:api-response` | 0 |
| `npm run test:perf` | 0 |
| `npm run test:contrast` | 0 |
| `npm run test:shell-mode` | 0 |
| `npm run test:dev-tooling` | 0 |
| `npm run test:live-read-regressions` | 0 |

Complete outputs: `/tmp/yx-ui-spacing-evidence/test-results.log`, `final-build.log`, `visual-summary.log`, `interaction-summary.log`, `shell-hero-summary.log`, `verification-summary.log`. Machine-readable results: `visual-results.json`, `interaction-results.json`, `shell-hero-results.json`. Append-only decision trail: `/tmp/yx-ui-spacing-evidence/decisions.tsv`.

## Screenshots and reference comparison

Reference directory: `/Users/vc/.openclaw/workspace-anya/media/inbound/openclaw-staged-cbb40f9c-c334-4b64-93bb-07bb00001708/` (both supplied PNGs inspected).

The hero reference has a heavy blue left stripe and tight content spacing; `shell-hero-desktop.png` shows the same title/subtitle/CTA with a uniform neutral border and balanced insets. The tab reference is addressed by the shared 10px vertical / 16px horizontal padding; `case-flow-desktop-viewport.png` shows the selected 流程與交付 tab with room around its label. The glass shell and pill control appearance remain consistent with PR #70. `controls-desktop.png` is an intermediate capture after the first padding edit, before the hero redesign; it is not a base-SHA screenshot.

All following paths are under `/tmp/yx-ui-spacing-evidence/`; final primary route screenshots are from the production bundle:

| Surface | Desktop screenshot | Narrow screenshot |
| --- | --- | --- |
| Work Overview | `/tmp/yx-ui-spacing-evidence/daily-home-desktop-viewport.png` | `/tmp/yx-ui-spacing-evidence/daily-home-narrow-viewport.png` |
| Case Overview | `/tmp/yx-ui-spacing-evidence/case-overview-desktop-viewport.png` | `/tmp/yx-ui-spacing-evidence/case-overview-narrow-viewport.png` |
| My Work table | `/tmp/yx-ui-spacing-evidence/my-work-desktop-viewport.png` | `/tmp/yx-ui-spacing-evidence/my-work-narrow-viewport.png` |
| Administration | `/tmp/yx-ui-spacing-evidence/administration-desktop-viewport.png` | `/tmp/yx-ui-spacing-evidence/administration-narrow-viewport.png` |
| Daily Records pickers | `/tmp/yx-ui-spacing-evidence/daily-records-desktop-viewport.png` | `/tmp/yx-ui-spacing-evidence/daily-records-narrow-viewport.png` |
| Case flow tabs | `/tmp/yx-ui-spacing-evidence/case-flow-desktop-viewport.png` | `/tmp/yx-ui-spacing-evidence/case-flow-narrow-viewport.png` |
| Task form dialog | `/tmp/yx-ui-spacing-evidence/task-form-desktop-viewport.png` | `/tmp/yx-ui-spacing-evidence/task-form-narrow-viewport.png` |
| Schedule date/owner pickers | `/tmp/yx-ui-spacing-evidence/schedule-pickers-desktop-viewport.png` | `/tmp/yx-ui-spacing-evidence/schedule-pickers-narrow-viewport.png` |
| Workday textarea dialog | `/tmp/yx-ui-spacing-evidence/schedule-dialog-desktop-viewport.png` | `/tmp/yx-ui-spacing-evidence/schedule-dialog-narrow-viewport.png` |
| Case search filtered state | `/tmp/yx-ui-spacing-evidence/case-search-desktop-viewport.png` | `/tmp/yx-ui-spacing-evidence/case-search-narrow-viewport.png` |
| Case Detail full page | `/tmp/yx-ui-spacing-evidence/case-detail-desktop.png` | `/tmp/yx-ui-spacing-evidence/case-detail-narrow.png` |
| Schedule people table | `/tmp/yx-ui-spacing-evidence/schedule-people-desktop.png` | `/tmp/yx-ui-spacing-evidence/schedule-people-narrow.png` |
| Reference shell hero fixture | `/tmp/yx-ui-spacing-evidence/shell-hero-desktop.png` | `/tmp/yx-ui-spacing-evidence/shell-hero-narrow.png` |

Additional dark/XL text check: `/tmp/yx-ui-spacing-evidence/shell-hero-narrow-dark-xl.png`. All eight main surfaces also have full-page `*-desktop.png` / `*-narrow.png` captures and DOM text files.

## Limitations

Shared CSS covers all page control families, including lazy-loaded pages, but not every route/data permutation was visually exercised. This was Chromium QA with demo data, not Safari/Firefox, actual phone hardware, company authentication, production API integration, native picker popup internals, or destructive save/submit actions. API-backed mutations were deliberately excluded from the screenshot/interaction scripts. Tables may intentionally scroll inside their containers, and fixed mobile navigation overlays the viewport portion of long full-page screenshots; viewport captures are included to make this clear. The supplied screenshot's shell hero was validated with a stated fixture; other primary routes used live local demo API responses. Existing unrelated workflow stage contrast was not redesigned.

Temporary task-owned Vite dev/preview servers were stopped after QA; the existing demo API was left running. No push, PR, merge, backend tests or deployment was performed. No acceptance-blocking UI issue remains in the checked surfaces; the coordinator can independently review the two commits and evidence.
