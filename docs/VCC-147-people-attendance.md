# People/resource and weekly attendance

`#view=people` uses `GET /api/people/attendance?week=YYYY-MM-DD`. Omitted week means the current Taipei week; any supplied day normalizes to its Monday. The window ends Sunday.

VCC-148 should import `fetchPeopleAttendance`, `PeopleAttendance`, and `attendanceValue` from `frontend/src/peopleAttendance.ts`. This is the same reader and cache as the People tab. The response includes:

- `status`: ok, incomplete, stale, needs-permission, not-connected, or read-failed.
- `as_of`, `missing_scopes`, `refreshing`, and `incomplete`.
- `summary`: nullable people, in_service, on_leave, on_trip, and trips counts. Leave/trip counts are distinct people with approvals overlapping the selected week, including future dates.
- `people`: id, name, group, in_service, and seven nullable daily attendance labels.
- `trips`: person_id, name, group, kind, start, and end. Approval reasons are omitted.

The existing roster reader continues requesting exactly 姓名, 人員, 在職, and 內外勤 from its already configured Base/table. 內外勤 does not establish a group; unknown groups stay null. No new Base, field, Lark scope, or app release is configured.

The existing AttendanceRefresher owns the weekly reads. The existing coordinator implementation stores projected last-good snapshots under workspace/week cache keys, uses database leases, and serves snapshots during background refresh. Startup warms the current week without waiting for Lark. Reads use the existing application token cache, rate budget, and retries. Missing permission returns HTTP 200 with scope names and unknown summary values. HR_VIEWERS gates the API, and the API is in the GET-only tenant-read route allowlist.

Only GET attendance/v1/groups and POST attendance/v1/user_tasks/query and user_approvals/query were added to the Lark boundary. Group details and department expansion remain disallowed. The view therefore shows returned punch evidence and approval records; it does not infer obligations, an attendance percentage, or absence from missing punches. A day can contain both normal and exception labels from different punches.

Before live acceptance, confirm the app's granted scopes and the correct YX roster Base/table/group mapping. The implementation preserves the existing approved roster configuration until confirmed. Verify with a logged-in colleague on staging after deployment.
