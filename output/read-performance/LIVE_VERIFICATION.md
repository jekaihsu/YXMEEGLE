# Live deployment verification — 2026-10-21

**Historical interim result. Superseded by [FINAL_VERIFICATION.md](FINAL_VERIFICATION.md), including successful activation and an explicit SOP read grant.**

PR #84 was merged into `ava-apple/yx-company-system` as `06b85dd07df3fdb2188496aff9d6649923745756`. The running Zeabur upload is `6ad805a624d8f4b41eb8735f` on https://yongxiang-projects-20260925.zeabur.app. This is a source upload, so Zeabur's Git SHA field is empty: identity is established by the frozen inventory matching the merged tree, 196 matching runtime source/configuration hashes, and all four entry HTML assets byte-matching the local production build. The web, supervisor and durable worker run as UID 10001. PostgreSQL is 17.11; all 37 workspaces report normalized storage schema 2.

**Settings verification passed. Project rollout verification did not pass.** The site is healthy with its original environment restored. No real SOP grants, source business records, or write flags were changed by verification. Deployment startup's normal schema/normalization behavior and background synchronization continue as implemented.

## Measured live results

Authenticated as an active manager, normal admission, formal workspace `lark-1aad6a938e891946`, effective capabilities `[]`. Six sequential rounds (first plus five warm), followed by three concurrent requests. Raw results are in `live-fallback-api.json`. Small-sample p95 is the maximum of five warm observations; timings include browser/network overhead. These results use the actual deployed PostgreSQL environment, unlike the earlier synthetic SQLite measurements.

| Read | Warm median | Warm p95 | Status / decoded bytes | Result |
|---|---:|---:|---|---|
| Session | 170 ms | 403 ms | 200 / 31,284 | Pass ≤1 s |
| Settings overview | 692 ms | 719 ms | 200 / 3,507 | Pass ≤1 s |
| SOP tasks, ungranted manager | 96 ms | 117 ms | 403 / 63 | Expected explicit capability denial |
| SOP assignees, ungranted manager | 81 ms | 127 ms | 403 / 63 | Expected explicit capability denial |
| Single-project detail | 94 ms | 121 ms | 404 / 43 | Not activated: workspace shell flag off; not a successful detail latency |

The concurrent batch returned session 200 in 372 ms, summary 200 in 513 ms, and the intentionally disabled detail API 404 in 240 ms. It does not establish concurrent successful project-detail performance. Node assignments and start-SOP return 404 because their deployment feature remains disabled. Source/network refresh latency is not included as a successful warm feature measurement.

Five complete settings navigations rendered the useful summary at **2,752 / 680 / 657 / 794 / 600 ms** from navigation start (median 680 ms, p95 2,752 ms). None requested `/api/workspace`; the initial entry assets and subsequent cached navigations are distinguishable in `live-settings-ui.json`. The original documented preview's old session measurements were 4.34–9.73 s; its settings API returned 404, so there is no comparable old successful summary API measurement. The tester's reported 41 s settings value remains a reported figure, not a reproduced same-version comparison.

Project navigation still used the full `/api/workspace` fallback and reached its **30,002 ms client deadline** before any project title appeared. The UI displayed its retry state. A client timeout does not prove the server stopped its work. `live-project-fallback-ui.json` records this failed acceptance check. The previous deployment's workspace successes took 18.67–20.41 s and returned 18,861,439 bytes, with later 45 s timeouts. We did not claim a successful after-detail or after-project-page speedup.

## Configuration and rollout findings

The original service had no `WORKSPACE_SHELL_ENABLED`, `INDEX_TABLES_ENABLED`, `NODE_ASSIGNMENT_ENABLED` or `SOP_TASK_WRITES_ENABLED` overrides (all resolve false). The optimized single-project API is gated by workspace shell, and a shell workspace response also requires current derived indexes. All **420 project index entries need repair**; a direct read found **zero indexed projects** and stale counter version 35382 versus workspace version 35389. An authenticated index-health check took **47.22 s**, returned 200 and reported `healthy=false`, `enabled=true`, 420 dirty projects. This is a one-off index diagnostic, not an endpoint performance success.

We temporarily enabled only the two read flags while preserving and reading back the entire existing environment map. SOP/local/source write settings, credentials, tenant admission and roles were preserved. The restart/replacement sequence produced extended 502 responses and CRASHED pod statuses. Both initial and replacement uploads had identical deployment plans; the first upload had already passed source/health checks. Zeabur returned missing runtime-log storage / container-not-found during the failed period, so the exact crash cause is **not established**. The flag correlation is not proof of an application bug or platform-only fault.

The original complete environment was restored and the service recovered. The recovery upload was canceled before activation once the existing replacement became RUNNING. Final runtime checks confirm the merged source, web and worker, and all read/write flags at their original false values. A paid-only rollback request was rejected with `REQUIRE_PAID_PLAN`; no subscription or billing change was made. No additional restart or automatic deployment is pending.

Because activation was unstable, no index-repair POST reached execution (its health precheck returned 502). We did not bypass the repair endpoint's flag/administrator policy or write indexes directly through SQL. Full workspace bootstrap remains the measured project bottleneck; successful shell/detail latency and project rendering remain unverified. The current code provides the intended optimized paths, but those paths are not active in this environment.

## Permission result

The active, normally admitted manager consistently receives **403 `sop_import_forbidden`** from both SOP GETs, with an identity phase and no case-load phase. Its effective capability list is empty. This reproduces the missing-explicit-SOP-grant cause for the current account and workspace. It does not prove the original tester was the same account/environment. The UI avoids automatic SOP reads for this account and explains the restriction when its section is available.

An authorized administrator must explicitly provision `sop_task_read` for intended readers through the versioned personnel workflow; original source procedures separately require `sop_task_read_source`. No grant was inferred from manager status. Authorized-read success with SOP writes disabled was covered locally, **not verified on live**, because this signed-in user has no SOP grant and verification did not change permissions.

## Remaining acceptance work

1. Diagnose the read-flag rollout instability in the existing staging environment with usable container events/logs and the same representative dataset; do not repeat unbounded production restarts.
2. Use the authorized administrator index-repair workflow after controlled activation, verify current project/task/counter indexes, then verify writes/background synchronization keep their versions current.
3. Enable the shell and index read flags only once that path is healthy. Repeat successful single-project API and page-readiness measurements, denied/slow child isolation and the three-request concurrency check.
4. Provision explicit read access for intended SOP readers and test both permitted and ungranted accounts with SOP writes still off. Confirm unavailable/hidden projects remain protected.

The merge and code deployment are complete. Settings and negative permission checks passed live; **project activation/performance and positive SOP-reader acceptance remain incomplete**.
