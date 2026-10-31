# AI review round 7

This round changes backend AI code and tests only. The UI remains the authority for case state and overdue behavior.

## Evidence and overlap rules

The real attendance producer evaluates check-in and check-out independently. The regression fixture sends a late check-in and a leave check-out through `fetch_week` and `/api/people/attendance`. Its label is `遲到、請假`. Both evidence groups retain the person. Leave, trip, out and exemption explanations also overlap independently. A person enters `unaccounted` only with no attendance record and no explanation on an evaluated day. It is disjoint from all other groups. Complete daily counts equal list lengths before truncation. Weekly person-days and merged display labels retain overlaps.

`test_explained_independent_punches` originally failed with late count 0. It now checks both counts, disjointness, weekly person-days and display labels. `test_explanation_preserves_each_independent_evidence` also covers early leave, missing punch and supplemented records.

Completion summaries retain workflow node completion in each assignment row's `workflow_evidence`. `completion_conflict` lists workflow, assignment and available SOP counts in Traditional Chinese when workflow and assignment evidence disagree. The real demo workflow has four completed nodes and nine completed tasks. Assignment-shaped rows with `未開始` and 0/0 tasks reproduce the loss of evidence. The regression originally failed because `completed` was missing from retained evidence.

`skipped_nodes` counts 略過, skipped, not_applicable and approved_skipped separately. These nodes are excluded from the denominator. The parameterized regression uses real workflow route rows and proves eight completed plus one skipped means 8/8, skipped 1.

The zero-completion sentence requires zero done counts in every retained workflow, assignment and SOP source. Missing workflow counts suppress that sentence. An unavailable SOP source also removes it. `test_sop_completion_prevents_zero_statement` creates and completes a real SOP task while workflow counts remain zero.

## Tool contract

Every tool property is required and non-nullable. The exact schemas are generated in `ai-r7-schemas.json`. Both SDK request tests walk every transmitted schema. Only type, properties, required, additionalProperties, enum, description and items are accepted. Type must be a single string, object additionalProperties must be false and enum cannot contain null. The previous schemas failed these adapter request tests.

`search_cases` uses empty query, status `all`, owner `anyone`, overdue false and offset 0 as defaults supplied by the caller. The status enum includes the six UI states and their canonical English keys. `attendance_today` uses empty date for today's Taipei date and current week. Types and enums are validated from each property's schema. String length and nonnegative integer checks report the offending field. Overlong query originally produced the misleading status error.

Search returns `population_total` for the keyword, owner and overdue filtered population before status filtering. `status_counts` is computed on that population and includes `other`, so its values sum to `population_total`. `matched_total` counts the status-filtered population. Offset is zero-based, with eight cases per page and `next_offset` for the next page. The 19-case real workspace regression checks pages of 8, 8 and 3 without duplicates and proves an empty selected status does not erase the other status counts.

A search makes one portfolio snapshot read per call when workspace shell is enabled. The route caches snapshots per viewer and authority context. Owner `me` adds a session lookup. With shell disabled, it reads the heavier complete workspace projection. Paging repeats the snapshot read and then slices in memory. No per-case detail requests are introduced.

## UI parity

`project_state` contains the node-order and status-label tables used to reproduce `caseRow` and `caseAttention`. Stored execution status no longer drives the status filter and is omitted from model-visible search rows. Only execution status completed closes the UI overdue flag. Engineering-complete cases can still be overdue.

`test_portfolio_frontend_parity` reads a real demo portfolio and workspace, adds producer-shaped node overlays, then bundles the actual `frontend/src/projectsListModel.ts` with esbuild and calls `caseRow` and `caseAttention` in Node. Python and TypeScript receive identical JSON. The test checks each case's state and overdue flag. It covers pending, active, review, paused, completed, skipped, unknown, absent nodes and a timezone deadline. The demo workspace contains seven UI-derived in-progress cases, compared with six stored in-progress statuses.

The parity test requires frontend dependencies. Run `npm ci` in `frontend/` before running `backend/test_ai_round7.py::test_portfolio_frontend_parity`. It locates esbuild in `frontend/node_modules` and skips with that explicit instruction when esbuild is absent. It does not depend on a gitignored backend installation. The fixture also covers mixed node order, an unknown middle node, missing keys, duplicate keys and a task deadline without `overdue_tasks`.

Prompt regressions require question-specific attendance headlines, unevaluated day wording, no exposed internal field names, no absence terminology, no operational narration and one source-time mention. These are rule-text checks. No live model behavior or live provider schema acceptance is claimed.

## Final verification

The final `python -m pytest backend -q` run passes with 5710 passed, 39 skipped and 1 xfailed in 513.40 seconds. Four warnings concern the existing unregistered `pytest.mark.perf`. The final focused `backend/test_ai_*.py` run passes 187 tests. The independent real-socket run passes all three selected tests, including incremental delivery, project streaming and the status question. `git diff --check` passes.

A replay of the original `6cbac90` tool module against real demo routes fails the UI population assertion with six stored in-progress cases instead of seven UI-derived cases. It also rejects the required offset contract. Initial regressions captured lost attendance labels, overwritten completion evidence, skipped denominators, misleading field errors, missing prompt rules and nullable schemas. The corrected 19-case paging fixture verifies three complete pages without duplicates.

All changes are local commits. No push or frontend edit was made. No live Anthropic or OpenAI request was made. Adapter tests inspect the serialized SDK requests and parse synthetic provider streams. The Model the Domain principle shaped the shared node-order and status-label tables in `project_state`.

## Final review corrections

`population_total` counts cases after keyword, owner and overdue filters but before the status filter. `matched_total` counts the requested status. Prompts require `matched_total` or `status_counts` for filtered questions. The real demo regression adds completed and pending cases, so the counts differ. Last pages have no truncation flag unless size trimming removed rows. After trimming, `next_offset` advances by the number actually returned.

Completion conflict means node completion differs between sources, or the workflow shows completed work for a node whose assignment source explicitly shows none. Different task totals alone do not conflict. Both task populations remain in the payload. The conflict note contains aggregate counts, while row evidence retains node figures. Both prompts require source-specific figures on conflict, exclude skipped nodes from outstanding work and prohibit zero-work claims when any source shows completion. A 25-node real-route fixture checks row trimming under the 6000-character tool and 12000-character project limits.

Weekly displays omit unevaluated dates from chart points and show their dates with 不評估 in the note and table cells. The numeric chart contract cannot represent null points. Display notes use 查詢時間 rather than an internal timestamp field, and node evidence cells use Chinese source names. `test_display_chinese_and_unevaluated_days` checks visible text for internal identifiers.

`project_state` ignores malformed node and task rows, defaults missing states to 待核對 and tolerates invalid date and overdue values. Schema tests reject null query, status and date, plus boolean and string offsets. No frontend or CI-script edits are included.

### Final review verification

`/tmp/ai-backend-venv/bin/python -m pytest backend -q` passes with 5723 passed, 40 skipped, 1 xfailed and 4 warnings. The warnings are the existing unregistered `pytest.mark.perf`. The focused `backend/test_ai_*.py` run passes with 200 passed and 1 skipped. The standard parity test skips because frontend esbuild is absent, with the instruction to run `npm ci` in `frontend/`.

A supplemental local probe installs esbuild 0.28.2 under `backend/ai/.parity` and runs the same expanded parity fixture with only the dependency guard removed and the JavaScript import redirected to that backend installation. It passes against the actual TypeScript implementation. That run exposed and corrected a fixture error, selecting a real workspace project with tasks for the task-deadline case. The normal test still requires frontend dependencies and skips even with backend esbuild installed.

The independent real-socket run passes all three checks for incremental delivery, project streaming with forbidden-case handling, and status-question tool displays. The 19-case fixture prints its final search result with `population_total:19`, `matched_total:19`, `offset:16`, `next_offset:null`, three cases, derived state and overdue flags, and no raw stored status or truncation flag. `git diff --check` passes. All commits remain local, without a push or frontend changes.
