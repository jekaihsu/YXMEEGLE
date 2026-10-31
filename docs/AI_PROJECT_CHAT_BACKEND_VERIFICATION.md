# Project chat backend verification

Verified implementation commit `6176ac0` on `t3/ai-pc-backend`. Commands ran in `/Users/vc/Local/YXMEEGLE-worktrees/ai-pc-backend` with `/tmp/ai-backend-venv/bin/python`.

- `python -m pytest backend -q` passed with 5,631 passed, 39 skipped, 1 xfailed in 562.48 seconds. Four existing warnings concern unregistered `perf` markers.
- `python -m pytest backend/test_ai_*.py -q` passed with 108 passed.
- The final dedicated socket and curl run passed with 2 passed. Text deltas arrived at 0.006 and 0.809 seconds.
- Prompt and empty-tools tests failed before implementation. Project-route tests reproduced HTTP 422 for `project_id`. Scope migration and usage-filter tests also failed first. The available-history test reproduced the missing history projection before its fix.

| Change | Proof |
| --- | --- |
| Direct answers with correctness caveats | `test_prompt_has_no_banned_narration`, existing caveat tests |
| Authorized project context, one model call, no tools, scope ledger, feedback | `test_project_real_routes_single_call_and_ledger`, both model hooks |
| Hidden, unknown and unreadable projects denied without model calls or rows | `test_project_hidden_and_unknown_are_identical_without_ledger`, `test_unreadable_base_denied_without_model_or_ledger` |
| Cache expiry, isolation, coalescing, capacity and cancellation | `test_context_cache_real_routes_ttl_users_workspaces_and_coalescing`, `test_context_shared_build_survives_waiter_cancellation` |
| Safe amounts projection, unavailable markers, JSON truncation and history | `test_context_unavailable_parts_and_amount_projection`, `test_context_node_unavailable_from_real_503_route`, `test_context_truncation_real_detail_keeps_priority_and_valid_json`, history tests |
| Scope filtering and additive migration | `test_usage_scope_filter_all_aggregates`, scope migration tests for SQLite preservation, repeat no-op and PostgreSQL DDL compilation |
| SDK requests omit empty tools and finish streaming | `test_empty_tools_omitted_and_stream_completes`, both SDK mock transports |

The following curl output comes from the real app over a local socket with the fake provider. Authentication cookies are not printed. The unknown-project response is identical to the hidden-project response tested above.

```text
curl POST /api/ai/chat {"model": "claude", "conversation_id": "c-123", "messages": [{"role": "user", "content": "查詢公司資料"}], "project_id": "p1"}
data: {"type": "start", "usage_id": "eb207206-32a9-4ba4-92d9-397ff6f38a63", "conversation_id": "c-123", "provider": "claude", "scope": "project"}
data: {"type": "text", "delta": "截至目前，"}
data: {"type": "text", "delta": "查詢完成"}
data: {"type": "done", "usage": {"input_tokens": 60, "output_tokens": 40}}
HTTP 200
curl POST /api/ai/chat {"model": "claude", "conversation_id": "c-123", "messages": [{"role": "user", "content": "查詢公司資料"}], "project_id": "unknown"}
{"code":"ai_forbidden","message":"找不到或沒有權限查看這個案件"}
HTTP 403
```

No requested backend work remains. No push was made. PostgreSQL verification compiles the migration DDL; SQLite tests execute it against the full previous table shape.
