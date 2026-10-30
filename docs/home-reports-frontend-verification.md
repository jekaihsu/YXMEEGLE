# Home report frontend verification

Implemented only in `/Users/vc/.t3/worktrees/YXMEEGLE/home-reports-fe` on `t3/home-reports-frontend`. No backend files changed. No push or PR.

## Registry

Company sections are `todo`, `quality`, `business`, `progress`, `resources`, `people`, `shortcuts`. Mine and assign section orders and defaults remain unchanged. The former `cases` section is removed. The `cases` card is now in `todo`. `groups` and `statuses` are in `progress`.

| Card | Title | Section | Views |
| --- | --- | --- | --- |
| `attention` | 週報待追蹤 | todo | company |
| `qualityTrend` | 外業失誤率 · 12 週 | quality | company |
| `qualityGroups` | 各組失誤率 | quality | company |
| `funnel` | 合約 → 請款 → 入帳 | business | company |
| `receivables` | 應收未收前 5 案 | business | company |
| `achievement` | 預排達成率 | progress | company |
| `instruments` | 儀器 | resources | company |
| `vehicles` | 車輛 | resources | company |
| `kpi` | 工作摘要 | summary | mine, assign, company |
| `work` | 我的工作 | todo | mine, assign |
| `confirmation` | 待我確認 | todo | mine, company |
| `deadlines` | 未來七天期限 | todo | mine |
| `allocation` | 待分配與待審核 | todo | assign |
| `workload` | 組員工作量 | people | assign |
| `delegated` | 我交辦的 | todo | assign |
| `groups` | 各組工作量 | progress | company |
| `cases` | 需留意案件 | todo | company |
| `statuses` | 案件狀態分布 | progress | company |
| `links` | 管理捷徑 | shortcuts | company |
| `leave` | 今日請假 | people | mine, company |
| `trips` | 今日出差 | people | mine, company |
| `absence` | 本週出勤 | people | assign, company |
| `impact` | 缺席影響 | people | assign |

Company default order.

`kpi, attention, confirmation, cases, qualityTrend, qualityGroups, funnel, receivables, achievement, statuses, groups, instruments, vehicles, leave, trips, absence, links`

The attention strip renders first in todo, outside the two-column card grid. It can be hidden. Its move controls are disabled. Remaining cards retain section-local ordering, equal row height, and full-row odd last cards. Saved v2 orders and hidden cases remain intact; missing report defaults are appended.

## Validation

- 11 of 13 requested home test scripts pass. Both failures were reproduced before any edits.
- `test-home-panels.mjs` fails its existing `/已核對案件/` assertion against the current MyWorkHub text.
- `test-home-target-navigation.mjs` fails because its company fixture lacks `source.status`. Neither failure was changed.
- All three scripts in `npm run test:reports` pass.
- `npx tsc -b` passes.
- Added checks total 69. They comprise 33 literal parser, insight and summary checks, 30 rendered checks, and 6 layout migration and attention placement checks.
- Rendered checks run under React StrictMode. They include pm and manager access, member and assign exclusion, all report cards hidden, one request, 403 and 404 no retry, a session change, late-response cancellation, stale and refresh_error notes, retained data after a 500, SVG gaps, clipboard success and manual fallback.

Logs are `/tmp/home-reports-fe-verify/tests.json`, `/tmp/home-reports-base-panels.log`, and `/tmp/home-reports-base-navigation.log`.

## Real browser checks

The demo backend ran from this worktree on 8766 with a fresh SQLite database and upload directory under `/tmp/home-reports-fe-verify`. Vite used the real frontend root, a scratch config, and the /api proxy on 127.0.0.1:5200. Chrome ran through the requested Playwright workflow with intercepted report payloads and session roles.

The session fixture pins a workspace identity. The demo backend initially returns a session without workspace_id, then establishes one on the next read. Pinning the fixture avoids treating that genuine session change as a forbidden-report retry.

| Requested check | Result | Evidence |
| --- | --- | --- |
| Equal top and height for each pair; odd last full width | Pass | Measurements below. Attention width 952px. |
| Section order | Pass | todo, quality, business, progress, resources, people, shortcuts. |
| Sentences and coverage notes | Pass | Browser assertions, quality and business screenshots. |
| Clipboard summary | Pass | Clipboard equals `copySummary(payload)` with permissions granted. |
| 403 cards hidden, no retry and no application exception | Pass | One request even after manual refresh, no cards or error banner, zero pageerror events. |
| 403 produces no console error of any kind | Fail | Chrome emits its native `Failed to load resource: the server responded with a status of 403 (Forbidden)`. No application console error or exception. |
| Member and lead preview do not request home reports | Pass | Zero requests for each. Company preview with member role also makes zero requests. |
| No horizontal overflow at 760px | Pass | document width 760px; home width and scrollWidth both 728px. |
| Screenshots saved | Pass | Paths below. |

At 1280 × 900, the grid width is 952px. Paired cards are 468px each. Values below are CSS pixels rounded to two decimals.

| Section | Cards | Top | Height | Width each |
| --- | --- | ---: | ---: | ---: |
| todo | confirmation, cases | 876.80 | 328.62 | 468 |
| quality | qualityTrend, qualityGroups | 1263.92 | 484.48 | 468 |
| business | funnel, receivables | 1806.91 | 604.45 | 468 |
| progress | achievement, statuses | 2469.86 | 435.23 | 468 |
| progress | groups | 2921.09 | 242.58 | 952 |
| resources | instruments, vehicles | 3222.17 | 467.03 | 468 |
| people | leave, trips | 3747.70 | 226.44 | 468 |
| people | absence | 3990.14 | 643.39 | 952 |
| shortcuts | links | 4692.03 | 220.94 | 952 |

Screenshots.

- `/tmp/home-reports-fe-verify/company.png`
- `/tmp/home-reports-fe-verify/company-quality.png`
- `/tmp/home-reports-fe-verify/company-business.png`
- `/tmp/home-reports-fe-verify/company-progress.png`
- `/tmp/home-reports-fe-verify/company-resources.png`
- `/tmp/home-reports-fe-verify/company-760.png`
- `/tmp/home-reports-fe-verify/forbidden.png`
- `/tmp/home-reports-fe-verify/member.png`
- `/tmp/home-reports-fe-verify/lead.png`
- `/tmp/home-reports-fe-verify/company-member.png`
- `/tmp/home-reports-fe-verify/stale.png`
- `/tmp/home-reports-fe-verify/stale-760.png`

Full browser measurements, request counts, console messages and clipboard text are in `/tmp/home-reports-fe-verify/evidence.json`. The adapted runner is `/tmp/home-reports-fe-verify/verify.mjs`. Viewport screenshots are used because Chrome full-page capture repeated fixed app chrome instead of capturing the offscreen report content. Section screenshots show the actual cards.

## Links, limits and decisions

Report links support tab navigation only. ReportsPage passes only tab selection to its views; useReport builds filters from view state and does not consume hash filters. The attention tiles and footers therefore use review, sales, progress and assets tab links without status or group filters.

The 24.9M received total divided by 48.6M contract total rounds to 51%. The mockup labels it 52%; the implemented deterministic rule uses the actual ratio. Previous-week absence is represented by `kpi_prev.error_rate = null`, as the fixed contract requires a Kpi object. Null parts stay null and missing numbers fail parsing.

ReportTrend is a minimal inline SVG. Existing TrendChart combines counts and rates on a fixed 0–100% axis, so it does not match the requested compact line-only presentation. Null weeks leave gaps.

No live backend report endpoint was integrated in this slice. Endpoint behavior was verified with contract-shaped intercepted responses as requested. Browser clipboard denial was covered by the rendered fallback test; granted browser clipboard access was tested on the real page.

Model the Domain shaped the central card registry and pure insights. Type System Discipline shaped unknown-input parsing and types derived from the existing report contract. Both leaf skills were read. Deslop and technical-writing guidance were applied to the final diff and this record.

Implementation stayed in-thread under the requested implementation-subagent role and single frontend owner. No child design or review agents were dispatched. No PR workflow ran.

The implementation meets the requested scope. The strict zero-console-message expectation for a browser-level HTTP 403 remains the one failed browser check.
