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

Search returns `total` for the keyword, owner and overdue filtered population before status filtering. `status_counts` is computed on that population and includes `other`, so its values sum to `total`. `matched_total` counts the status-filtered population. Offset is zero-based, with eight cases per page and `next_offset` for the next page. The 19-case real workspace regression checks pages of 8, 8 and 3 without duplicates and proves an empty selected status does not erase the other status counts.

A search makes one portfolio snapshot read per call when workspace shell is enabled. The route caches snapshots per viewer and authority context. Owner `me` adds a session lookup. With shell disabled, it reads the heavier complete workspace projection. Paging repeats the snapshot read and then slices in memory. No per-case detail requests are introduced.

## UI parity

`project_state` contains the node-order and status-label tables used to reproduce `caseRow` and `caseAttention`. Stored execution status is retained as source evidence but no longer drives the status filter. Only execution status completed closes the UI overdue flag. Engineering-complete cases can still be overdue.

`test_portfolio_frontend_parity` reads a real demo portfolio and workspace, adds producer-shaped node overlays, then bundles the actual `frontend/src/projectsListModel.ts` with esbuild and calls `caseRow` and `caseAttention` in Node. Python and TypeScript receive identical JSON. The test checks each case's state and overdue flag. It covers pending, active, review, paused, completed, skipped, unknown, absent nodes and a timezone deadline. The demo workspace contains seven UI-derived in-progress cases, compared with six stored in-progress statuses.

The frontend dependencies were absent. This run installs only esbuild under the allowed backend directory. Reproduce from this worktree with:

```sh
npm install --prefix "$PWD/backend/ai/.parity" --no-save --package-lock=false --cache "$PWD/backend/ai/.parity/cache" esbuild@0.28.2
/tmp/ai-backend-venv/bin/python -m pytest backend/test_ai_round7.py -q
```

The parity test prefers frontend/node_modules when available. `PARITY_ESBUILD` can name an alternative module path. Missing Node or esbuild fails the test explicitly.

Prompt regressions require question-specific attendance headlines, unevaluated day wording, no exposed internal field names, no absence terminology, no operational narration and one source-time mention. These are rule-text checks. No live model behavior or live provider schema acceptance is claimed.
