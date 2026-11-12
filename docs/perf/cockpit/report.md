# Company cockpit performance

The cockpit now starts after the authenticated session check, renders independently of the workspace response, and reuses an explicitly labeled snapshot when the user returns to the tab. Maintainers keep the existing visibility, redaction, project-state and admission code. The aggregate route skips personal task actions, policy summaries and attachment coverage that it never returns.

## Root causes and evidence

- `backend/app.py:555` previously passed the cockpit through the complete `public_ws` projection. `backend/workspace_projection.py:171` built personal queues and details for every task. `backend/home_details.py:153` recomputed execution and activation blockers. `backend/workflow.py:54` scans approvals for each blocker check. The isolated warm profile records 7,018 `build_home_task` calls and 319 `project_summary` calls before the change. It records neither afterward. See `projection-profile.txt`.
- `backend/operations.py:961` builds detailed financial, closure, node and topology summaries after refreshing project state. The cockpit consumes the refreshed project state but none of those summaries. `backend/app.py:410` now retains the same `refresh_project_state` operation for the aggregate route.
- `frontend/src/App.tsx:114` previously mounted the cockpit only after the workspace request completed. It now mounts after the existing session and recovery checks. The first workspace response no longer duplicates the cockpit read. `test-company-progressive.mjs` holds the workspace response open and verifies both the cockpit skeleton and its data appear independently.
- `frontend/src/CompanyCockpit.tsx:36` previously fetched on each mount, including a tab revisit. `frontend/src/companyDashboardCache.ts:9` now scopes up to 32 snapshots by the session epoch, refresh version and query. Manual refresh bypasses the cache. A workspace refresh invalidates it. An epoch key on the component removes the prior identity's visible snapshot immediately.

The attendance failure is real, but this branch already schedules refreshes without waiting. `backend/live_read/coordinator.py:237` defaults `ensure` to `wait=False`. `backend/app.py:537` and `backend/app.py:538` use that default for sources and attendance. The cockpit route makes no Lark requests itself. `backend/live_read/coordinator.py:263` coalesces each workspace and dataset key. Roster has a separate executor. These rules remain intact.

The second read-only Zeabur log request succeeded. It reported the following failures.

```text
2026-10-14T14:34:04Z Live-read refresh failed: dataset=attendance TimeoutError status=None detail= duration_ms=100266
2026-10-14T14:20:21Z Live-read refresh failed: dataset=attendance HTTPException status=502 detail=正常班表讀取失敗，保留上次成功資料 duration_ms=153823
```

The authenticated staging browser recorded one cockpit request at 13,346.4 ms. Its initial workspace request took 10,400.5 ms. These are single observations, not medians. No changes were pushed or deployed, so there is no staging measurement of the new code.

## Measurement design

`backend/benchmark_company_cockpit.py` runs the real HTTP routes with `TestClient`, SQLite, a fictional company workspace and `httpx.MockTransport`. It times session, shell workspace and cockpit responses, including response materialization. It does not time browser paint, real PostgreSQL, a production network or the Zeabur CPU.

Read-only Lark table lists on 2026-10-14 supplied the nine source table sizes. The mock returns every page, uses the real source field projection and completeness checks, and injects 250 ms for each request. The 67-person attendance mock uses the actual attendance reader for fourteen days and fourteen distinct shifts. It returns 938 schedule rows. The schema and business values are synthetic. The latency is an assumption, not a measured Lark latency.

The workspace is the existing 319-project, 7,018-task fixture. Its 9,000 daily reports, files, comments and review history are fictional workloads documented by `backend/perf_fixture.py`. These are not claims about today's staging workspace size. The current raw table counts are in `v4-table-counts.json` and `quote-table-counts.json`.

The initial unprofiled baseline ran five times before any application edit. It measured cold HTTP loads at a median of 591.348 ms, with a range of 542.515 to 674.188 ms. Warm loads had a median of 593.135 ms, with a range of 557.305 to 768.076 ms. See `baseline.json`.

The final comparison alternates baseline and optimized code five times each. The baseline adapter forces the unchanged full projection on the same final server code. Each pair uses a fresh database and mock transport. Background refreshes complete before the warm load. See `comparison.json`.

- Cold HTTP load. Median 705.842 ms before and 295.554 ms after. Before range 695.421 to 868.347 ms. After range 259.228 to 341.550 ms. Reduction 58.1 percent.
- Warm HTTP load. Median 698.167 ms before and 275.289 ms after. Before range 625.815 to 824.531 ms. After range 250.135 to 308.449 ms. Reduction 60.6 percent.
- Cold cockpit endpoint. Median 680.507 ms before and 269.888 ms after.
- Warm cockpit endpoint. Median 678.259 ms before and 245.713 ms after.
- Lark calls. Each cold load initiates 45 background calls. Each warm load adds zero. Sources use 29 calls including the tenant token. Attendance uses 16. Every run finishes both refreshes as fresh with zero retries and no failed HTTP responses.
- Data equivalence. All twenty cockpit responses have the same SHA-256 digest after excluding only `checked_at`. Each has 319 cases and 7,018 tasks, and the response size stays 31,807 bytes.

The machine had twelve logical cores and load averages of 2.70, 2.39 and 2.20 before the baseline. The final comparison overlapped the backend and frontend verification processes, so both sides were alternated under that extra load. The initial and final baselines differ. The reported improvement uses only the alternating final pairs.

## What limits the numbers

The profile identifies Python work in the response projection as the original HTTP limiter. The warm profile records 13.4 million calls before and 3.4 million after. The separate profile is not used for the reported HTTP speedup.

The remaining projection time is dominated by migration-archive traversal, source payload sanitization and case redaction. Those walks remain because they enforce the response contract. Database decoding, serialization and the other HTTP endpoints also remain in the timed load. The improvement cannot remove those costs.

The mock source refresh still takes about 9.74 to 9.78 seconds. Every source table is read sequentially, and both datasets share the unchanged five-request-per-second bucket. Forty-five calls require at least 8.8 seconds between the first and last reservations at that rate, plus request completion time. Their completion does not gate the cockpit response. Faster dataset fetching would not explain the measured HTTP improvement, so this patch does not alter the rate limit, TTLs, worker budgets or completeness rules.

## Safety and tradeoffs

The endpoint continues to call `identity`, validates its query, loads authoritative state, filters visible cases, derives execution admission, sanitizes source payloads and applies the same redaction plan. `company_dashboard.overview` keeps its existing output whitelist and aggregation rules. Full workspace responses still compute all personal task details.

A cache hit keeps the original source time and check time and displays `上次讀取快照，尚未重新查詢`. A failed refresh preserves the previous rows with the existing warning that they must not be treated as current. A new session or workspace refresh invalidates cached data. No cached snapshot grants permission to perform an action. Server admission remains authoritative.

The cockpit request now has a fifteen-second client timeout. This bounds the spinner and aborts the client request. It does not impose a new backend worker budget or forcibly cancel server computation. Large deployments might need that client limit tuned after staging verification.

The attendance timeout and roster errors remain unresolved background issues. No deployed speedup, production PostgreSQL behavior, company-scale browser paint time or actual Lark latency was measured after the patch. The independent parent review was not run inside this assigned implementation sub-agent.

## Verification

The requested backend command used the supplied virtualenv from this worktree.

```text
python -m pytest backend -q
3832 passed, 20 skipped, 1 xfailed, 5 warnings in 204.78s (0:03:24)
```

The slow and failing live-read tests also now include the cockpit route. The focused final run passed.

```text
14 passed, 5 warnings in 0.57s
```

Every `frontend/test-*.mjs` file ran. Two browser scripts initially lacked `playwright-core`. A local installation without a manifest or lockfile change supplied it, and both scripts used the installed Google Chrome executable. The final complete run produced the following summary.

```text
55 files, 0 failed
Company cockpit and runtime health: 41 checks passed
Company progressive load: 12 checks passed
ops-sync panel: ok
Search input: 1440px native typing, replacement, clear, filtering and reload protection passed
Search input: 1024px native typing, replacement, clear, filtering and reload protection passed
```

The production frontend build includes `tsc -b` and Vite.

```text
✓ 1708 modules transformed.
✓ built in 774ms
```

The final local built app also ran in the collaborative browser. It made one cockpit request at boot. A dashboard-to-cockpit revisit left that request count at one and showed the retained-snapshot label. See `local-browser.json` and `local-cockpit.png`. That small demo validates the built behavior, not company-scale performance.

Full outputs are in `backend-tests.txt`, `frontend-tests.txt`, `frontend-build.txt` and `frontend-browser-tests.txt`.

## Commits and reproduction

- `70db29c` captures the baseline and mock transport.
- `c061b2d` removes unused response projections and verifies equal aggregates.
- `76320fd` renders the cockpit early, caches labeled snapshots and tests identity changes and timeouts.

Run the comparison from the isolated worktree. Supply absolute output paths.

```sh
/Users/vc/Local/worktrees/YXMEEGLE/yx-company-system/.venv/bin/python -m backend.benchmark_company_cockpit --runs 5 --compare --output /Users/vc/.t3/worktrees/YXMEEGLE/cockpit-perf-20261014/docs/perf/cockpit/comparison.json
```

Explain the Number changed the fix from speculative Lark concurrency to measured projection removal. Model the Domain changed the cache into a bounded map keyed by session and refresh namespace. Sequence Work into Verifiable Units put the baseline, backend fix and UI fix in separate commits. Prove It Works required full output equality, timeout and identity tests, and a built browser run.

The implementation and verification steps ran in-thread because this task assigned this agent as the implementation delegate. No child agents, pushes, PRs or deployments were created.
