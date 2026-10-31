# Attendance semantics and weekly queries

The attendance tool keeps its public name `attendance_today`. Both arguments are required. `range` is `today` for a single day or `week` for its containing Monday through Sunday. `date` is a strict `YYYY-MM-DD` string or null for the current Taipei date. Last week uses an explicit date in that week. Queries outside the route's current week plus or minus 26 weeks return an explanatory error. Existing 1 to 240 character validation remains in force.

The old handler always requested today's week, and its projector discarded six columns. A real-route reproduction before the fix returned the following counts.

```text
OLD {"missing_punch": 0, "no_record": 54, "leave": 2, "exempt": 4}
```

The fixture has 58 employed people. Two leave approvals overlap null attendance labels. Four exemption labels are non-null. The old projector includes both people on leave in `no_record`. It supplies no category for the question "who has not punched in". Its empty `missing_punch` list therefore cannot answer that question.

The requested literal old shape of 58 null records including four exempt people cannot be produced by `weekly_attendance.fetch_week`. `NoNeedCheck` produces `免打卡`, so those four labels cannot also be null. The fixture preserves the real producer behavior rather than inventing incompatible evidence. Its corrected result is 52 unaccounted people, two on leave, and four exempt.

The screenshot's 59 to 58 change is not explained by including both leave approvals, which changes a count by two. Repeating the same snapshot is deterministic. A changed record or roster could change the count by one after refresh, and model arithmetic could also do so. Distinguishing these requires both staging tool payloads and their `as_of` values. No live staging data or Claude replay was available in this worktree.

Each day now has complete `counts`, plus semantic lists `unaccounted`, `late`, `early_leave`, `missing_punch`, `on_leave`, `trip`, `out`, `exempt`, and `supplemented`. `arrived` is a labelled count only. Each evidence group is independent. A person can appear in multiple explanation and punch groups, including late and on leave on the same day. `unaccounted` requires no record and no explanation and is disjoint from every other group. Counts equal full list lengths before documented truncation. Weekly person-days and displays preserve these overlaps. Displays merge their labels into one row.

```json
{"range":"today","date":"2026-10-12","counts":{"arrived":0,"unaccounted":52,"on_leave":2,"exempt":4,"missing_punch":0},"unaccounted":[{"id":"ou_10","name":"同事10"}],"incomplete":true,"truncated":false}
```

This sample omits other zero counts and all remaining names. Today means no record yet at `as_of`, never a finding of absence. Past dates mean no record. Future dates and weekends do not create unaccounted people. The `basis` field says `no punch obligation or holiday calendar in the source; weekends excluded, public holidays not excluded`.

Weekly results retain seven daily count objects, distinct people and person-day summaries, the top ten people ranked by unaccounted days, and up to 50 per-person category-to-date lists. `labelled_arrival_count` sums daily arrival labels rather than claiming unique attendance. Details are trimmed before rankings. Complete counts remain unchanged under structural trimming to 6,000 characters. The result exposes `incomplete` and `truncated` separately.

The mixed Monday through Friday fixture has eight people. Two take leave on Monday, four are exempt on Monday, one is late each weekday, and one has a missing punch each weekday.

```json
{"range":"week","week_start":"2026-10-12","week_end":"2026-10-18","summary":{"unaccounted":{"people":6,"person_days":24},"late":{"people":1,"person_days":5},"missing_punch":{"people":1,"person_days":5},"on_leave":{"people":2,"person_days":2}},"people":[{"id":"ou_6","name":"同事6","days":{"late":["2026-10-12","2026-10-13","2026-10-14","2026-10-15","2026-10-16"]}}]}
```

This sample omits other groups, rankings, and names. The day display has a count bar chart and a deduplicated people table. The week display has name plus seven dates, short state codes, and daily unaccounted bars. Both tables cap at 50 rows, use scalar cells, and honor truncation. The week caption gives the date range and source time.

Tests seed only a production Lark workspace through `reader.refreshers['attendance']`. The refresher calls the real weekly producer with synthetic task and approval responses. Tool calls traverse the real HTTP route and authorization. No demo attendance source is fabricated.

Verification uses `/tmp/ai-backend-venv/bin/python`. The final focused run of `backend/test_ai_attendance.py`, `backend/test_ai_tools.py`, `backend/test_ai_api.py`, `backend/test_ai_displays.py`, and `backend/test_ai_providers.py` passes 68 tests. Attendance coverage includes date validation before HTTP, a changed count after refresh, leave and travel approvals, weekday label lists, weekend and future-day exclusion, truncation, scalar displays, and prompt text. These tests assert tool behavior and prompt rules, not generated model behavior.

`backend/test_ai_api.py::test_real_socket_stream_is_not_buffered` passes through an actual socket. Its observed text deltas arrive at 0.012 seconds and 0.813 seconds with the delayed synthetic provider, demonstrating incremental delivery rather than response buffering. `git diff --check` passes.

The whole backend command `python -m pytest backend -q` completes with `5686 passed, 39 skipped, 1 xfailed, 4 warnings in 581.12s`. The suite started before the final additive arrival-count field, prompt truncation clarification, and additional fixture cases were finished. The fresh 68-test focused run verifies those final changes.
