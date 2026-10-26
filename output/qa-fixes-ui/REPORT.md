Branch `t3/qa-fixes-ui`. Base `9f92eb492131e27eda8fcc21f9ba4115885ede02`.
Verified source HEAD `7f304fab47af5e086cb3d54c4ce0b46954f4905b`.
The final evidence commit changes only this output directory.

Commits in order. Each regression-test commit precedes its implementation.
- `4a1d79b` test missing breadcrumb labels.
- `1d6a95a` fix the exhaustive route label table shared by breadcrumbs and navigation.
- `5a94fb7` test missing source read details.
- `7982cb4` expose authorized read summaries, Taipei times, missing timestamps and forced retry.
- `a96b89a` test stale retries and coalesced progress requests.
- `98d48c6` bypass pending reads, fence older completions and reject stale retry results.
- `97a24ea` test staged build identity and health metadata.
- `7f304fa` write and expose build identity in the staged backend and sources UI.

Root causes and evidence.
- F01. AppShell derived breadcrumbs from NAV, which omits work, sources, dispatch and detail routes. Its default was 資料來源. `before-work.png` and `f01-red.txt` reproduce this. `test-route-labels.mjs` covers every displayed view and the three work tabs. Real browser navigation and direct reload pass.
- F02. Both the source-health endpoint and SourceHealthPage disabled diagnostics. Source read timestamps already existed. The endpoint now returns visibility-filtered names, states and successful times without record values or raw source identifiers. Backend error strings become safe summaries. Missing times remain unknown. `f02-red-*`, backend tests and sources screenshots show the change.
- F03. useProjectProgress returned a pending read even for force=true, and accepted stale HTTP 200 payloads as ready. Retrying now starts a separate request. Older responses cannot overwrite its cache. A stale/unknown/error result ends in an explicit failed state with last-success time and retry. Scoped backend progress reads have no response cache; source synchronization and report snapshots can still be stale. These remain failed rather than being presented as a successful refresh. `before-timeout.png`, `before-retry-stale.png`, `f03-red-*` and browser results reproduce and verify both outcomes.
- F04. The deployment package and health endpoint had no build identity. The stage builder now generates backend/build-manifest.json with git_sha, dirty, built_at in UTC and branch, included in package inventory. Health returns only these fields, or build:null without a valid manifest. Sources shows the short SHA. `stage.txt`, `health.json` and backend tests verify the actual staged API.

Verification.
- PASS. `npx tsc --noEmit` from frontend. See `typecheck.txt`.
- PASS. Scratch Vite build, outside frontend/dist. See `build.txt`.
- PASS. All six touched/new Node test files, plus evidence, freshness and work-item suites. See `head/`.
- PASS against baseline. Full loop ran 118 base files and 121 head files. Base 105 pass / 13 fail. Head 108 pass / 13 fail. Identical failure set, zero new failures. See `verification.json` and both `results.json` files. The two macOS timeout-command failures are present on both revisions.
- PASS. Focused backend suite has 269 passing tests. See `backend-tests.txt`.
- PASS. Chrome at 1440 and 390 widths. Work tabs plus reload; source states, times, error and force:true retry; real 30-second client timeout; stale failure followed by independent fresh response; real dev/staged health fields. No page errors. See `browser-results.json` and `browser-walk.mjs`.
- PASS. All final commit messages include the requested co-author trailer. No push, deployment or PR was performed.

Screenshots.
- `work-{assigned,delegated,local}-1440.png`.
- `sources-1440.png` and `sources-390.png`.
- `items-timeout-1440.png`.
- `items-retry-{failed,fresh}-{1440,390}.png`.

Limits.
- No real Lark or business records were touched. Source and engineering browser responses are controlled synthetic fixtures intercepted in the isolated demo instance.
- Actual live staging SHA, authoritative engineering quantities and live Lark refresh behavior were not verified. This is not live staging sign-off.
- The 13 existing frontend failure files remain. Their base and head evidence is retained.

Principles applied. Model the Domain made the route label map exhaustive. Fix Root Causes put retry state in the progress reader. Prove It Works required the isolated browser walk and real packaged health endpoint.

To repeat in this worktree, install playwright-core under .runtime/qa and use Chrome. Start the demo API on 8876, scratch Vite on 5299, and the freshly prepared stage API on 8877 with separate scratch SQLite files. Run browser-walk.mjs from the worktree root. Run node-test-loop.py base and head to rebuild to scratch and compare all Node files. All evidence uses local synthetic data.
