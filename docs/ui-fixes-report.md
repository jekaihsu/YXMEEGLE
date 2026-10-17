# UI/UX fixes — ui-core

Completed all eleven requested fixes in priority order, with one focused implementation commit per fix. The five specified product decisions remain deferred.

Workspace: `/Users/vc/orca/workspaces/YXMEEGLE/ui-core`; branch `ava-apple/ui-core`; starting HEAD `8c1965696e01f9d0936eef09475373be0e96592c`; final implementation HEAD `99aa345`.

Only frontend CSS/TSX changed in the implementation commits. This requested report is the sole repository evidence-file exception. No backend, dependencies or lockfiles changed; no push, PR or merge. Agent: Codex; exact runtime model/effort not exposed.

Read both independent reviews: `/Users/vc/.openclaw/workspace-anya/reports/ui-core/uiux-codex.md` and `uiux-claude.md`.

## Verification environment

Playwright Core with installed Chromium 1243, 1440×1000 and 390×844. Source frontend served on `http://127.0.0.1:5191` using `/tmp/yx-ui-spacing-evidence/vite-qa.config.mjs`, proxying only `/api` to the existing demo API at `http://127.0.0.1:8124` (health check HTTP 200). The browser intercepted requests and allowed only loopback GET/HEAD; no external API requests or save/submit/delete actions occurred. Checkbox clicks changed temporary local UI state and the participant dialog was cancelled.

Server command: `npm run dev -- --config /tmp/yx-ui-spacing-evidence/vite-qa.config.mjs --host 127.0.0.1 --port 5191` from frontend; Vite ready on 5191. The worker stops this server before settlement and leaves the pre-existing demo service untouched.

Evidence directory: `/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence`. Before captures show the immediately preceding verified state; after captures show each isolated fix. Final behavioral checks additionally inspect the combined artifact.

After each implementation commit, ran:

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/checks.mjs <fix-id>` — exit 0 for every final commit.

`npm run build` runs `tsc -b && vite build`. Every existing npm `test:*` script was then run, including bundle budgets; all 23 commands (build + 22 test scripts) exited 0 for each final implementation commit. Per-fix JSON files record each command and exit code, and logs retain stdout/stderr.

## Fix evidence

### P1-a — Completed workflow contrast

Removed conflicting completed-stage white-on-accent rules from brand CSS; pale stages now use readable design tokens. Completed, in-progress and pending legend dots have distinct green, blue and outlined treatments.

Commit: `3d555f0fa15d50a029456e1cb020033ecee0baa5`. Files: `frontend/src/brand-workspace.css`, `frontend/src/polish.css`.

Checks: `node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/checks.mjs P1-a` — exit 0; all 23 commands exit 0. [Command results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-a-checks.json), [full log](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-a-checks.log).

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P1-a before 'view=project&project=p1&tab=flow'` — exit 0.

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P1-a after 'view=project&project=p1&tab=flow'` — exit 0.

| Affected state | Before desktop / mobile | After desktop / mobile |
| --- | --- | --- |
| `view=project&project=p1&tab=flow` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-a-before-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-a-before-0-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-a-after-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-a-after-0-mobile.png) |

Full-page companions use the same names with `-full.png`; computed styles, element bounds, text and browser-request evidence: [P1-a-after.json](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-a-after.json).

### P1-b — Case-list workflow and validation labels

Root cause: STATUS.engineering_complete is the correct string 工程完成、財務待結. A no-wrap badge overflowed an 80px cell into adjacent validation/attention symbols. The status cell is wider, text wraps deliberately, the full string is in title, and validation shows 待確認 / 已驗證 / 不一致 with an accessible full label and title.

Commit: `78d1c109455a459723fc1b9b2acdd19e729d4164`. Files: `frontend/src/ProjectsList.css`, `frontend/src/ProjectsList.tsx`.

Checks: `node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/checks.mjs P1-b` — exit 0; all 23 commands exit 0. [Command results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-b-checks.json), [full log](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-b-checks.log).

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P1-b before view=projects` — exit 0.

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P1-b after view=projects` — exit 0.

| Affected state | Before desktop / mobile | After desktop / mobile |
| --- | --- | --- |
| `view=projects` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-b-before-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-b-before-0-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-b-after-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-b-after-0-mobile.png) |

Full-page companions use the same names with `-full.png`; computed styles, element bounds, text and browser-request evidence: [P1-b-after.json](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-b-after.json).

### P1-c — Seven-day desktop schedule

At 1440px the grid uses seven equal columns and no horizontal overflow. Auto-scroll runs only when scrolling is possible; Monday is fully visible on open. Narrow screens and XL text retain readable columns with an explicit horizontal-scroll hint.

Commit: `230dd316ac7092dfc14de1512b6c4b1c0288b042`. Files: `frontend/src/App.tsx`, `frontend/src/polish.css`.

Checks: `node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/checks.mjs P1-c` — exit 0; all 23 commands exit 0. [Command results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-c-checks.json), [full log](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-c-checks.log).

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P1-c before view=schedule` — exit 0.

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P1-c after view=schedule` — exit 0.

| Affected state | Before desktop / mobile | After desktop / mobile |
| --- | --- | --- |
| `view=schedule` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-c-before-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-c-before-0-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-c-after-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-c-after-0-mobile.png) |

Full-page companions use the same names with `-full.png`; computed styles, element bounds, text and browser-request evidence: [P1-c-after.json](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-c-after.json).

### P1-d — Mobile case cards

Below 600px the same paged table rows become stacked cards with the case name, status chip, PM, progress and due date. The table headings remain visually hidden for accessibility; one row data source preserves filters, paging and case links.

Commit: `17f19fcc3cbb9b148f9036c74e811c9a969599fe`. Files: `frontend/src/ProjectsList.css`.

Checks: `node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/checks.mjs P1-d` — exit 0; all 23 commands exit 0. [Command results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-d-checks.json), [full log](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-d-checks.log).

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P1-d before view=projects` — exit 0.

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P1-d after view=projects` — exit 0.

| Affected state | Before desktop / mobile | After desktop / mobile |
| --- | --- | --- |
| `view=projects` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-d-before-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-d-before-0-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-d-after-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-d-after-0-mobile.png) |

Full-page companions use the same names with `-full.png`; computed styles, element bounds, text and browser-request evidence: [P1-d-after.json](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P1-d-after.json).

### P2-e — Active mobile tabs and overflow cue

A document-lifetime shared helper watches section navigation and centers the active button on initial rendering and tab/route changes. Scroll edges and a visible text hint indicate additional tabs; the helper loads on demand to preserve the existing initial-JavaScript budget.

Commit: `ca868f9faa08f19ff1603986f48eeb982ce05931`. Files: `frontend/src/App.tsx`, `frontend/src/design/tabs.tsx`, `frontend/src/polish.css`.

Checks: `node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/checks.mjs P2-e` — exit 0; all 23 commands exit 0. [Command results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-checks.json), [full log](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-checks.log).

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P2-e before 'view=project&project=p1&tab=logs' 'view=admin&tab=jobs' view=approvals 'view=projects&tab=intake'` — exit 0.

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P2-e after 'view=project&project=p1&tab=logs' 'view=admin&tab=jobs' view=approvals 'view=projects&tab=intake'` — exit 0.

| Affected state | Before desktop / mobile | After desktop / mobile |
| --- | --- | --- |
| `view=project&project=p1&tab=logs` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-before-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-before-0-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-after-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-after-0-mobile.png) |
| `view=admin&tab=jobs` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-before-1-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-before-1-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-after-1-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-after-1-mobile.png) |
| `view=approvals` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-before-2-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-before-2-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-after-2-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-after-2-mobile.png) |
| `view=projects&tab=intake` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-before-3-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-before-3-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-after-3-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-after-3-mobile.png) |

Full-page companions use the same names with `-full.png`; computed styles, element bounds, text and browser-request evidence: [P2-e-after.json](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-e-after.json).

### P2-f — Sticky workload identities

The workload person/header column stays at the left edge with an opaque surface and separator while day cells scroll. The available local demo opens people mode at scrollLeft=0; captures deliberately scroll to Friday to reproduce and verify the reported identity-loss condition.

Commit: `33f7e7ba5a35c0dc6ded8135f1ceb5ee41285300`. Files: `frontend/src/polish.css`.

Checks: `node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/checks.mjs P2-f` — exit 0; all 23 commands exit 0. [Command results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-f-checks.json), [full log](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-f-checks.log).

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P2-f before 'view=schedule|people'` — exit 0.

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P2-f after 'view=schedule|people'` — exit 0.

| Affected state | Before desktop / mobile | After desktop / mobile |
| --- | --- | --- |
| `view=schedule|people` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-f-before-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-f-before-0-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-f-after-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-f-after-0-mobile.png) |

Full-page companions use the same names with `-full.png`; computed styles, element bounds, text and browser-request evidence: [P2-f-after.json](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-f-after.json).

### P2-g — Checkbox and owner-field targets

Schedule and participant checkbox labels have padded 44px hit targets. Participant choices use two columns on mobile; desktop owner fields have at least 240px and render the department without clipping.

Commit: `6367e9c97446fee3c5c3727a31aa4d9124c5624c`. Files: `frontend/src/polish.css`.

Checks: `node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/checks.mjs P2-g` — exit 0; all 23 commands exit 0. [Command results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-g-checks.json), [full log](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-g-checks.log).

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P2-g before 'view=project&project=p1&tab=data&section=participants|participants' view=schedule` — exit 0.

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P2-g after 'view=project&project=p1&tab=data&section=participants|participants' view=schedule` — exit 0.

| Affected state | Before desktop / mobile | After desktop / mobile |
| --- | --- | --- |
| `view=project&project=p1&tab=data&section=participants|participants` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-g-before-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-g-before-0-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-g-after-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-g-after-0-mobile.png) |
| `view=schedule` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-g-before-1-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-g-before-1-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-g-after-1-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-g-after-1-mobile.png) |

Full-page companions use the same names with `-full.png`; computed styles, element bounds, text and browser-request evidence: [P2-g-after.json](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-g-after.json).

### P2-h — Shared pill tab design

One design/tabs.css style gives My Work, Changes, Admin, Case detail and case-list filters the same rounded rail, 44px controls, 15px text and filled selected pill. The legacy underline is removed.

Commit: `6a69db78efd4afd3e79021244f22091ac758a0a0`. Files: `frontend/src/design/tabs.css`, `frontend/src/main.tsx`.

Checks: `node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/checks.mjs P2-h` — exit 0; all 23 commands exit 0. [Command results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-checks.json), [full log](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-checks.log).

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P2-h before view=work view=approvals 'view=admin&tab=people' 'view=project&project=p1&tab=overview'` — exit 0.

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P2-h after view=work view=approvals 'view=admin&tab=people' 'view=project&project=p1&tab=overview'` — exit 0.

| Affected state | Before desktop / mobile | After desktop / mobile |
| --- | --- | --- |
| `view=work` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-before-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-before-0-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-after-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-after-0-mobile.png) |
| `view=approvals` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-before-1-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-before-1-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-after-1-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-after-1-mobile.png) |
| `view=admin&tab=people` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-before-2-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-before-2-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-after-2-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-after-2-mobile.png) |
| `view=project&project=p1&tab=overview` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-before-3-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-before-3-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-after-3-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-after-3-mobile.png) |

Full-page companions use the same names with `-full.png`; computed styles, element bounds, text and browser-request evidence: [P2-h-after.json](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-h-after.json).

### P2-i — Overview activity and side-rail hierarchy

Activity rows use 12px/16px padding and 13px text. The daily disclaimer is a caption paragraph; progress tracks are taller (10px), wider and use brand blue fill.

Commit: `b189aace356b0e0c637641a072e7c1b51d276185`. Files: `frontend/src/DailyHome.css`, `frontend/src/DailyHome.tsx`, `frontend/src/ProjectDetail.css`.

Checks: `node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/checks.mjs P2-i` — exit 0; all 23 commands exit 0. [Command results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-checks.json), [full log](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-checks.log).

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P2-i before 'view=project&project=p1&tab=overview|activity' 'view=dashboard|activity' 'view=dashboard|daily' view=dashboard` — exit 0.

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P2-i after 'view=project&project=p1&tab=overview|activity' 'view=dashboard|activity' 'view=dashboard|daily' view=dashboard` — exit 0.

| Affected state | Before desktop / mobile | After desktop / mobile |
| --- | --- | --- |
| `view=project&project=p1&tab=overview|activity` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-before-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-before-0-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-after-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-after-0-mobile.png) |
| `view=dashboard|activity` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-before-1-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-before-1-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-after-1-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-after-1-mobile.png) |
| `view=dashboard|daily` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-before-2-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-before-2-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-after-2-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-after-2-mobile.png) |
| `view=dashboard` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-before-3-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-before-3-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-after-3-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-after-3-mobile.png) |

Full-page companions use the same names with `-full.png`; computed styles, element bounds, text and browser-request evidence: [P2-i-after.json](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-i-after.json).

### P2-j — Case data and page insets

The category toolbar aligns left. Basic-data fields use two columns with a 768px maximum width and stack on mobile. Cockpit, Tracking and Admin use the existing workspace gutter, matching other page titles.

Commit: `c842f47a1427d0a19da641e209823d61d7a0e602`. Files: `frontend/src/ProjectDetail.css`, `frontend/src/polish.css`.

Checks: `node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/checks.mjs P2-j` — exit 0; all 23 commands exit 0. [Command results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-checks.json), [full log](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-checks.log).

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P2-j before 'view=project&project=p1&tab=data&section=basic' view=company view=routines 'view=admin&tab=people'` — exit 0.

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P2-j after 'view=project&project=p1&tab=data&section=basic' view=company view=routines 'view=admin&tab=people'` — exit 0.

| Affected state | Before desktop / mobile | After desktop / mobile |
| --- | --- | --- |
| `view=project&project=p1&tab=data&section=basic` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-before-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-before-0-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-after-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-after-0-mobile.png) |
| `view=company` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-before-1-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-before-1-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-after-1-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-after-1-mobile.png) |
| `view=routines` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-before-2-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-before-2-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-after-2-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-after-2-mobile.png) |
| `view=admin&tab=people` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-before-3-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-before-3-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-after-3-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-after-3-mobile.png) |

Full-page companions use the same names with `-full.png`; computed styles, element bounds, text and browser-request evidence: [P2-j-after.json](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P2-j-after.json).

### P3-k — SOP localization

Published templates show 已發布 and stage keys use the existing NODE_NAMES vocabulary. Existing shared status translations replace duplicate local mappings; no template data is changed.

Commit: `99aa345f04ec8663dfdb32b3ec44de94826844db`. Files: `frontend/src/Operations.tsx`.

Checks: `node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/checks.mjs P3-k` — exit 0; all 23 commands exit 0. [Command results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P3-k-checks.json), [full log](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P3-k-checks.log).

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P3-k before 'view=admin&tab=sop|sop'` — exit 0.

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/capture.mjs P3-k after 'view=admin&tab=sop|sop'` — exit 0.

| Affected state | Before desktop / mobile | After desktop / mobile |
| --- | --- | --- |
| `view=admin&tab=sop|sop` | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P3-k-before-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P3-k-before-0-mobile.png) | [desktop](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P3-k-after-0-desktop.png) / [mobile](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P3-k-after-0-mobile.png) |

Full-page companions use the same names with `-full.png`; computed styles, element bounds, text and browser-request evidence: [P3-k-after.json](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/P3-k-after.json).

## Final rendered behavior verification

`node /Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/verify-final.mjs` — exit 0; 34 checks at both viewports, no runtime errors or blocked requests. [Results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/final-behavior.json).

- Completed-stage text contrast: light desktop minimum 4.66:1, dark desktop minimum 5.42:1, light mobile minimum 4.66:1, dark mobile minimum 5.42:1. Titles, owner text, counts and completed labels all meet 4.5:1. Theme-transition measurements wait 400ms for styles to settle.
- Desktop week shows all seven columns with scrollLeft=0; mobile cards expose columns 1, 2, 6, 8 and 9 within the viewport.
- Active tabs remain fully within their rails on initial/direct navigation and first-to-last tab changes across Case, Admin, Changes and filters.
- Sticky workload identity cells remain visible after horizontal scrolling; whole-label checkbox clicks toggle the intended control and label heights are at least 44px.
- Data grid stays within 768px; Dashboard, Cockpit, Tracking and Admin title x positions match at both viewports; expanded SOP contains localized publication/stage labels.
- [Mobile card accessibility snapshot](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/mobile-cards-accessibility.txt); [dark desktop flow](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/final-flow-dark-desktop.png), [dark mobile flow](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/final-flow-dark-mobile.png).

## Corrections during verification

Final commits and final evidence passed. During iteration, a mistaken CSS write was caught in the P1-c diff/screenshot, restored, and amended before proceeding. The initial P1-d duplicated card markup breached the entry budget (300799 bytes); an intermediate version exceeded the initial budget by 32 bytes; the final CSS-only cards passed. The P2-e helper initially referenced a browser-only MutationObserver global in jsdom; it now uses window.MutationObserver. Early P2-e bundle measurements exceeded the initial budget by 90/16 bytes; initialization moved into the existing startup effect and the final commit passed without changing budgets. The P2-i caption initially exceeded the initial budget by 15 bytes; removing an unnecessary class preserved the caption treatment and passed. Failed measurement of dark contrast before the color transition settled was corrected by waiting for the actual rendered styles; the final measured minimum is above 4.5:1.

The evidence-only report commit is followed by the same suite; [final command results](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/final-checks.json) and [final log](/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/final-checks.log) record its outcome. The report commit does not alter a rendered page.

## Deferred and unverified

- Deferred by instruction: My Work grouping, Company Cockpit restructuring, schedule-density redesign, workday date-picker redesign and native date locale.
- No requested fix remains unfixed. Browser checks use the existing local demo data and Chromium; Safari/Firefox, physical-device behavior, every role/data permutation and full dark-theme coverage of pages other than Flow remain unverified.
- The unchanged JavaScript budget has little headroom; all final checks nevertheless pass. No budget or test was relaxed.

Append-only decision evidence: `/Users/vc/.openclaw/workspace-anya/reports/ui-core/fix-evidence/decisions.tsv`. Browser and verification scripts are durable beside the screenshots, outside the repository.
