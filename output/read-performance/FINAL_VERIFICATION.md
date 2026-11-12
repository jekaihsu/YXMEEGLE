# Formal rollout verification — 2026-10-21

The application fixes are merged into `ava-apple/yx-company-system` through PRs [84](https://github.com/jekaihsu/YXMEEGLE/pull/84), [85](https://github.com/jekaihsu/YXMEEGLE/pull/85), and [86](https://github.com/jekaihsu/YXMEEGLE/pull/86). Final application revision: `e47bd6768d506f79cd0e0b0e29538978c89cd198`. The formal Zeabur source upload is `6ad8134787ff0bfa5af827dd`, serving https://yongxiang-projects-20260925.zeabur.app. All 198 runtime backend/script/configuration hashes match the frozen source package (inventory `1dcb9010833b0e8826e2545d0e9af27574a8cc63d34e4de1e634a3a17af6126f`). This is a source upload; the platform Git SHA field is empty. Health is 200.

`LIVE_VERIFICATION.md` and the `live-*` artifacts preserve the earlier, incomplete activation attempt. They are historical evidence, superseded by this report. The original tester did not independently confirm the preview URL or tester identity; this verification uses the user's authenticated formal preview account and the actual deployed PostgreSQL dataset.

## Configuration and explicit access

The two read flags, `INDEX_TABLES_ENABLED` and `WORKSPACE_SHELL_ENABLED`, are now true. The complete 40-variable environment was freshly read and preserved when adding these two keys; all other values were read back unchanged. SOP writes remain false. Node-assignment remains disabled as originally configured; its APIs are not claimed as successfully activated formal reads. Its behavior was tested locally and the enabled staging configuration was exercised separately.

The deployment package previously omitted both documented index operators, and their PostgreSQL URL aliases selected an uninstalled driver. PR 85 ships both operators and selects psycopg 3. The deployed migration and batched backfill completed successfully: 420 projects, 9,553 tasks, matching workspace/counter version 35438. After ordinary background activity and the final deployment, both versions had advanced to 35451 with 420 indexed projects. This verifies ongoing maintenance beyond the initial backfill. PostgreSQL is 17.11; all 37 workspaces use normalized storage schema 2. There is one Uvicorn web process and a separate durable worker, both UID 10001; no replica/concurrency assumption is inferred from the old repository alone.

The signed-in active manager initially had `capabilities: []`, which explains its formal SOP 403 under the explicit permission policy. Through the authorized `admin_person` workflow, only `sop_task_read` was added, using expected-version checking and request ID `b7850f3e-2de5-4943-8d2e-0ea2608e6832`. Both SOP GETs subsequently returned 200 with SOP writes off. Import/work/manage/publication capabilities and `sop_task_read_source` were not added. This proves the cause for this account; the original tester's distinct account/workspace remains unconfirmed. Other intended readers need the same explicit authorized read grant in their effective workspace.

## Evidence boundaries

Local regression coverage for the follow-ups: 37 index/operator/runtime/packaging tests; 127 progress/P2/detail tests including full-capture equivalence for manager/member accounts and a source-cache materialization budget; 254 additional source-policy/redaction/health/case tests; frontend delayed-detail/loading regression, 41 session-epoch scenarios, and production build. PR 84's broader validation and local before/after SQL counts remain in `README.md`. The final deployment does not rerun the entire 4,913-test suite; these targeted checks validate its changes.

Live SQL query/row counts were not instrumented in the running web process; do not confuse local materialization budgets with measured formal SQL counts. Formal timing headers distinguish identity, loading, whole policy/projection and encoding where instrumented. `project` is the entire projection phase. Progress has no phase timing header, so its remaining latency is not assigned to a measured internal phase. Source refresh and first cold external reads are not claimed as snapshot-backed SLA measurements.

## Final authenticated API measurements

Six sequential rounds per endpoint (first plus five warm), followed by one three-request concurrent batch; 42 sequential + 3 concurrent requests, all 200. Small-sample p95 is the maximum of five warm observations, not a population SLA. These browser times include transport; byte counts are decoded JSON. The source snapshot was retained, with live-source reads disabled. Raw evidence: `final-api-reads.json`.

| Endpoint | Warm median | Warm p95 | Decoded bytes | Status |
|---|---:|---:|---:|---|
| `/api/session` | 149 ms | 236 ms | 31,322 | 200 |
| `/api/settings/overview` | 499 ms | 919 ms | 3,523 | 200 |
| `/api/workspace?scope=shell` | 4872 ms | 6968 ms | 268,474 | 200 |
| `/api/projects/src-604c50ce7422171b35dc` | 3638 ms | 9044 ms | 86,051 | 200 |
| `/api/projects/src-604c50ce7422171b35dc/sop-tasks` | 740 ms | 1666 ms | 1,151 | 200 |
| `/api/projects/src-604c50ce7422171b35dc/sop-assignees` | 1003 ms | 1390 ms | 72 | 200 |
| `/api/projects/src-604c50ce7422171b35dc/progress` | 7124 ms | 8529 ms | 3,820 | 200 |

The first post-deployment detail sample was 2,011 ms (server total 1,918 ms); the earlier post-activation probe was 1,560 ms. Those single observations are not substituted for the repeated p95. Session and settings meet their ≤1 s sequential warm targets; **single-project p95 ≤2 s is not met**.

For the worst browser detail observation (9,044 ms), Server-Timing accounts for 2,972 ms: identity 21 ms, loading 2,236 ms, whole policy/projection 688 ms, encoding 11 ms, residual serialization/framework 16 ms. Approximately 6,072 ms lies outside that server total. Its remaining server bottleneck is loading shared policy/source inputs and projection. The slowest shell browser observation was 6,968 ms while server total was 585 ms (loading 22 ms, projection 462 ms). Transport variability is material and is not called database work.

Concurrent summary/detail/progress returned 200 in **2,074 / 3,690 / 6,564 ms**. Detail server total was 3,587 ms (load 2,691; projection 805). Read contention still increases latency; this is one batch, not a load test. Progress warm p95 was 8,529 ms, with no measured internal phase breakdown. The final code bounds this child read independently and removes its unrelated project trees and repeated source-snapshot generation loads; it does not claim that progress is fast in all conditions.

## Before/after and readiness

| Operation | Before | Final after | Comparability |
|---|---|---|---|
| Bootstrap workspace selection | Actual old full read: 18.67–20.41 s, 18,861,439 bytes; later timeouts | Shell median 4.87 s browser, 268,474 bytes; worst browser sample server total 585 ms | Same formal dataset; deliberately smaller read contract, not an optimization claim for the full endpoint |
| Settings summary | Tester reported ~41 s; old deployed summary API 404 | API median 499 ms / p95 919 ms, 3,523 bytes; no workspace dependency | Original reported navigation not independently reproduced on its exact deployment |
| Detail API | Tester reported ~8.6 s; old deployed API 404; interim disabled flag 404 | Median 3.64 s / p95 9.04 s, 86,051 bytes, all successful | No comparable successful old API baseline on this preview |
| SOP reads | Tester reported ~12 s and 403; signed-in manager's explicit-grant denial reproduced after code rollout | Tasks median 740 ms / p95 1,666 ms; assignees median 1,003 ms / p95 1,390 ms; both 200 | Positive access requires the separately recorded explicit grant |
| Database work | Local fixture SQL/decoded-row comparison in README; live counters unavailable | Single project tree; one full source-cache capture per progress read rather than three; generation checks select scalars | Materialization regressions verified locally, not live SQL counter measurements |

Settings useful readiness was previously verified in five complete formal navigations at 2,752 / 680 / 657 / 794 / 600 ms with no workspace request (`live-settings-ui.json`). Five cached in-app returns to the selected project showed useful identity in 21–23 ms (`warm-cached-project-navigation.json`); these reuse the application cache and are not fresh page-load claims.

Cold asset delivery remains a failed ≤3 s readiness case. The recorded entry JavaScript was 134,154 compressed bytes, delivered in 46.54 s in the automated browser (first byte at 5.79 s; about 40.75 s after first byte); a direct HTTP client retrieved the same compressed asset in 0.334 s. The first project navigation then showed identity at 33.23 s and full detail at 47.50 s, including a 21 s lazy-chunk transfer and a shell response with 11.77 s after first byte. Gzip is active. This evidence establishes a browser/transport contribution but does not establish its underlying network cause. **Cold useful-content ≤3 s is not achieved in that run.** No artificial network settings were changed or excluded to improve the numbers.

Formal negative checks: anonymous shell/detail/settings/SOP reads return 401; authenticated missing detail and SOP reads return 404. Ungranted-manager denial/restricted UI and no predictable SOP requests were checked before the grant and in local regressions. Hidden-project denial and response equivalence remain covered by targeted tests. No unrelated business writes, import/work/source-read grants, or automatic 403 retries were introduced. Client deadlines bound waiting; they do not establish backend cancellation.


Five subsequent **fresh document navigations** on the final deployment (warm assets, no application cache carried across reloads) showed the project name/code at **1,401 / 8,500 / 5,717 / 5,515 / 4,399 ms** (median 5,515; p95 8,500). All five showed that available identity while full detail and progress were still pending. Full detail render marks were **6,374 / 16,690 / 10,390 / 14,115 / 17,685 ms**. All completed successfully, without the old full-workspace timeout. The observer was installed at DOMContentLoaded before each identity appeared; this avoids treating a late polling observation as an exact render timestamp. Raw marks and request starts/ends are in `final-fresh-project-navigation.json`. A preceding fresh navigation was observed only after its header existed and is deliberately excluded from those five samples.

These measurements confirm the rendering separation and successful access/activation. They also confirm that **fresh useful project content ≤3 s remains unmet**. Loading shared policy/source facts, simultaneous child reads, and variable response/chunk delivery remain the measured limits. This report records those misses instead of declaring every acceptance/performance target complete. The exact network cause and live per-request SQL counters remain unavailable.
