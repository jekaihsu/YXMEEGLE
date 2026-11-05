# Lark avatar verification

Implementation starts from d85caf8 in the isolated t3/lark-avatar-photos worktree.
No push, PR, deployment, scope change or Lark write was performed.

## Live evidence

The requested `lark-cli base +record-list` call succeeded with three records.
Its account cells contained `id` and `name`, with no `avatar_url`.
A complete read of only 姓名 and Lark帳號 returned 67 rows with `has_more=false`.
The shortcut response is not evidence that the v1 record API omits avatars.
The direct v1 GET was blocked by CLI authorization with code 99991679.
Its exact reported scope alternatives were `bitable:app:readonly`, `bitable:app`, and `base:record:retrieve`.
No authorization flow was started.

The read-only `/authen/v1/user_info` call returned `avatar_url`, `avatar_thumb`, `avatar_middle`, and `avatar_big` for Vincent.
All four used `s16-imfile-sg.feishucdn.com`.
The allowlist therefore accepts only HTTPS on `feishucdn.com` or its subdomains.
It rejects credentials, nonstandard ports, fragments, whitespace, backslashes and unrelated domains.
No access token or full login response is saved in this report.

The read-only contact user GET was also blocked by CLI authorization with code 99991679.
Its exact reported endpoint scope alternatives were `contact:contact.base:readonly`, `contact:contact:access_as_app`, `contact:contact:readonly`, and `contact:contact:readonly_as_app`.
Use the read-only base scope rather than requesting broad contact access.
The contact user avatar field requires `contact:user.base:readonly`; field visibility and the app contact visibility range also govern the response.
The avatar field scope was not exercised because endpoint authorization was denied.
The implementation makes no contact API request and adds no scopes.
The official endpoint documentation is https://open.feishu.cn/document/server-docs/contact-v3/user/get.

## People without a returned avatar

These named rows have no Lark account cell.

- 簡伯叡.
- 楊宜呈.
- 張健益.
- 林暉哲.
- Unnamed row.

These account-linked people had no avatar URL in the CLI shortcut response.
Their real photo availability through the v1 API could not be verified with the logged-in CLI scopes.

- 鍾智偉.
- 涂振邦.
- 陳誼靜.
- 郭倢瑛.
- 黃佑賢.
- 謝孟宗.
- 黃士嘉.
- 黃全佑.
- 張志豪.
- 余聖恩.
- 陳嘉略.
- 許庭豪.
- 鄭文澤.
- 鄭秉彜.
- 許峻瑋.
- 康益誌.
- 李炘龍.
- 林威仁.
- 陳振德.
- 黃耀興.
- 林宗翰.
- 李柏毅.
- 彭書逸.
- 蔡文銜.
- 吳宇軒.
- 張又升.
- 郭冠辰.
- 鐘傑嶙.
- 莊勇勝.
- 廖冠綸.
- 邱慶宗.
- 林士辰.
- 賴佳宏.
- 文乃毅.
- 王煜誠.
- 萬鈞.
- 陳靖羽.
- 林豐緯.
- 古恆安.
- 朱雅雯.
- 林佑靜.
- 李佳諭.
- 謝椀曳.
- 胡畯評.
- 黃馨加.
- 羅薇.
- 劉芳君.
- 沈宜蓁.
- 徐孟君.
- 郭國泰.
- 劉耀云.
- 廖堉惠.
- 謝佾均.
- 陳星穎.
- 林芷樓.
- 吳重樺.
- 張家彬.
- 朱雅琪.
- 吳柏頤.
- 莊博丞.
- 吳奇穎.
- 吳科翰.

Demo seed people retain initials because synthetic identities have no real Lark avatar.
Existing company profiles receive photos on the next successful login or directory refresh when those sources supply one.
V4 node assignment roster photos stay response-only and are not merged into company profiles.

## CSP and browser evidence

No Content-Security-Policy or img-src setting was found in backend/app.py, Dockerfile or repository headers configuration.
No CSP change was needed.
An external deployment proxy CSP is outside the repository and was not verified.
The shared Avatar component was mounted directly in the running Vite page for the browser check.
The application API was not started for this check.
The real login photo loaded in the collaborative browser with naturalWidth 72.
The avatar box measured 33 by 33 before and after a dispatched image error.
The fallback after the error was V, with zero image elements.
Node card avatar size and mobile size remain controlled by the existing na-avatar CSS.

## Test guard adjustment

The old ops-sync test rejected any change to people_directory.py by comparing it against a historical commit.
This task requires carrying the directory photo.
The historical capability_write_policy.py guard remains intact.
The directory field whitelist and assertions that directory membership grants no authority remain intact.

## Principles applied

Model the Domain made avatar_url an optional field on the existing person types.
Boundary Discipline placed URL validation at identity, Bitable and public response boundaries.
Test Behavior, Not Implementation led to literal person response expectations and DOM image error tests.
Prove It Works led to loading the observed photo and measuring the fallback box in the real browser.

Design, implementation and comment review ran in-thread because this is the implementation delegate and poteto-agent reserves child dispatch for the owning parent.
No independent review is claimed.

## Frontend verification

All 57 frontend/test-*.mjs scripts ran with the existing Chrome executable.
The two browser scripts needed an untracked local installation of playwright-core, which is absent from package.json.
56 scripts passed.
The only failing script also failed on the clean d85caf8 frontend archive with the same assertion.

```text
AssertionError [ERR_ASSERTION]: Expected values to be strictly deep-equal:
+ actual - expected

+ []
- [
-   '/api/projects/pA/node-assignments'
- ]
```

The failure is at test-shell-mode.mjs line 164.
No shell fetch behavior was changed for this task.

```text
Avatar image, error fallback, URL changes and allowlist tests passed
ops-sync panel: ok
Search input: 1440px native typing, replacement, clear, filtering and reload protection passed
Search input: 1024px native typing, replacement, clear, filtering and reload protection passed
people attendance view contracts passed
People page: search, filters, empty/reset, keyboard table, explicit refresh, re-entry, idle and permission safety passed
```

`./node_modules/.bin/tsc -b` exited 0 with no output.
The final `npm run build` exited 0.

```text
✓ built in 778ms
```

The focused final backend run covered avatar, OAuth, weekly people and the adjusted ops-sync guard.

```text
114 passed, 1 warning in 2.54s
```

The complete frontend script exit results follow.

```text
test-api-response.mjs 0
test-approval-detail-a11y.mjs 0
test-audit-pagination.mjs 0
test-audit-project-switch.mjs 0
test-avatar.mjs 0
test-case-detail-view.mjs 0
test-case-navigation.mjs 0
test-comment-draft-scope.mjs 0
test-company-cockpit.mjs 0
test-company-route.mjs 0
test-confirmation-list-view.mjs 0
test-contract-detail-view.mjs 0
test-contrast.mjs 0
test-daily-records.mjs 0
test-data-freshness.mjs 0
test-data-state.mjs 0
test-dev-tooling.mjs 0
test-draft-callsites.mjs 0
test-drilldown-context.mjs 0
test-execution-admission.mjs 0
test-financial-draft-scope.mjs 0
test-form-draft-identity.mjs 0
test-freshness-wiring.mjs 0
test-home-executable.mjs 0
test-home-review-regressions.mjs 0
test-input-recovery.mjs 0
test-integration-routes.mjs 0
test-lark-pilot-contract.mjs 0
test-lark-pilot.mjs 0
test-live-read-regressions.mjs 0
test-manager-overview-view.mjs 0
test-my-work-integrated.mjs 0
test-my-work-return-focus.mjs 0
test-my-work-view.mjs 0
test-native-approval-a11y.mjs 0
test-native-approval-version.mjs 0
test-node-assignment-api.mjs 0
test-node-assignments.mjs 0
test-ops-flow-view.mjs 0
test-ops-sync-panel.mjs 0
test-overview-design.mjs 0
test-p2-routes.mjs 0
test-people-attendance.mjs 0
test-perf.mjs 0
test-pm-glance.mjs 0
test-project-disabled-reasons.mjs 0
test-recurring-draft-period.mjs 0
test-search-input.mjs 0
test-session-epoch.mjs 0
test-shell-mode.mjs 1
test-source-coverage-views.mjs 0
test-source-health-view.mjs 0
test-source-lifecycle.mjs 0
test-taipei-time.mjs 0
test-view-data.mjs 0
test-work-assigned-visibility.mjs 0
test-work-item-detail-view.mjs 0
```

## Committed backend verification

The requested `python -m pytest backend -q` used the supplied Python venv against the committed implementation.

```text
3960 passed, 20 skipped, 1 xfailed, 5 warnings in 200.50s (0:03:20)
```
