# Reports backend fix round, 2026-10-15

Full dump run through FastAPI TestClient. Cold build includes file read, projection, fingerprint, normalization and indexes, but excludes network. Sequential local requests. Five rounds of 300 identical requests measure result-cache hits. A further 300 varied requests per endpoint clear the result cache before every timed request, ensuring misses. Weeks, departments, sorts, offsets, limits and asset ranges vary. No errors. Response snapshot and pagination are asserted. No claim of speedup from the earlier cache-hit benchmark.

Machine had 10 logical CPUs and load averages 4.60, 3.45, 2.72. These are local acceptance measurements, not concurrent production capacity measurements.

Cold full dump build 136.22 ms. Source counts `{"field": 813, "field_cost": 774, "office": 1233, "office_cost": 684, "case": 735, "contract": 0, "plan": 1354, "vehicle": 21, "instrument": 148, "people": 81, "monthly": 18, "issue": 10}`.

| Endpoint | Hit p50/p95/max ms | Miss p50/p95/max ms |
|---|---|---|
| review | 0.317/0.376/0.468 | 0.304/0.532/0.612 |
| review/rows | 0.404/0.467/0.679 | 0.263/0.445/0.661 |
| sales | 0.448/0.468/13.451 | 2.215/2.596/2.712 |
| assets | 0.326/0.351/0.453 | 0.868/1.232/1.339 |
| progress | 0.324/0.348/0.402 | 0.368/0.519/0.578 |

Cross-check independently parsed original field statuses and Taipei dates against all weekly endpoints. {"independent": {"pending": 405, "returned": 47, "passed": 361}, "endpoint": {"passed": 361, "returned": 47, "pending": 401, "unset": 0}, "weeks": 16, "undated": 4, "undated_statuses": {"pending": 4}}

The dump does not include contract details. Live verification follows below. Raw dumps and live records remain in /tmp only.

## Final complete live snapshot benchmark

The final run includes all 1997 contract rows. Miss requests use observed field weeks rather than mostly empty historical weeks. Departments, groups, status filters, sort keys, orders, offsets, limits and asset date ranges vary. Each miss clears only the result cache before timing, leaving the normalized snapshot warm. Five hit rounds of 300 requests and 300 misses per endpoint. All HTTP responses succeeded.

Cold complete live-data file build 70.38 ms. Live CLI acquisition 79.32 seconds. These are separate measurements; CLI startup and serialized network reads dominate the latter.

| Endpoint | Hit p50/p95/max ms | Miss p50/p95/max ms |
|---|---|---|
| review | 0.316/0.406/6.092 | 0.483/1.149/2.153 |
| review/rows | 0.398/0.490/3.563 | 0.274/0.477/12.526 |
| sales | 0.439/0.462/0.540 | 2.069/2.491/2.668 |
| assets | 0.319/0.334/0.399 | 0.883/1.224/2.991 |
| progress | 0.315/0.333/0.463 | 0.354/0.415/0.485 |

All miss p95 values pass aggregate <100 ms and rows <80 ms. Profiling 100 sales plus progress computations separately showed sales cell/number parsing dominates CPU (0.874 of 0.917 profiled seconds). No speedup is claimed. Review uses a department/week index; progress plans use a department/week index and snapshot-level basis detection, avoiding full 1233 work-row or 1354 plan-row scans per request. Small sales and asset tables are still evaluated on misses. Varied filtered pages can be cheaper than the fixed hit response because serialization and deepcopy scale with returned data.

## Live source verification

LarkReader used the dev-only CLI transport with bot identity, page_size=500 and field_names. All tables completed successfully. CLI wrapper timing includes waiting for its serialized transport lock. Raw data stays outside the repository.

| Table | Live rows | Dump rows | Schema total |
|---|---|---|---|
| 外業工作單 | 813 | 813 | 813 |
| 外業成本單 | 774 | 774 | 774 |
| 內業工作單 | 1233 | 1233 | 1233 |
| 內業成本單 | 684 | 684 | 684 |
| 案件 | 735 | 735 | ? |
| 合約明細 | 1997 | absent | 1997 |
| 工作預排 | 1354 | 1354 | 1354 |
| 車輛 | 21 | 21 | 21 |
| 儀器費率 | 148 | 148 | 148 |
| 人員名單 | 81 | 81 | ? |
| 外業組別營業額統計 | 18 | 18 | 18 |
| 回報問題 | 10 | 10 | 10 |

Live and dump status counts exactly match, with no observed drift. Passed 361, returned 47, pending 405. Weekly HTTP totals exclude four undated pending rows and reconcile to the complete source. Trimmed returned statuses are counted correctly. Gaps retain field-date 4/813 and field-group 9/813. Office coverage remains 31/1233.

The same first 100 office records returned 278605 bytes without field_names and 108280 bytes with the registry whitelist, a 61.13% reduction in serialized CLI JSON. This compares equal row counts and includes CLI envelope overhead.

## Real-data behavior

For 2026-01-01 through 2026-10-15, vehicles have 16 in use, 5 idle, and 140638 valid km; instruments have 55 in use, 93 idle and 7 repair/insurance entries. Invalid or missing mileage is ignored. Never-used assets retain null last_used and idle_days. Blank instrument category/status remains 未填 with computed gaps. Owner classification preserves the raw note.

Sales contains 735 cases. Billed, received, unbilled billable and receivable totals are null because source formulas are empty. Contract uses actual amount with expected fallback; progress text arrays parse numerically. The contract total is 162559588081.3751 in the source units; unusually large source values are preserved, not silently adjusted.

Field progress for 2026-10-05 uses days, with 8 planned case-days and 30 distinct actual case-dates, achievement 3.75, actual points 40.4. Multiple plans mentioning a case count separately; duplicate work orders on a date count once per case. Remaining uses case expected minus department cumulative. Default scope only includes weekly activity; scope=open adds in-progress cases.

## Validation and remaining gaps

`python -m pytest backend/test_reports_compute.py backend/test_reports_routes.py -q` passed 23 tests. Tests cover Taipei UTC-to-Monday boundary, trimmed status, all vehicle slots, negative mileage, null financial totals, days basis, linked multiple cases, placeholder exclusion, distinct dates, open scope, CLI retry and 422 responses for malformed/non-Monday week, limits 0/999, unknown sort/dept/scope. Sanitized fixtures occupy 48 KB on disk.

Optional planned asset use counts were not added because the contract has no response field; the existing computed coverage gap remains. No contract deviation for required fields. The additive scope parameter follows the fix brief although the copied contract query list does not yet mention it. TAF, calibration and monthly inspection sources remain absent. Empty financial formulas remain a source data gap. No commit or push.

## Independent review fix acceptance, 2026-10-15

This section supersedes the earlier progress semantics and totals. No speedup is claimed. The acceptance claim is that all result-cache miss p95 values remain below 100 ms for aggregates and 80 ms for rows on the existing local dump.

Five complete runs of `backend.benchmark_reports.run('/tmp/lark-docs/data', 300, 5)` produced 45,000 timed HTTP requests. Each run includes five rounds of 300 hits and 300 varied forced misses per endpoint. Every response status, snapshot and page size was asserted. Errors were zero. The independent field-status reconciliation still matches 361 passed, 47 returned and 405 pending, including four undated pending records outside weekly reports. The dump contains no contract-detail file, so those rows are zero here. This run does not repeat live network acquisition.

The benchmark sends `week` to sales and assets, which the new per-endpoint allowlist correctly rejects. That file is outside the permitted edit paths. The run used this temporary in-memory adapter, leaving the benchmark file unchanged. All benchmark requests otherwise use the original implementation.

```python
from fastapi.testclient import TestClient
from backend.benchmark_reports import run
original = TestClient.get

def get(self, url, **kwargs):
    if url.endswith(('/sales', '/assets')) and 'params' in kwargs:
        kwargs['params'] = {k: v for k, v in kwargs['params'].items() if k != 'week'}
    return original(self, url, **kwargs)

TestClient.get = get
for _ in range(5):
    result = run('/tmp/lark-docs/data', 300, 5)
    print({k: v['miss'] for k, v in result['endpoints'].items()})
```

The table gives the median and range across five per-run miss p95 values, in milliseconds.

| Endpoint | Median miss p95 ms | Minimum p95 ms | Maximum p95 ms |
|---|---:|---:|---:|
| review | 0.733 | 0.725 | 0.749 |
| review/rows | 0.511 | 0.499 | 0.532 |
| sales | 2.867 | 2.826 | 2.954 |
| assets | 2.079 | 2.073 | 2.088 |
| progress | 0.490 | 0.484 | 0.556 |

All five runs pass both limits. Raw benchmark JSON remains local at `/tmp/reports-fix-benchmark-runs.json`. The first cold file snapshot took 135.65 ms, including file reads, fingerprints, date expansion, normalization and static gap precomputation. Warm misses include endpoint computation, deepcopy, JSON serialization and TestClient transport. Cache clearing is outside the timed region. The host has 10 logical CPUs; load averages before measurement were 2.24, 2.81 and 3.45. These are sequential local acceptance numbers, not production concurrency capacity. One separate profile overlapped the start of a repeat run; no before/after speed comparison is inferred.

A separate untimed cProfile run executed 100 sales, vehicle and progress calculations. Sales consumed 1.142 cumulative seconds of 1.566 profiled seconds. Cell and numeric decoding dominate sales; date parsing contributes 0.257 cumulative seconds across the run. Profiling time is excluded from the latency table. Work is CPU-bound over these small source tables. Static source gaps now come from the snapshot cache. Date-window asset coverage and selected negative-remaining counts are computed from each request's relevant data.

Real-data corrected KPIs, group names, query rejection and per-finding test evidence are in `REPORTS_FIX_REVIEW_20261015.md`.
