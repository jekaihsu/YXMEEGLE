# Lark-authoritative operations contract

Contract version 1, for YXS-41/T0. Base branch `ava-apple/yx-company-system` at `f1455b1671859cbe3b09ace82baee0903b33d0bc`. This document specifies the local/mock implementation. It does not authorize live changes or decide the open product policies below. MUST means a required invariant; proposed interfaces and test names are implementation obligations, not existing code or passing test evidence.

## Scope and existing responsibilities

New implementation belongs in `backend/ops_sync/`, with behavioral tests in `backend/test_ops_sync_*.py`. Existing modules may receive only thin wiring behind default-OFF flags. T0 changes this document only.

| Inspected source | Existing behavior and constraint |
| --- | --- |
| `sop_deadlines.py` | `_fixed` protects contract dates and contract-fixed policy. `_started` protects started/completed timestamps and statuses other than pending or None. `_materialize` detects manual dates, records prior date/provenance, retains assignments and task IDs, and records conflicts instead of rescheduling protected work. Completed nodes receive separate followups. Resolution checks the current date again. |
| `operations.py` | Workspace-transaction mutations; `project_roles` validates active/assignable IDs, records role changes and uses assignment helpers. Existing `lead`/`capable` rules are application rules, not evidence of Lark PM eligibility. `queue` rejects different payloads under the same key. |
| `native_approval.py`, `native_requests.py` | Bind receipts to application, tenant, workspace, project, request version, scope, definition and actual distinct approvers. Current production receipt validation rejects simulated, invalidated, stale or mismatched receipts and checks freshness. Mock receipts MUST remain distinguishable from this production proof. |
| `people_directory.py` | Application-scoped stable IDs, complete pagination, duplicate-account rejection, no name merge or privilege restoration. The approved four-column reader does not supply a PM capability/eligibility field. Do not expand its whitelist. |
| `source_entities.py` | Source identity uses base/table/record IDs; preserves linked project/task references and revision snapshots. Missing source entities remain recorded. |
| `lark_adapter.py` | Typed canonical/wire conversion and read-compare-PUT-read. Transport/uncertain write results are unknown outcomes. Existing omitted-field reads via `.get` are insufficient for this contract's presence-aware semantics. Do not reuse that behavior as proof of clear. |
| `capability_write_policy.py`, `features.py` | Protected capability Base guard and paused learning state remain unchanged. No implicit bypass or PM permission from personnel adapters. |
| `storage.py` | Existing workspace JSON metadata and normalized entity materialization in caller-owned version-checked transactions. Store ops state inside workspace JSON or an injected store; add no tables or migrations. |

No live Lark reads, writes, schema modifications, subscriptions or migrations in this work. No new credentials, permissions, dependencies or production deployment. No protected personnel, payroll, quote, V4, original daily-report or Meegle writes. Training, capability, evaluation and payroll remain paused. Fixtures use synthetic IDs such as `ou_test_pm_1`; no real personal/production data. Names are display text only.

## Identity, eligibility, authorization and assignment

A person identity is the tuple of tenant, application ID and stable person ID. Validate all three; do not match names, select the first person in a list, or infer identity from a role label. Synthetic mock IDs need not satisfy the older production adapter's ID regex and MUST never reach it.

`EligibilitySource.lookup(person_identity, at)` returns `eligible | ineligible | unknown` plus source revision, observed_at, validity limit and reason. The exact Lark field and its governance are OPEN. Missing, partial, forbidden, stale, ambiguous or wrong-application evidence returns unknown. Unknown denies eligibility-sensitive actions. The mock source is injected; no production reader expansion is implied.

Application authorization independently answers whether an authenticated active actor may submit a given field command, assign someone, approve, or resolve a conflict under current application policy. Eligibility confers no application permission. Application permission confers no eligibility. Per-case assignment independently records who holds the PM seat for that case. Holding the seat confers no implicit global PM capability.

A case has zero or one confirmed PM. A PM assignment accepts exactly one eligible active identity, or explicit CLEAR if the authorized assignment policy permits an empty seat. Check eligibility/authorization both at submission and immediately before execution. An imported list of multiple distinct assignees becomes an assignment conflict; retain the last confirmed assignment and all observed candidates. Do not pick one. Node responsibility also accepts zero or one active, application-admitted stable identity; PM eligibility is required only if that person is also assigned a PM seat.

If a confirmed PM becomes ineligible/revoked, or eligibility becomes unknown, retain the recorded PM identity and assignment history but mark the seat `blocked_ineligible` or `blocked_unknown`. Deny further PM-seat actions and pending PM-dependent approvals. Do not silently clear, replace or reassign the person or their tasks. Restoration requires fresh evidence; replacement is an explicit authorized command. Eligibility revision changes invalidate pending receipts that depend on that seat.

Assignment history is append-only with prior/new identities, actor identity, source, command/event ID, reason and aware timestamp. Replays append nothing. Case PM changes do not mass-change task owners. Explicit task handovers preserve existing task assignment history and completed work.

## Entities and dates

| Entity | Required identity and links | Governed fields |
| --- | --- | --- |
| `OperationalCase` | Immutable `entity_id`, existing `project_id`, optional verified source record binding, schema binding version | `case.pm`, `case.deadline` |
| `NodeRecord` | Immutable `entity_id`, existing `node_id`, parent case entity ID and `project_id`, existing `task_ids`, optional verified source binding | `node.responsible`, `node.deadline` |

Use opaque existing IDs; do not regenerate, infer from a title, or create duplicate projects/nodes/tasks on import or restart. Validate parent/child linkage and uniqueness. Headers and nodes are provisional separate operational records, not a modification of existing source quotation/contract records.

Each deadline stores separate original/contract, approved effective and proposed values, plus append-only revisions/provenance. Original/contract is immutable evidence; amendments append a new contract revision and do not overwrite the original. Effective is the confirmed approved operational deadline. Proposed is a requested change with request/command identity and approval state; multiple proposals remain identifiable. Derived task dates record anchor identity/version, rule/version, calendar snapshot/hash and calculation result. Never treat a derived date as a formal effective deadline.

Provisionally every SET or CLEAR of case/node effective deadline requires a bound approval. Submission records a proposal and `waiting_approval`; effective stays unchanged. A receipt binds command ID, entity/field, expected baseline, canonical intended value, proposal version, case/node scope, schema version, eligibility/assignment revisions, approver identities and approval-policy version. Check scope, freshness and all required votes immediately before mutation. Mock verifier can attest only mock receipts.

Rejected, withdrawn or expired proposals terminate as failed with the matching reason. Stale approvals fail closed; a changed baseline becomes conflict. Duplicate receipt consumption returns the stored result without another mutation or history entry. None of these outcomes changes the effective date. Withdrawal before dispatch removes write eligibility; withdrawal during uncertain delivery requires reconciliation and must not pretend the write never occurred. Approval expiry/freshness uses an injected aware clock; provisional mock receipt validity is at most 300 seconds, with no future verification timestamps. Owner policy can supersede this default only through a versioned decision.

Only confirmed effective changes can trigger derived-date recalculation. Reuse existing workday/calendar semantics. Existing manual, fixed, started or completed tasks retain due dates and original dates; record a proposed derived-date conflict with provenance. Manual means an explicit manual policy or an existing date without derivation provenance or unequal to its recorded calculation. Match existing `_fixed` and `_started` protections, including non-pending statuses. Recalculating must not change task IDs/owners or reopen a completed node. An explicit authorized conflict resolution can adopt a derived proposal only for an unstarted, non-fixed task with unchanged baseline; started/completed/contract-fixed changes need a separately approved formal process outside automatic recalculation.

## Commands and value presence

An immutable command envelope contains:

| Field | Contract |
| --- | --- |
| `command_id` | Unique stable operation identity, reused for every delivery/recovery attempt |
| `entity_id`, `field_id` | Exact verified case/node identity and one governed semantic field |
| `expected_baseline` | Canonical known value or known CLEAR, plus field revision; UNKNOWN is invalid |
| `intended_value` | Typed SET value or explicit CLEAR; OMITTED and UNKNOWN cannot request mutation |
| `actor` | Authenticated stable identity and verified authority context; no client-asserted privilege |
| `source` | `app` or `lark`; origin does not bypass validation/approval |
| `occurred_at` | Offset-aware instant, normalized to UTC; never used as last-write-wins priority |
| `approval_ref` | Bound proposal/receipt reference or explicit absence for fields not requiring approval |
| `schema_binding_version` | Exact approved mock/live binding revision; mismatches fail closed |

Canonical serialization determines a payload fingerprint. Same command ID and same fingerprint returns its persisted status/result. Same ID with different payload is an identity collision and is rejected without mutation. A conflict-resolution command has a NEW ID, links the original/conflict ID, captures a fresh known baseline and states `keep_current`, `apply_intended` or `set_explicit`. It needs the same authorization/approval rules as the field. Keep-current writes no value but records an explicit resolution. Never rewrite the original command.

Presence has three distinct exceptional states in addition to SET:

- CLEAR means an explicitly observed or requested empty value. It is not inferred from an absent JSON key. SET(null) is invalid; nullable input must explicitly encode CLEAR.
- OMITTED means a field is outside a command/patch. Preserve it and send no write for it.
- UNKNOWN means unreadable, incomplete, forbidden or unverified observation. Preserve the prior confirmed value and record the reason. It cannot be a baseline, clear or success receipt.

An observation includes requested fields, returned fields, completeness, permissions, binding version and source revision. A null/empty field counts as observed CLEAR only when the adapter proves this field was readable and fully represented under its versioned schema. Missing fields/pages/records never imply CLEAR/deletion. Explicit deletion/tombstone is separate evidence and must not erase existing IDs/history.

Date-only fields accept strict valid `YYYY-MM-DD` calendar dates in Asia/Taipei, never locale-ambiguous strings. They stay dates in the domain. A documented timestamp wire mapping converts an aware instant to Asia/Taipei before extracting the day; writing date-only milliseconds uses Taipei midnight. For example `2026-10-10T16:00:00Z` means local date `2026-10-11`. Reject invalid dates, booleans as timestamps, unexpected precision/types and naive datetimes. All audit/event/clock timestamps require timezone offsets; do not slice a UTC string to obtain a local day.

## Durable delivery and reconciliation

Store commands, outbox, inbox, dedup fingerprints, attempts, leases, checkpoints, conflicts, receipts and history in a single `ops_sync` workspace JSON namespace, or injected transactional store with equivalent guarantees. Persist acceptance plus outbox/proposal atomically before acknowledging acceptance. Atomically persist inbox dedup plus observation/projection changes and checkpoint. Use the existing version-checked transaction path to prevent lost workspace updates. Do not overwrite unrelated workspace state with a stale snapshot. The owner clarification on 2026-10-11 requires deliberate failures proving atomic persistence, crash/restart recovery, duplicate suppression and concurrent-process behavior. An in-memory mock alone is insufficient. If the existing transaction/store cannot provide these guarantees, report a narrow storage blocker instead of weakening them.

Serialize controlled writes per entity, including all fields and approval events. The mock adapter supports per-field CAS and a durable operation-ID ledger. The ledger atomically records the command fingerprint and resulting field revision with the write. Entity serialization alone is not cross-process locking; store leases must fence stale workers. A crash after reserving an attempt may mean the remote call happened.

| State | Meaning and allowed transitions |
| --- | --- |
| `waiting_approval` | Durable proposal, no write attempted. Valid current receipt moves to queued; rejection/withdrawal/expiry moves to failed; baseline divergence moves to conflict. |
| `queued` | Accepted pending dispatch/backoff. Revalidate identity, authority, eligibility, approval, binding and baseline. Verified write/read-back moves to confirmed; divergent field moves to conflict; definitive denial/validation failure or exhausted safe retries moves to failed; any possibly committed/unverifiable write moves to unknown. |
| `unknown` | Commit outcome uncertain. Preserve effective projection and proposal separately; set durable reconciliation phase `pending` or `reconciling`. No blind write retry. |
| `confirmed` | Adapter receipt and complete authoritative read-back verify intended value and operation identity under the controlled path. Commit projection/history once. Terminal for this command. Later edits are separate observations/commands. |
| `conflict` | Expected/current/intended differ, or assignment is ambiguous. No automatic overwrite. Terminal for original command; explicit resolution creates a linked new command. |
| `failed` | Definitive no-write denial/invalidity, terminal approval outcome, or exhausted safe retry budget. Retain reason/history. A changed request needs a new command; unknown is never relabeled failed just because reads exhausted retries. |

Before dispatch persist attempt number, lease/fence and start time. On restart recover persisted work: waiting proposals stay waiting, queued work respects next_attempt_at, expired in-flight leases become unknown, and unknown work resumes read-back. Do not allocate a replacement command ID or rely on in-memory deduplication.

For unknown, consult the operation ledger/receipt and perform a complete bound read. If identity and value/revision prove this operation committed, confirm once. If the ledger proves it never committed and current baseline is unchanged, revalidate all gates and queue a retry with the SAME command ID. Divergence becomes conflict. If the read is partial/forbidden or identity cannot be proved, remain unknown with an explicit blocker. Mere equality to intended value is not identity proof; another writer could have set it. If the operation committed and a later edit is observed, record the original receipt and a separate conflict/observation rather than reverting the later edit.

Use injected clock and sleeper/scheduler; no wall-clock sleeps in tests. Provisional mock limits: five write attempts including first, exponential delay `min(60, 2^(attempt-1))` seconds, respecting a larger retry-after. Retry only documented safe no-commit transient failures. Every ambiguous timeout, malformed write response or server failure goes to unknown first. Reconciliation has five reads per recovery cycle with the same backoff; exhaustion retains unknown and disables automatic dispatch until an explicit recovery action schedules another read cycle. Record attempts/reasons without sensitive payloads. A permission or schema problem suspends affected dispatch immediately.

## Storage durability

Workspace JSON is a candidate durable store, not a proven guarantee. The implementation MUST prove atomic acceptance/outbox persistence, atomic inbox/dedup/projection/checkpoint persistence, restart recovery and cross-process serialization before using it for this command path. A flag and an in-memory mock do not satisfy durability.

For file-backed JSON, hold a cross-process lock across the entire read-modify-write transaction, including reading the latest committed state. Update only the scoped `ops_sync` namespace and preserve unrelated keys. Write a complete validated snapshot to a temporary file on the same filesystem, flush and fsync that file, atomically rename it over the committed file, then fsync the containing directory before acknowledging durable success. The lock must cover every cooperating writer of this shared JSON, not only ops writers. Version checks and worker fencing must reject stale transactions/leases. A database-backed workspace JSON store may use an equivalent atomic durable transaction, but its actual commit/recovery semantics must be demonstrated rather than inferred from the JSON format.

On restart, load only a validated complete committed snapshot. A leftover temporary file is not a committed command. A torn, partial or corrupt committed file must fail closed with an explicit storage blocker; never silently initialize an empty store or erase dedup/history. Preserve recovery evidence. Recover unknown deliveries through the same command identity and read-back rules above. A crash must expose either the previous complete transaction or the next complete transaction, never a partial combination.

The following deliberate-failure tests are mandatory implementation evidence in addition to the adversarial matrix. Use a real persistent store and independent OS processes, synthetic data, deterministic failure barriers and fresh-process reopen checks. These names are obligations, not tests run by T0.

| Failure injection | Named behavioral test | Required observable result |
| --- | --- | --- |
| Kill the writer during temporary-file write, after file fsync, after rename and before/after directory fsync or the equivalent transaction commit barriers | `test_storage_kill_mid_write_recovers_complete_transaction` | Restart sees a complete old or new snapshot; every acknowledged commit survives; no partial command/outbox/inbox/history. An uncertain unacknowledged dispatch reconciles with its original identity. |
| Truncate/corrupt a temporary file and separately the committed file | `test_storage_torn_partial_file_fails_closed_without_reset` | Incomplete temporary state is never promoted; invalid committed state blocks operations explicitly, preserves evidence and never resets existing IDs/dedup/history. |
| Crash after durable command acceptance and after durable adapter commit but before local confirmation; replay commands/events after restart | `test_storage_restart_preserves_duplicate_suppression` | Fresh process recovers pending/unknown state and suppresses duplicates; one adapter effect and one history entry per operation, with the same command/event identity. |
| Two independent processes write the same workspace, including competing field updates and a stale worker | `test_storage_two_process_writers_serialize_and_fence` | Cross-process lock/version checks prevent lost updates; same-field competition conflicts; stale worker cannot dispatch; different-field state survives. Process death releases/reclaims ownership safely. |
| An unrelated workspace writer races an ops transaction and an injected commit failure | `test_storage_ops_transaction_preserves_unrelated_workspace_keys` | Unrelated sentinel keys/values survive both successful commits and recovery. All shared-file writers participate in the lock or equivalent transaction; a scoped namespace alone is insufficient. |

**Go/no-go criterion:** GO only when every guarantee above has passing deliberate-failure evidence for the actual workspace store, including all cooperating writer paths and filesystem/transaction durability semantics. Record commands, output and tested implementation SHA. Until then, workspace JSON durability is UNPROVEN. NO-GO if any required guarantee fails or cannot be tested: stop durable integration, retain disabled flags/live writer, and report the narrow storage decision/blocker to the Lead. Do not substitute an in-memory store, weaken recovery or concurrency guarantees, add SQL tables/dependencies, or change storage policy without the required decision and approval.

### Workspace row store (`backend/ops_sync/workspace_store.py`): proven vs not proven

`WorkspaceStore` is the `OpsStore` the local feature path uses when `FEATURE_LARK_AUTHORITATIVE_OPS` is on (default off; `app.state.ops_store_for`). It works on the existing `workspaces` row (`id`, `version`, `data` JSON) with no new schema: read `(version, data)`, run the transaction on a private copy of `data["ops_sync"]` only, write back with `UPDATE ... WHERE id=? AND version=?`, bump `version` exactly as `app.persist_mutation` does and mirror it into `data["version"]` (the app serves that value and checks it against `row.version`). A CAS miss re-reads and re-runs the transaction, bounded (default 8); exhaustion raises `StorageBusy` and commits nothing. A missing row, non-object data, non-object namespace, non-integer version or undecodable JSON raises `StorageBlocked` and writes nothing. `JsonFileStore` stays a test-only store.

| Guarantee | Status | Evidence (`backend/test_ops_sync_workspace_store.py` unless noted) |
| --- | --- | --- |
| Commit-or-nothing on exception and injected failure | PROVEN on SQLite | `test_fn_exception_commits_nothing_and_keeps_the_version`, `test_injected_failure_mid_transaction_is_commit_or_nothing` |
| kill -9 at each commit barrier, restart recovery, replay safe | PROVEN on SQLite | `test_kill_9_at_each_commit_barrier_recovers_a_complete_old_or_new_state`, `test_external_sigkill_mid_stream_loses_no_acknowledged_command_and_never_splits_a_commit`, `test_storage_kill_mid_write_recovers_complete_transaction[workspace-*]` |
| Duplicate command/event suppression across restart | PROVEN on SQLite | `test_duplicate_command_and_event_suppression_survives_restart`, `test_storage_restart_preserves_duplicate_suppression[workspace-*]` |
| Two-process contention, no lost updates, same-field conflict | PROVEN on SQLite | `test_two_process_contention_has_no_lost_updates_and_conflicts_on_the_same_field`, `test_storage_two_process_writers_serialize_and_fence[workspace]` |
| App writer and ops writer neither clobber the other; unrelated keys kept | PROVEN on SQLite, including the real `create_app` write path and an `app.persist_mutation`-style CAS writer | `test_app_style_writer_is_not_clobbered_by_an_ops_write_and_vice_versa`, `test_ops_namespace_survives_real_app_writes_and_stale_app_clients_get_a_409`, `test_storage_ops_transaction_preserves_unrelated_workspace_keys[workspace]` |
| Fail closed on corrupt/missing data, no reset | PROVEN on SQLite | `test_corrupt_row_data_fails_closed_without_reset`, `test_missing_row_fails_closed_and_creates_nothing`, `test_non_integer_row_version_fails_closed` |
| JSON round trip (CLEAR/SET/UNKNOWN tags, unicode) | PROVEN on SQLite | `test_json_column_round_trip_keeps_markers_unicode_and_types` |
| Engine and storage suites on both stores | PROVEN | the `store_kind` fixture (`backend/conftest.py`) runs the engine, domain-persistence and storage suites against `JsonFileStore` and `WorkspaceStore` |
| PostgreSQL | **UNTESTED. No claim is made.** | No PostgreSQL was available. The CAS is plain SQL and row-level, but read-committed isolation, `synchronous_commit`, pool/replica behavior and `with_for_update` interplay with `persist_mutation` are unverified. |
| Durability against power loss / OS crash | NOT proven | Tests kill the process, not the machine. SQLite's default journal gives crash safety only with honest `fsync`; this was not fault-injected below the process level. |
| App writers other than the `persist_mutation` pattern | NOT proven | `index_health_run` rewrites with an unchanged version and `create_app` start-up migration writes `data` without a version bump. Neither is a CAS-safe writer; ops writes that race them are not covered. |
| Live Lark, production or staging data | NOT touched | Synthetic data and temp SQLite files only. |

The wiring imports `ops_sync` only when the flag is on; `backend/ops_sync` is not yet in the deploy package inventory (`scripts/deploy_prepare.py`), so enabling the flag in a staged build needs that inventory change first (YXS-45 scope).

Side effect to expect: every ops commit bumps `row.version`, so an app client holding an older workspace version gets the app's existing 409 and must reload.

## Events and conflicts

Persist inbox events before processing. Dedup by source scope and `event_id`; identical replay is a no-op, different payload under the same ID is a failed integrity check. Events carry entity/field, source revision, command identity if available and presence-aware observations. Never trust arrival order or occurred_at as authoritative revision order.

A revision below/equal to the processed revision cannot roll back confirmed values. Equal revision with different content is an integrity conflict. A gap or an unversioned event schedules complete read reconciliation; missing events are recovered through explicit checkpoint/read recovery in the mock slice. Incomplete snapshots do not advance a complete checkpoint or erase values. Do not create live subscriptions. Lark-originated effective deadline changes are proposals requiring the controlled approval path, not an approval bypass.

Same-field writes compare canonical expected value AND field revision against the current known baseline. A competing same-field revision creates a conflict, even if values changed away and back. Record conflict ID, entity/field, expected/current/intended values and revisions, command IDs, actors/sources, binding, reason and timestamps. No last-write-wins. A replay with a proven operation receipt is idempotent, not a competing write.

Different-field commands compare their own baselines and merge only their field patch. Do not PUT a stale whole-record snapshot. An unrelated revision must not invalidate the field baseline unless approval scope explicitly depends on it. Preserve all unrelated fields and history. Conflict resolution re-reads a complete baseline and fails if another change occurred; it cannot force overwrite or bypass protected-task rules.

Permission loss is `permission_denied` and schema drift is `schema_binding_mismatch`; both fail closed before dispatch. If discovered after a possibly committed call, keep unknown with that blocker until reconciliation proves the result. Validate field IDs/types, record links, person cardinality and binding version. No field-name guessing, silent remapping or automatic retry under a new schema. A reviewed new binding requires a new command/approval when it changes command scope.

## Concurrency limits

Lark has no documented CAS/If-Match contract available to this design. The existing read-compare-PUT-read sequence has a time-of-check/time-of-use window. A direct editor can change the field between comparison and PUT, and read-back does not recover an overwritten value. This document does not assert a newly verified live API guarantee; this task makes no live calls.

Strict same-field conflict, operation idempotency and different-field preservation guarantees apply to the controlled-writer path with one fenced writer per entity and the mock adapter's CAS/operation ledger. Unrestricted direct Lark edits plus app edits cannot strictly promise lossless concurrent updates. Field patches reduce unrelated-field overwrites but do not close the same-field race. Provisionally all formal effective deadlines must use controlled commands; direct observations become proposals/conflicts. Future live editing restrictions and authority are OPEN owner decisions. Do not claim that polling, timestamps or a process-local mutex provides remote CAS.

## Flags and user-visible claims

Proposed flags `FEATURE_OPS_SYNC`, `FEATURE_OPS_SYNC_MOCK_UI`, `FEATURE_OPS_SYNC_LARK_EVENTS` and `FEATURE_OPS_SYNC_LIVE_WRITES` all default to False. These names are contract requirements for later wiring, not additions made by T0. A local mock configuration may explicitly enable only the core/mock UI. Live writes remain hard-disabled regardless of environment/config overrides; attempting to construct/dispatch a live ops writer must reject without network I/O. Tests must assert default-OFF and this hard disable. Existing paused flags/guard/whitelist remain unchanged.

Show distinct waiting approval, queued/pending, confirmed, conflict, failed and unknown/reconciling states with actionable reasons. Submission acknowledgment means accepted pending work, not success. Display confirmed effective values separately from proposals and last-confirmed values during unknown reads. Mock confirmation must say local/mock confirmed; never say live sync, saved to Lark, production approved, or lossless concurrent live editing. Hide disabled mutation controls. Unknown, denied eligibility and ambiguous assignments disable dependent actions; errors must not silently fall back to success.

## Adversarial test obligations

All tests below are planned, not implemented or executed by T0. Use deterministic synthetic identities, an injectable clock/store, and adapter barriers/fault injection. Assert observable stored values, visible delivery states, write counts and preserved history, not internal call sequences. Full implementation verification runs `scripts/local_ci.sh` on each submitted code SHA, plus real local UI evidence where included.

| Parent acceptance item 3 case | Named behavioral test in `backend/test_ops_sync_*.py` | Required outcome |
| --- | --- | --- |
| Same-field race | `test_same_field_race_conflicts_without_overwrite` | Two writers with one baseline; one confirms, other records expected/current/intended conflict; winner retained. |
| Different-field race | `test_different_field_race_merges_field_patches` | Both field edits confirm; unrelated values/history preserved. |
| Baseline changed away and back | `test_same_value_new_revision_still_conflicts` | Field revision prevents ABA overwrite. |
| Ineligible PM | `test_ineligible_pm_assignment_denied` | No write/confirmed seat, clear reason. |
| Revoked PM | `test_revoked_pm_blocks_pending_action_preserves_assignment` | Queued action denied after revocation; recorded person/tasks/history preserved. |
| Unknown PM evidence | `test_unknown_pm_eligibility_denies_without_role_inference` | Missing/stale/forbidden evidence and legacy PM role confer no eligibility. |
| Multiple assignees | `test_multiple_pm_assignees_record_conflict_without_first_choice` | All candidates recorded, prior seat retained, no guessed assignment. |
| Authorization separate from eligibility | `test_eligible_person_has_no_implicit_application_permission` | Eligibility alone cannot submit, approve or resolve. |
| Null/presence | `test_clear_omitted_unknown_are_distinct` | CLEAR is explicit; omitted/unknown/missing fields preserve values; SET(null) rejected. |
| Dates | `test_invalid_date_and_naive_datetime_rejected` | Invalid dates/types/naive instants rejected before write. |
| Time zone | `test_taipei_date_roundtrip_crosses_utc_midnight` | UTC boundary example round-trips to correct Taipei date. |
| Duplicate approvals | `test_duplicate_approval_applies_effective_deadline_once` | One mutation/receipt consumption/history append. |
| Stale approvals | `test_stale_scope_or_expired_receipt_cannot_change_effective_date` | Scope/baseline/person/policy changes or expired/future receipt cannot apply. |
| Other terminal approvals | `test_rejected_withdrawn_expired_proposal_preserves_effective_date` | All terminal outcomes retain effective/original dates. |
| Duplicate events | `test_duplicate_event_is_noop_and_payload_collision_rejected` | Identical replay no-op, ID collision recorded without mutation. |
| Out-of-order events | `test_out_of_order_event_cannot_roll_back_projection` | Older revision cannot replace newer field/history. |
| Missing events | `test_missing_revision_requires_complete_read_recovery` | Gap schedules read; partial reads preserve baseline/checkpoint. |
| Permission drift | `test_permission_loss_fails_closed_without_clear` | No new write, prior values retained; uncertain prior write remains unknown. |
| Schema drift | `test_schema_binding_mismatch_fails_closed` | Mismatched version/type/identity never writes or remaps silently. |
| Timeout after commit and restart | `test_timeout_after_commit_restart_reconciles_same_command_once` | Durable unknown, restart reads ledger/current value, confirms once with original ID and one write/history entry. |
| Unknown before commit | `test_unknown_requires_proven_noncommit_before_same_id_retry` | No blind retry; proof plus unchanged baseline allows bounded same-ID delivery. |
| Restart before/after persistence | `test_restart_recovers_outbox_inbox_and_fences_old_worker` | Atomic acceptance/dedup survives crash; stale worker cannot dispatch. |
| Atomic persistence and concurrent processes | `test_process_race_and_commit_failure_preserve_atomic_ops_and_unrelated_state` | Two independent processes race workspace versions; one retries safely or conflicts, no unrelated JSON loss. Inject failure before commit and prove no partial command/outbox/inbox/history state; reopen the persistent store after commit and prove durability. |
| Bounded failures | `test_backoff_budget_and_unknown_exhaustion_are_visible` | Injected clock verifies attempt bounds; no busy loop or false failed/success. |
| Preserved IDs/history | `test_roundtrip_preserves_project_node_task_ids_and_histories` | Import, edit, replay and restart preserve original IDs, date and assignment histories. |
| Protected tasks | `test_recalculation_preserves_manual_fixed_started_completed_tasks` | Protected dates/owners retained, derived conflicts recorded; completed node stays completed. |
| Explicit resolution | `test_resolution_requires_fresh_baseline_and_current_approval` | New linked command, re-race conflicts, no bypass of deadline policy. |
| Feature boundaries | `test_flags_default_off_and_live_writer_hard_disabled` | All defaults false; attempted live enable performs zero network calls; paused policies unchanged. |

If UI is included later, real-browser evidence must cover loading, empty, validation, waiting/queued, unknown/reconciling, conflict, failure and confirmed mock states, responsive and keyboard behavior. Use the worker's own port, never 8000. Screenshots must not contain real personal data.

## Open owner decisions

These decisions do not block contract/mock work and do not grant live permission.

| Decision | Recommended provisional default | Required before live work |
| --- | --- | --- |
| Live field mappings | Separate operational header/node records; mock semantic fields only; preserve existing project/node/task IDs. | Owner-approved Base/table/field IDs, types, linkage and binding version. No live schema creation in this work. |
| Exact PM eligibility field and governance | Dedicated Lark-sourced eligibility evidence with explicit eligible/ineligible/unknown, unknown deny; no existing role/whitelist inference. | Exact field, who may change it, source of authority, freshness/revocation policy and audited governance. |
| Editing mode | Controlled writer for formal effective fields; direct edits treated as proposals/conflicts; mock-only delivery. | Owner choice of restricted controlled editing or acceptance of documented concurrency limits. Live writer remains disabled pending a separate approved task. |
| Deadline approval policy | Require bound current approval for every effective date SET/CLEAR; preserve original dates and task protections; mock distinct PM/supervisor votes with explicit authority checks. | Exact approver seats, delegation rules, external evidence, expiry/freshness, withdrawal policy and permitted exceptions, all versioned. |

## T0 evidence boundary

T0 delivers this document in one local commit. No production code or tests change. `scripts/local_ci.sh`: not run, docs only, under the task-specific exception. The matrix is a test specification, not passing evidence. Independent review/verification and Lead closure are still required. No push, PR, merge, deployment or self-approval.

## Field-mapping reconciliation (owner audit, label-level; NOT approved live bindings)

Source: owner workbook 工作台與Lark標頭對照.xlsx. All 351 actual mapping / writeback / two-way-sync tests are **unperformed** (row 41) and no field IDs or types exist (row 43). Therefore every mapping below is a candidate and the synthetic flow labels it "未確認／模擬".

- **Case PM**: H0073/H0183/H0197 (rows 52/129/143) are candidates only. They do not establish PM eligibility; A0003/A0013 (rows 253/263) are unmapped. Eligibility is a synthetic fixture rule behind the adapter.
- **Node owner**: H0078 (row 57) is unconfirmed; H0164 (row 112): a case/quote PM does not prove node responsibility, so the UI never infers it.
- **Dates**: case deadline candidates H0182/H0201/H0202 (rows 128/147/148) must not be reused as task original/effective dates H0023/H0031 (rows 22/30).
- **Identity**: A0010 (row 260): OpenID, Lark account and person are different identity types; the flow uses a typed (tenant, app, person_id) binding, never a display name or free string.
- Qualification, assignment, node and date mappings stay separate and unmapped states are preserved. No label-based auto-binding, no live schema/data write, no live adapter enablement.
