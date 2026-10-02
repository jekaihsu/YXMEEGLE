# Attendance identity read-only acceptance — 2026-09-29

## Final read-only result after scope-range publication

Dedicated app version 0.4.2 published all-member visibility. Repeated exact-ID acceptance then verified **58/58** eligible people; contact batches returned 50 and 8 users, and a single GET returned HTTP 200 / code 0. The earlier 41050 blocker described below is resolved.

The first real schedule query exposed a separate implementation bug: the API rejects 58 IDs in one call with HTTP 400 / 1220001 and a 50-person limit. `AttendanceScheduleReader` now splits into batches of at most 50 and rejects identities returned outside each requested batch. Targeted identity/schedule/service tests: **34 passed**. The amended reader was exercised in-memory through controlled service execution, without changing deployed files or production rows.

Real schedule queries for 2026-09-28 through 2026-10-04 returned HTTP 200 for both batches and both shift definitions. Out of **406 person-days**, **84** have verified normal shift end times, **210** lack a unique schedule, and **112** have flexible/unknown shifts. The aggregate remains `pending_schedule`; missing or flexible schedules were not replaced with 17:00 or inferred from punches. This proves read-only retrieval, not yet normal application synchronization or persistence of these mappings. The batch fix must be included in the next deployment.

An enablement request for `LARK_ATTENDANCE_IDENTITY_RESOLUTION=contact` was prepared by merging a fresh full environment snapshot; no remote setting was applied by this agent. Private request: `.runtime/attendance-contact-full-env-request.json`; receipt: `.runtime/attendance-contact-env-preparation.json`. Re-fetch and re-merge if any environment changes before application.

## Earlier diagnostic evidence

After the dedicated application received `contact:contact.base:readonly` and `contact:user.employee_id:readonly`, a controlled service execution queried only identity/admission fields from `company_people`. PostgreSQL transactions were READ ONLY. The application adapter requested exact same-app open IDs via the official contact batch endpoint. No names, salaries, or guessed relationships were used; no business database rows were written.

Observed initial result: 64 stored profiles; 58 eligible same-app, active, roster-confirmed employed profiles. Exclusions: 3 app identity unverified/mismatched, 2 inactive, 1 not verified employed. These are stored-profile eligibility counts, not the earlier raw roster row counts.

Both batches returned no users: 0 matched, 58 `contact_identity_not_returned`. A single exact-ID GET returned HTTP 400, code **41050**. The official batch API documentation identifies this as **no user authority**: the requested user must be within the application's contact authorization scope. Granted API scopes alone do not establish visibility of every company employee. The application's available/contact data range must be checked before declaring identity integration ready.

Private execution receipts and minimal mappings remain under `.runtime/attendance-identity-readonly-*.json`; logs report aggregate counts only. The runner `.runtime/verify_cloud_attendance_ids.py` does not persist mappings to production. A future successful read-only result still requires the normal authenticated Attendance synchronization flow after deployment to persist verified identities and obtain real schedule data.

Official source: [Batch get users](https://open.larksuite.com/document/server-docs/contact-v3/user/batch), archived locally as `.runtime/attendance-identity-doc-1-batch.md`; error 41050 links to [Contact authorization scope](https://open.larksuite.com/document/ukTMukTMukTM/uETNz4SM1MjLxUzM/v3/guides/scope_authority).

## Normal company API acceptance — supersedes the earlier runner-only limitation

At **2026-09-29T20:09:39+08:00**, the main executor confirmed a normal authenticated company `POST /api/attendance/sync` for 2026-09-28 through 2026-10-04 returned **HTTP 200**. The persisted result was `status=pending_schedule`, `ready_count=84`, `manual_override_count=0`, `issues=4`, `sync_revision=175`. This verifies the normal service path after the mixed-identity cohort fix; it does not mean every employee or person-day has a verified schedule. Pending identities or shifts remain pending rather than receiving an inferred cutoff.

The normal company roster was also observed updating naturally for **45 minutes**, with `sync_revision` advancing **215 → 223** and **58 exact verified roster identities**. The earlier **64** figure is the number of stored profiles, not 64 active employees. Application availability and roster eligibility still do not constitute each colleague's personal OAuth acceptance.

The second patch prevents retained historical attendance rows from supplying a current deadline when the employee is inactive, has left, lacks verified same-app roster evidence, or has stale roster evidence. It preserves schedule history and demo/test behavior. Its local regression suite passed **136 tests**. The patch is included in stage **`4a810052`**; deployment is in progress at this checkpoint, and **RUNNING and live acceptance have not yet been verified**. Do not attribute this second patch's behavior to the already completed HTTP 200 observation above.

The user delegated selection of a test participant; **文乃毅** was selected for QA only. This selection does not change the person's production role or authority, and does not authorize impersonating their OAuth session or approval.
