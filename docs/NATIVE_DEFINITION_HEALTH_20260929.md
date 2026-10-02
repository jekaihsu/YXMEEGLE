# Native definition read-only health verification

`POST /api/native-approvals/definitions/verify` accepts only `{ "version": <current workspace version> }`.
It requires a normal, currently admitted company manager in the real company
workspace. Recovery-only bootstrap access, members and isolated workspaces are
rejected. This is administrative health verification, not approval authority.

The route reads each configured financial/change/extension/node-skip definition
with `GET /approval/v4/approvals/{code}`, verifies the exact form and approval
node mapping using the existing verifier, then saves the health evidence through
the ordinary workspace CAS/persistence/audit path. Actor, policy and workspace
are checked before and after every remote request and before persistence.
It never creates a business request, binding, UUID, instance or vote. Existing
submission enablement, DEMO_MODE and native case-context guards are unchanged.

Evidence lives in `native_definition_verification`: app/tenant/workspace,
mapping-set hash, per-kind mapping/definition hashes, checked-by and timestamps.
The public projection removes this raw object. `approval_connection` receives it
server-side and exposes only verified flags and `verified_at` for each kind.
Evidence expires after 15 minutes; changes to app, tenant or mappings invalidate
it. A failed fresh read/mapping verification replaces old success with unverified
status. Remote response bodies and errors are not stored in public health data.

UI integration: normal manager button calls the endpoint with the displayed
workspace version and refreshes from the returned workspace. Inspect
`approval_connection.native_submit.by_type[kind].definition_mapping_verified`
and `.verified_at`. Definition health can be verified while submission remains
disabled. Result-binding and end-to-end blockers are deliberately retained.

Validation: `python -m pytest backend/test_native_definition_health.py
backend/test_approval_capabilities.py backend/test_native_routes.py
backend/test_native_service.py backend/test_native_approval.py -q` passed
**80 tests in 30.56 seconds**, including 18 new health-route/TTL/race tests,
public workspace/mutation privacy projection, and unchanged native submission
guards. This is local validation using fake external responses, not live health
verification or real approval acceptance.
Additional malformed-response and definition-drift regression cases subsequently
passed with the complete health suite: **20 passed in 10.49 seconds**. Both
replace prior verified health with unverified evidence, like transport failures.

## Remaining real approval acceptance boundary

Definition verification does not prove real creation, human approval, result
binding or business application. Existing native routes require a formal
company case and cannot be used for isolated QA by changing mode, workspace ID
or simulated flags. No QA exception was added.

The smallest transport acceptance scenario is extension: its documented mapping
has one supervisor seat. One user-selected test employee can personally approve
that QA seat. Change, node skip and financial still require their two distinct
real approvers; one employee cannot stand in for both.

If testing must avoid changing any production case, a separate acceptance runner
and durable database are required, with an explicitly isolated QA binding,
dedicated maintainable QA definition, and the selected real employee allowlist.
QA artifacts must not be production projects or source records. QA receipts must
never enter production approval collections or authorize business application.
The current `prepare_binding` function explicitly accepts only the production
workspace namespace; callers must not lie about a QA namespace to bypass it.
Such a runner is not implemented by this change. A successful transport test
would still be reported separately from a full production business-flow test.

No real definition or approval instance was created or changed, and no person
was notified or approved on behalf of by this workstream.
