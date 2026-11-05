# Lark sync and storage performance, 2026-10-25

Measured baseline `5c39bb0` before changing code, then replayed that commit from an isolated export for the five-repeat comparison below. The final after measurements use implementation commit `9b20ad2`. All measurements use fictional records, local databases, and fake refreshers. No Lark requests, writes, deployment, push, or changes to sibling worktrees were performed.

The source benchmark imports 420 projects, 5,880 daily records, and 21,849 normalized business rows. Each scenario runs five times; numbers below are median milliseconds. The first unchanged run follows a failed attempt and deliberately re-imports; the other four exercise an unchanged healthy cache. The raw JSON includes minima/maxima. Other implementation agents were running tests on the same developer machine, so these wall times are local observations rather than staging latency guarantees.

| Database / scenario | Before | After |
| --- | ---: | ---: |
| PostgreSQL unchanged sources | 1,124.0 | 143.0 |
| PostgreSQL changed sources | 6,322.7 | 1,936.2 |
| SQLite unchanged sources | 907.4 | 133.5 |
| SQLite changed sources | 5,430.6 | 1,808.0 |
| PostgreSQL request with a contended lease row | 253.6 | 0.2 |
| SQLite request with a contended lease row | 287.5 | 0.1 |

An initial three-repeat baseline measured PostgreSQL unchanged/changed at 809.5/4,120.8 ms and SQLite at 714.5/3,698.9 ms. The same bottlenecks appeared in both baseline rounds. The lease benchmark holds an actual database write transaction until either the refresh call returns or a 250 ms timer expires. It verifies one eventual refresh per stale dataset; the five calls in each run all refreshed exactly once. Only the source refresh is fake.

Unchanged source refreshes now perform **zero full workspace loads, zero whole-state fingerprints, zero imports, and zero business-row writes**. They load users/templates for the existing authorization/upgrade checks, validate source content and the persisted workspace revision, then advance root/cache metadata. Source generation, project content, and event history remain unchanged. The source cache JSON is still rewritten to advance timestamps.

Profiling the original two-repeat source benchmark showed 12,444,600 calls to `normalized_case`. Daily matching scanned all project codes for each row, and daily replacement scanned every project's accumulated history repeatedly. The importer now builds exact-code/reviewed-alias candidates once and removes fetched daily evidence in one pass. It retains all conflicting/native candidates and delegates attribution to the existing resolver. A bounded 4,096-entry cache stores normalized text, including the current text of mutable Lark formula values.

The coordinator already ran remote reads in workers, but acquired database leases synchronously in requests. Claims now run in the same bounded worker lanes. Local futures still coalesce callers, database CAS leases still exclude other processes, and commit fencing/renewal still prevents expired owners from publishing. Blocking callers retain error/permission behavior, and their timeout now includes lease acquisition. TTLs, roster admission rules, and worker capacity are unchanged.

The unchanged-refresh proof is invalidated by all three storage write APIs, including callers that save without advancing the workspace version. Root-only writers that advance the version also invalidate it through the version comparison. The proof is checked again under the workspace lock. Cache changes, local edits, import-version changes, missing proofs, legacy layouts, and upgrades to root policy inputs retain the complete validation/import fallback. Existing local tasks, comments, approvals, and daily history are preserved.

Changed PostgreSQL snapshots still spend about 915 ms in the workspace write transaction, including about 802 ms in `storage.save`; that path loads/diffs the full state and maintains indexes. The unchanged transaction takes about 50 ms. Cache JSON serialization, full changed-state saves, and repeated native-parent/review/provenance processing remain possible next targets. The first refresh after rollout, and refreshes after local writes invalidate the proof, can still pay for full validation. No endpoint or frontend implementation was changed.

Changed implementation files: `backend/source_sync.py`, `backend/storage.py`, `backend/sources.py`, `backend/v4_sources.py`, and `backend/live_read/coordinator.py`. Added three regression test files and `scripts/benchmark_live_read_claim.py`.

Validation:

- Focused source/live/storage/daily/V4 suite: **865 passed, 8 skipped, 1 xfailed**. The skipped cases require an explicit isolated PostgreSQL URL; the xfail is the existing quote-deadline finding.
- New regression files with PostgreSQL enabled: **28 passed**, including nine PostgreSQL cases. Coverage includes local-state preservation, concurrent edits, cache races, all storage write APIs, upgraded root inputs, differential resolver decisions, duplicates, single-flight claims, claim timeout, and failed-claim retry.
- Final full backend suite: **5,071 passed, 32 skipped, 1 xfailed, 9 failed**, in 338.49 s. The nine failures exactly match the baseline failures listed below.
- All nine failures from the first full run also fail on unmodified `5c39bb0`, verified in an isolated baseline export.

The pre-existing failures are:

```text
test_home_executable_tasks.py::test_valid_current_proxy_stays_visible_on_historical_data_date
test_node_assignment_start_sop.py::test_start_agrees_with_the_evidence_overlay_and_mirrors_it_only_onto_rows_it_creates
test_node_item_progress.py::test_one_partial_item_starts_the_node_by_evidence_and_shows_the_percent
test_partial_writes.py::test_converted_action_stores_what_the_full_path_stores[daily_propose]
test_partial_writes.py::test_a_daily_mapping_is_proposed_and_approved_identically[unmatched]
test_partial_writes.py::test_a_daily_mapping_is_proposed_and_approved_identically[held by another case]
test_read_scopes.py::test_denied_sop_read_does_not_materialize_case_and_read_grants_work_without_writes
test_runtime.py::test_deployment_staging_includes_runtime_and_omits_credentials
test_ux_home_panels.py::test_production_evidence_moves_a_node_to_in_progress_on_the_home_panels_too
```

Run from the worktree root:

```sh
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B scripts/benchmark_source_sync.py --db sqlite --projects 420 --repeats 5
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B scripts/benchmark_live_read_claim.py --db sqlite --repeats 5
/Users/vc/Local/YXMEEGLE/.venv/bin/python -B -m pytest backend/test_source*.py backend/test_live_read*.py backend/test_storage*.py backend/test_daily*.py backend/test_v4*.py -q
```

For PostgreSQL benchmarks, pass a disposable local admin URL to `--db`; the scripts create/drop their own random database. For PostgreSQL regression tests, set `ACTION_AUDIT_TEST_POSTGRES_URL` to an isolated test database and run the three new test files. Each source regression uses a separate schema and removes it afterward. The existing `scripts/test_action_audit_postgres.py` can provision a private local cluster for those tests.

Raw synthetic measurements are in the adjacent `sources_{before,after}_{postgres,sqlite}.json` and `lease_{before,after}_{postgres,sqlite}.json` files. No database URLs, credentials, or customer records are included.
