# Project chat backend fix verification

Implementation commit is `d9fec70`, based on `2f6294a`. No push was performed.

1. Context now includes up to 15 unfinished workflow tasks and the header responsible person. History is newest first, capped at 20, with known Traditional Chinese action labels, count and latest time. Object-only trimming preserves state strings and the 12,000-character JSON limit. Tests include `test_unfinished_tasks_capped_from_real_workflow`, `test_history_newest_twenty_from_real_events` and `test_compact_preserves_state_strings_and_newest_real_history`.
2. Unknown states and no_authorized reasons receive an explicit unavailable marker with a Traditional Chinese explanation. `test_real_unknown_history_and_blockers_are_unavailable` uses the actual empty-history and unknown-blocker route responses.
3. Context JSON is delimited and angle brackets are escaped. All rules follow the block. `test_hostile_real_case_is_delimited_before_all_rules` includes both a hostile case name and unfinished task title, and checks placement only.
4. Request-derived timestamps are removed. `test_prompt_byte_stable_across_uncached_real_reads` varies the real case-detail builder's request time and compares prompt bytes. Source timestamps remain. The cache contract documents 90-second TTL reuse and unchanged-case reuse.
5. Real 403 and 404 case routes return the same forbidden body. Real 500 routes, timeout and unexpected exceptions return retryable 503 ai_upstream and a warning with hashed project id, status, exception class and elapsed milliseconds. `test_context_route_failures` verifies no provider call and no ledger row.
6. No frontend files or unrelated backend files changed.

`/tmp/ai-backend-venv/bin/python -m pytest backend -q` completed with 5667 passed, 39 skipped, 1 xfailed and 4 pre-existing unknown perf-marker warnings. See [full output](ai-pcfix1-backend-suite.txt). The independently added cache regression was also run in the final focused project suite, which passed all 35 tests. See [project output](ai-pcfix1-project-tests.txt).

`backend/test_ai_api.py::test_real_socket_stream_is_not_buffered` passed. See [socket output](ai-pcfix1-socket-test.txt). The project curl socket test passed with HTTP 200 SSE and HTTP 403 for an unknown project. Its fake provider prints the received system prompt, with context trimmed to 1500 characters. See [curl transcript](ai-pcfix1-curl-transcript.txt).

[Baseline failures](ai-pcfix1-baseline-failures.txt) record six projection/prompt regressions against the original modules and three upstream-error regressions against baseline 2f6294a. Historical modules were loaded in a separate Python process; the worktree source stayed intact.

The real workflow route supplies no due_date or assignee_name, and header blockers contain no task/node attribution. Those values cannot be recovered within the allowed AI-only scope. The projection retains those fields if supplied, orders explicit overdue/blocked statuses before other tasks and then available due dates, and marks missing blocker attribution unavailable. It never invents missing identities or dates.

Model the Domain centralized unavailable-state normalization. Prove It Works required real routes, sockets and the provider's received prompt as evidence.
