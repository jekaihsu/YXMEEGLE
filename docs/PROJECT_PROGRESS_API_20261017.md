# `GET /api/projects/{project_id}/progress` (2026-10-17)

One case's engineering progress, joined server-side from the workspace the app already holds plus the reports snapshot, so the project page needs no trip back to Lark. Typed models: `backend/project_progress.py` (`ProjectProgress`). Schema version: `schema_version: 1`. Additive keys may appear; existing keys keep their meaning.

Read-only. No Lark write, no workspace mutation, `Cache-Control: no-store`.

## Authorization and visibility

Identical to `GET /api/case-detail/{id}` (shared helper `p2_visible_case_state` in `backend/app.py`):

- `identity()` session, then `p2_read` (one fenced capture) narrowed by `filter_visible_cases`, `filter_private_workspace`, `restrict_hr` and, outside test/demo, `case_redaction`.
- A case that is absent or not visible is the same 404 `找不到這個項目`, byte-identical to case-detail. Unknown query parameters are 422. `project_id` over 200 characters is 422. No session is 401.
- Tenant-read viewers may call it (pattern added to `TENANT_READ_PATTERNS` next to case-detail). They get no amounts and no v3 data.
- Contract line planning fields (`工編號碼`, `<類別>數量`, `<類別>工項`) are re-attached after the payload strip and before `case_redaction`, so redaction still sweeps them. Nothing else of `fields`/`source_fields` is kept, and none is returned.
- Amounts and reports data are for `pm`/`manager`/`manage_sources` in normal access mode in a real company workspace only (the reports gate). Everyone else gets `finance.restricted: true` with the amount keys `null`, `sources.reports_status: "restricted"`, and gaps `finance_restricted`/`reports_restricted`.

## Reports snapshot

Non-blocking by design (`ReportsView`):

- A cached snapshot, even a stale one, is used as is. Per-week progress rows go through the store's own result cache (`SnapshotStore.result('progress', …)`), so repeated reads cost a dictionary lookup.
- A cold store is never waited on. It is warmed in the background (single-flight, read-only, same `start()` the reports lifespan uses) and the response says `reports_status: "cold"` with gap `reports_cold`. The rest of the response is complete.
- `unavailable` means no snapshot and the last refresh failed. `disabled` means `REPORTS_ENABLED=false`.

## Response

```
schema_version  int
project_id      string
as_of           string|null     source snapshot time of the capture (same as case-detail)
sources         { source_synced_at, source_status, reports_status: ok|cold|unavailable|restricted|disabled,
                  reports_fetched_at: string|null, reports_stale: bool|null }
identity        { code, is_c_prefix,
                  confirmation: { present, line_count, fill_item_count: int|null, source_status: string|null },
                  quotes: [ { number, engineering_code, status } ],            // attached to this project only
                  v3_cases: [ { case_key, case_code, status, match: code|quote_number } ],
                  v3_ambiguous }                                               // >1 distinct v3 case; all listed, never merged
stages          [ { key, label, state: done|active|waiting|unknown, basis: rule|source|none,
                    evidence: [ { label, value, tone: ok|warn|muted } ] } ]    // 9, in order:
                                                                               // sales pm confirmation field control mapping report billing settlement
production      { field|control|mapping|report: { planned: {lines, items, qty: string, basis: {native, derived, ambiguous, unlinked}, needs_review}|null,
                                                  items: [ { item_id, code, name, planned_qty: string|null, link_basis } ],   // max 50
                                                  items_total, items_truncated,
                                                  actual: { known, value: string|null, unit_note, reason, source: v4_daily|v3_reports|null },
                                                  work_orders: { count: int|null, latest_date: string|null } },
                  report_rows: [ { case_key, case_code, dept: field|office, week, basis: points|days, planned, actual,
                                   planned_days, actual_days, matched_days, achievement, expected_total, done_total, remaining, status } ],
                  report_rows_truncated }
finance         { restricted, quotes: [ { number, invoiced_total, billable_unrequested, billable_total, received_total, received_date, case_received } ],
                  case_received: true|null, received_date }
gaps            [ { id, severity: info|warn, message_zh } ]
```

Conventions:

- Quantities and money are decimal strings (never floats). Reports points (`planned`, `actual`, `done_total`) are floats as in `/api/reports/progress`.
- `null`/`unknown` means no data, never 0. `work_orders.count: null` means no mapped row (not a verified zero). `case_received` is `true` or `null`: an unchecked box cannot be told from an unset one.
- The SOP-node status is not here. The frontend joins it beside `stages`.
- `report_rows` carry `case_key`, which opens the existing drawer (`GET /api/reports/progress/case?key=…&dept=…&week=…`).

## Stage rules (top of the module)

| stage | state / basis | when |
| --- | --- | --- |
| sales | done / rule | code starts with `C` + digit, or a confirmation with ≥1 contract line exists; otherwise unknown / none |
| pm, confirmation | done / rule | confirmation with ≥1 line. Confirmation without lines: active / rule. No confirmation: waiting / rule |
| field, control, mapping, report | active / source | only when a mapped daily row (or, for field with exactly one v3 match, a positive v3 `累計外業營業額點數`) gives an actual. Never `done`. No confirmation: waiting / rule. Otherwise unknown / none |
| billing | active / source: source 累計已請款 > 0. done / source: 案件已入帳. Otherwise unknown / none. Without amount access (`finance.restricted`) billing and settlement are always unknown / none with no finance evidence |
| settlement | done / source: 案件已入帳. Otherwise unknown / none |

## Production actual

- `v4_daily`: sum of `points` (營業額點數) of `p.daily_reports` whose `department` is the stage's group (外業組/控制組/圖資組/報告組). It is reported work, not accepted delivery and not contract quantity (`unit_note` says so).
- Rows mapped but none has points: `known: false`, reason `已有日報連結，但完成數量尚未投影`.
- No row mapped to the case: `known: false`, reason `尚無日報連結到此案件`. Rows exist for other groups only: `此案件的日報沒有歸屬到<類別>`.
- `v3_reports` (field only, exactly one v3 case, positive cumulative): `known: true`, whether or not the case has weekly rows. Ambiguous v3 never lends an actual.

## Gap ids

`no_confirmation`, `confirmation_status_conflict`, `fill_items_unknown`, `plan_unavailable`, `plan_truncated`, `items_unlinked`, `items_ambiguous`, `quotes_duplicated`, `no_daily_linked`, `v3_ambiguous`, `v3_none`, `v3_no_activity`, `reports_cold|unavailable|restricted|disabled|stale`, `finance_restricted`, `finance_empty`.

## Known limits

- Item `code`/`name`/`planned_qty` come from the item's linked contract line. An ambiguous or unlinked item has `null` for all three.
- `PM告知可請款日期` and `計價進度` are not in `sources.FIELDS`, so they are not returned. Adding them needs a projection change, not a change here.
- `report_rows` cover the newest 6 weeks with activity per department (`report_rows_truncated`). Office rows are not split into control/mapping/report.
- The derived plan exists only when the plan tables were read completely and the viewer may see every source id behind it.

## Example (synthetic fixture of the real C115264 chain, abbreviated)

```json
{"schema_version": 1, "project_id": "<project-id>", "as_of": "2026-09-25",
 "sources": {"source_synced_at": null, "source_status": "fresh", "reports_status": "ok",
             "reports_fetched_at": "2026-10-17T11:42:26+00:00", "reports_stale": false},
 "identity": {"code": "C115264", "is_c_prefix": true,
   "confirmation": {"present": true, "line_count": 4, "fill_item_count": 12, "source_status": "執行中"},
   "quotes": [{"number": "115588", "engineering_code": "C115264", "status": "報價中"}],
   "v3_cases": [{"case_key": "recvsaz8kBOaj0", "case_code": "115588", "status": "報價中", "match": "quote_number"}],
   "v3_ambiguous": false},
 "stages": [{"key": "sales", "label": "業務", "state": "done", "basis": "rule",
             "evidence": [{"label": "判斷", "value": "工編以 C 開頭", "tone": "ok"}, {"label": "工編", "value": "C115264", "tone": "muted"}]},
            {"key": "field", "label": "外業", "state": "unknown", "basis": "none",
             "evidence": [{"label": "合約規劃", "value": "3 筆明細 / 65", "tone": "muted"}, {"label": "完成量", "value": "尚無日報連結到此案件", "tone": "warn"}]},
            "…7 more…"],
 "production": {"field": {"planned": {"lines": 3, "items": 3, "qty": "65", "needs_review": 0,
                                       "basis": {"native": 0, "derived": 3, "ambiguous": 0, "unlinked": 0}},
                          "items": [{"item_id": "…/recW0", "code": "C115264-1", "name": "直接水準測量坡度14~19%", "planned_qty": "10", "link_basis": "derived"}],
                          "items_total": 3, "items_truncated": false,
                          "actual": {"known": false, "value": null, "unit_note": null, "source": null, "reason": "尚無日報連結到此案件"},
                          "work_orders": {"count": null, "latest_date": null}},
                "control": "…", "mapping": "…", "report": "…", "report_rows": [], "report_rows_truncated": false},
 "finance": {"restricted": false, "quotes": [{"number": "115588", "invoiced_total": null, "billable_unrequested": null,
             "billable_total": null, "received_total": null, "received_date": null, "case_received": null}],
             "case_received": null, "received_date": null},
 "gaps": [{"id": "no_daily_linked", "severity": "warn", "message_zh": "尚無日報連結到此案件，實際完成量未知（不代表尚未施工）"},
          {"id": "v3_no_activity", "severity": "info", "message_zh": "對應的 v3 案件尚無外業／內業預排或工作單"},
          {"id": "finance_empty", "severity": "info", "message_zh": "來源尚無請款資料（空白不等於 0）"}]}
```
