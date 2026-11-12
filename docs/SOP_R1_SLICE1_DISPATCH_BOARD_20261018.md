# SOP R1 slice 1: dispatch board (C07 read) on the real V4 schedule

Source: `YX_SOP_R1_Implementation_Handoff_v1.0.md` (30 tickets F01-F08, W01-W10, C01-C08, R01-R04), PRD v1.0, `PM-Solution-playbook-v0.1.xlsx`.
Scope of this document: the first slice only. Nothing else in the handoff is started.

## Why this slice

The handoff's demo flow needs A (employee tasks), B (PM blockers) and C (dispatch). Auditing the V4 Base `H7W6b0PFWaVF1BsgqXJj3pQ9pXb` on 2026-10-18 shows only C has real data to read:

| Handoff need | V4 table | Rows | Verdict |
| --- | --- | --- | --- |
| Schedule slots (C07, F04) | 工作預排 `tblZz6Mkhv9gHrB2` | 312 | Real. 2026-07-24 to 2026-08-19, nothing after. Date-only. |
| People (C01/C02) | 人員名單 `tblfaCO2xPUNptQH` | 67 (61 在職) | Real. No skill/qualification fields. |
| Instruments (C03) | 儀器費率 `tblg3Fo23T6Gos6S` | 144 | Real. 啟用 + 狀態 (正常/送修-損壞/出險). No custody or expiry. |
| Vehicles (C03) | 車輛 `tblTQv8l5ntnbwyp` | 20 | Real. 啟用 only. |
| Task execution (W03, W07) | 任務 `tblsoyGcC6K5AipF` | 4 | 9 fields. None of the 21 proposed T extensions (planned start/end, crew, scope, version) exist. |
| Node summary (W08) | 節點指派 `tblcPZPmezkyeVb7` | 9 | Exists, nodes only. |
| Packages, submissions, approvals, blockers (W02, W04-W06) | none | n/a | No table. Needs Ledger (F03) first. |

Consequences:

- Publishing (C06) and confirmation read-back cannot run: the T extensions are unverified and null in the manifest.
- Capability (C01/C02) has no source. Every "required skill" check is `unknown` by rule, never passing.
- A and B have no new source data. They stay on the existing My Work and Project Progress pages.

So slice 1 is read-only and covers F01 (source manifest and schema drift check), a slice of F04 (the shared read envelope) and C07 (dispatch board). It gives the dispatcher the first honest view of who and what is booked, and it exposes the data gaps.

## Real-data findings that shape the rules (measured 2026-10-18)

- 312 rows, 307 `出工`, 3 `休假`, 2 with no type. 296 have a start date. 15 have a time of day. 59 span several days.
- 出工 rows with no 人員: 26. With no 案件: 40. 外業 rows with no 儀器: 14.
- 80 of 509 person-days are booked on more than one row, but only 15 rows carry a time. Same-day overlap on a date-only row is therefore **unknown**, not conflict. Only two rows with overlapping timed intervals can be a `conflict`.
- Instruments: 2 of 94 resource-days shared. Vehicles: 6 of 100.
- 父記錄 5 is empty on every row, so the parent/execution-child split in the handoff has no data yet.
- Latest booking is 2026-08-19. Today is 2026-10-18, so the default board window shows an empty future. The board must say "no bookings after 2026-08-19" and show the last-source-date, not a healthy zero.

## Contract: `GET /api/v2/dispatch/board?from=&to=&group=`

Flag `DISPATCH_BOARD_ENABLED` (default off). Read-only. Follows `backend/data_state.py` for states.

```jsonc
{
  "schema_version": 1,
  "window": {"from": "2026-07-20", "to": "2026-07-26", "tz": "Asia/Taipei"},
  "source": {
    "dataset_key": "operational_schedule",
    "registry_key": "v4", "table_id": "tblZz6Mkhv9gHrB2",
    "fetched_at": "ISO8601", "latest_booking_date": "2026-08-19",
    "quality": {"states": ["complete"|"partial"|"stale"|"read_failed"|"forbidden"|"unknown"], "reason": "string|null"},
    "joins": {"people": "ok|partial|unavailable", "instruments": "...", "vehicles": "...", "cases": "..."}
  },
  "kpi": {"slots": 0, "unassigned": 0, "unknown_overlap": 0, "conflict": 0},   // every number is a count over `slots` below
  "unassigned_queue": ["slot_id"],                                                // same ids as slots with planning_status=unassigned
  "slots": [{
    "slot_id": "v4:<table_id>:<record_id>",
    "record_id": "rec...",
    "kind": "work|leave|standby|support|unknown",
    "planning_status": "unassigned|confirmed",          // confirmed = row exists in V4, not read back by this workbench
    "provenance": "v4_row",
    "interval": {"start": "2026-07-27", "end": "2026-07-27", "precision": "date|datetime"},
    "group": "水深A組|null", "discipline": "外業|null",
    "case": {"ref": "rec...", "code": "string|null", "name": "string|null"} ,
    "work_content": "string|null",
    "crew": [{"person_ref": "rec...", "name": "string|null", "active": true, "feasibility": "feasible|conflict|unavailable|unknown", "reasons": ["inactive","timed_overlap","same_day_other_slot","no_leave_source"]}],
    "resources": [{"kind": "instrument|vehicle", "ref": "rec...", "label": "string|null", "feasibility": "...", "reasons": ["repair","inactive","same_day_other_slot"]}],
    "gaps": ["no_crew","no_case","no_instrument_for_field_work"],
    "issues": ["slot_id"]                                // other slots sharing a person/resource in the window
  }],
  "capacity": {"people": [{"person_ref": "rec...", "name": "...", "days": {"2026-07-27": {"booked_slots": 2, "state": "free|booked|overbooked_unknown|unknown"}}}]},
  "gaps": [{"code": "string", "message": "string", "count": 0}]   // source gaps, e.g. "no_bookings_after_2026-08-19", "no_capability_source"
}
```

Rules:

- Unknown stays unknown. No leave source and no qualification source means those checks return `unknown` with a reason, never `feasible`.
- A date-only overlap is `unknown` (`same_day_other_slot`). `conflict` needs two `datetime` intervals that overlap.
- Inactive person (`在職` false), 儀器 with 狀態 other than 正常 or 啟用 false, and 車輛 with 啟用 false are `unavailable`.
- `unassigned` means a work slot with no crew. A missing case applies only to 外業/內業 work (admin, sales and PM work carries no case, per PKG-04). A missing instrument on field work is a slot gap, not unassigned.
- A case link whose target table is missing counts under gap `unresolved_case_links`. On 2026-10-18 the schedule's 案件 link points to table `tbljGNdDxLs8ihuE`, which no longer exists in the V4 Base, so case codes cannot be shown yet.
- KPI numbers are computed from the same list the queue is built from.
- Salary and leave-reason fields are never read.
- A failed join degrades that field (`name: null`, `joins.people: partial`), not the board.
- Cache: reuse the existing read-layer coalescing. A stale last-good response is served with `stale` plus its age while a refresh runs.

## Loading experience

- The page renders its frame (week header, KPI strip, empty queue and grid skeletons with the final geometry) before data arrives, so nothing shifts.
- First paint from the schedule rows. People, instrument and vehicle names fill in as joins land. Unresolved names show a neutral placeholder, not a record id.
- `stale` shows the age and a refresh button. `read_failed` keeps the last good board and shows the failure inline with a retry. `forbidden` shows no counts.
- 390px: queue first, then a per-day list. Keyboard: arrow keys move across days, Enter opens the slot detail.

## Out of scope for slice 1

Preview/commit/publish (C04-C06), capability and resource verification records (C01-C03), the Ledger (F03), writes of any kind, calendar/Lark notifications. Reason: each needs a decision or table that does not exist yet (T field migration, a capability source, approval seat owners).

## Open decisions for the owner

1. Create the 21 T extension fields in V4 (needed before any publish work). Names and types are in handoff section 3.3.
2. Choose a capability source (a new 能力 table or manual verification records). Without one, every dispatch confirmation stays blocked, by design.
3. Whether date-only 工作預排 rows are the permanent schedule grain or are replaced by timed T rows.
