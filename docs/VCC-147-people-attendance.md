# People/resource and weekly attendance

`#view=people` uses `GET /api/people/attendance?week=YYYY-MM-DD`. Omitted week means the current Taipei week; any supplied day normalizes to its Monday. The window ends Sunday. Queries are limited to 26 weeks before or after the current Taipei week; unsupported dates return 422 before a cache claim or Lark read.

VCC-148 should import `fetchPeopleAttendance`, `PeopleAttendance`, and `attendanceValue` from `frontend/src/peopleAttendance.ts`. This is the same reader and cache as the People tab. The response includes:

- `status`: loading, ok, incomplete, stale, needs-permission, not-connected, or read-failed.
- `as_of`, `missing_scopes`, `refreshing`, and `incomplete`.
- `summary`: nullable people, in_service, on_leave, on_trip, and trips counts. Leave/trip counts are distinct people with approvals overlapping the selected week, including future dates.
- `people`: id, name, group, in_service, and seven nullable daily attendance labels.
- `trips`: person_id, name, group, kind, start, and end. Approval reasons are omitted.

The existing roster reader continues requesting exactly 姓名, 人員, 在職, and 內外勤 from its already configured Base/table. 內外勤 does not establish a group; unknown groups stay null. No new Base, field, Lark scope, or app release is configured.

The existing AttendanceRefresher owns the weekly reads. The existing coordinator implementation stores projected last-good snapshots under workspace/week cache keys, uses database leases, and serves snapshots during background refresh. Startup warms the current week without waiting for Lark. Reads use the existing application token cache, rate budget, and retries. Missing permission returns HTTP 200 with scope names and unknown summary values. HR_VIEWERS gates the API, and the API is in the GET-only tenant-read route allowlist.

Only GET attendance/v1/groups and POST attendance/v1/user_tasks/query and user_approvals/query were added to the Lark boundary. Group details and department expansion remain disallowed. The view therefore shows returned punch evidence and approval records; it does not infer obligations, an attendance percentage, or absence from missing punches. A day can contain both normal and exception labels from different punches.

Before live acceptance, confirm the app's granted scopes and the correct YX roster Base/table/group mapping. The implementation preserves the existing approved roster configuration until confirmed. Verify with a logged-in colleague on staging after deployment.

## Single cross-model review

Claude Opus 5.5 reviewed the implementation once. No P1 findings. Both P2 findings were fixed with focused tests: unread weeks retain a retry/loading state when refresh capacity is busy, and date queries are bounded to ±26 weeks with overflow returning 422 before refresh.

P3 follow-ups, recorded without further review or implementation:

- Use groups for membership only after group-detail/department expansion is approved; the current groups call validates the specified read and scope only.
- Reuse verified attendance identity mappings/settings where appropriate and retain each source person's identity_app_id when invoking the resolver.
- Consider using a recently stale roster during a failed refresh rather than requiring a fresh roster read first.
- Expire old weekly cache rows and completed future entries as the supported date window moves.
- Hide the People tab for excluded HR_VIEWERS users when narrowing the default list; the API already denies these reads.
