# Dispatch board read API

`DISPATCH_BOARD_ENABLED=true` registers `GET /api/v2/dispatch/board`. The default is off and the route is absent.
The route uses the PM reports gate. The session must belong to a formal Lark workspace, and the viewer must be a PM, manager, or hold `manage_sources`.

`from` and `to` use `YYYY-MM-DD` in Asia/Taipei. Both bounds are inclusive, with at most 62 calendar days. The default is today through six days later. `group` matches the source group exactly.

The first response waits for schedule rows only. Joins run in a bounded background pool. Repeat the same GET to fill names and availability attributes. Until then, names and unknown active flags are null, and `source.joins` reports unavailable. KPIs and overlap checks use the schedule links, so their counts do not depend on name joins. No unbooked person is declared free without a complete availability source.

A work slot is unassigned when it has no crew. Missing cases and field-work instruments are gaps only. Other source kinds remain confirmed. Confirmed means that a V4 row exists. It does not assert approval or feasibility. Missing optional joins never change the assignment status.

The builder compares all slots in the requested window before filtering returned slots by group. Capacity includes bookings across groups. Date intervals include their end day. Timed intervals use an exclusive end. Either midnight bound carries date precision. A timed start ending at midnight excludes the end day. A start with a time but no duration stays visible and cannot prove a timed conflict. Malformed or reversed intervals are excluded with an `invalid_schedule_interval` source gap. `active: null` means the person join or active flag is unknown.

Cases use only the V4 confirmation table's code and name. Missing, ambiguous, or explicitly foreign-table links retain their reference but have null code and name. The source manifest lists expected field names and numeric Lark types. These dependencies still need live verification before rollout. No capability or complete leave availability source is registered.

Per-table reads reuse `node_assignment.cache.StaleCache` and `live_read.client.LiveLarkClient`, including their coalescing, tenant token cache, rate limits, pagination budget, and permission handling. Cache scope includes workspace, tenant, application, identity, authorization version, Base, table, and field projection. TTL and last-good retention follow the existing node-assignment read settings. Old data returns immediately while a refresh runs. `quality.age_seconds` reports the oldest delivered source age for stale and read_failed responses. A failed schedule refresh retains its board with `read_failed`. A cold schedule failure returns HTTP 503 without counts. HTTP 403 responses contain no board counts. Error envelopes follow `backend/data_state.py`; successful boards use the contract's complete/partial/stale vocabulary.

The synthetic fixtures are plain contract responses.

- `backend/fixtures/dispatch_board_sample.json` contains an unassigned slot, timed conflicts, date-only unknown overlaps, an inactive person, a sent-for-repair instrument, a repaired normal instrument, and a disabled vehicle.
- `backend/fixtures/dispatch_board_stale_sample.json` retains the same slots with stale quality and age.
- `backend/fixtures/dispatch_board_read_failed_sample.json` retains the same slots with read_failed quality and age.

Check recorded field metadata with `python scripts/verify_dispatch_sources.py --snapshot fields.json`.
The file maps each table ID to its full `lark-cli base +field-list` JSON response or a field array. The checker prints one JSON line per dependency with verified, missing, or drift. Exit codes are 0 for all verified, 1 for missing or drift, and 2 for invalid or unreadable metadata. `--live` explicitly invokes the CLI for metadata only. Tests use synthetic snapshots and fake HTTP transports. They do not verify live schema or access.
