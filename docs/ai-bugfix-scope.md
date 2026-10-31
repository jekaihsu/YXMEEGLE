# Case search and completion evidence

The reproduction uses the application factory, isolated real demo workspace, authenticated HTTP routes and the same cookies as the UI. It does not contact staging or Lark. Run commands from this worktree with `/tmp/ai-backend-venv/bin/python`.

## Search findings

`ProjectsList.tsx` reads `/api/projects?view=portfolio&page=1` and then all remaining snapshot pages. Its default classification includes all records. The old tool reads the unqualified `/api/projects?q=...` endpoint. Both read the same authenticated workspace, but their projections differ.

For both `u-control` and `u-manager`, the unfiltered baseline returns seven cases in both projections. A keyword `進行中` returns zero. The legacy `status=in_progress` endpoint returns seven including p6. The portfolio exposes the refreshed p6 status `engineering_complete`, leaving six genuinely matching `in_progress` cases. The shared frontend case dictionary is `stageModel.ts` CASE_STATUS, also reflected in `workflowLabels.ts`. The tool schema documents those exact values and Chinese labels.

Portfolio applies lifecycle policy and collapses duplicate case codes. The regression modifies existing demo records to include a duplicate, a normal intake, a removed intake and a local planning case. For both member and manager, the legacy endpoint returns six records while portfolio and the repaired tool return four identical IDs. The normal intake remains. The removed intake, duplicate and local planning case are excluded. `overview` defaults to `tab=formal`, but that endpoint is not the current 案件總覽 request.

The repaired tool uses the full portfolio snapshot in one read, filters and sorts by due date then ID, returns eight rows, the full matching total and matching per-status counts. When shell mode is off, the UI reads the workspace and the tool follows it. `owner=me` resolves only the authenticated session ID and means PM ownership. It requires one additional session read. Overdue means a known workspace deadline before today, excluding completed and engineering-complete cases. Unknown approved deadlines, task-level lateness and arbitrary owners are not supported.

## Progress findings

The p1 demo detail route exposes four completed nodes and nine completed tasks out of 21. Its completed nodes are 報價, PM 派工, 確認單 and 外業. The original project context omits these nodes and their tasks. Its production progress can say `waiting` because confirmation evidence is absent, even when local workflow work is complete. This is the reproduced mechanism behind the misleading answer. No live model response was claimed.

`project_progress.py` stages use `done` for completion with a separate basis, `active` for an activity signal, `waiting` for unmet prerequisites and `unknown` for unavailable evidence. `basis=rule` is an inference, `source` means source evidence and `none` means no evidential basis. `verified` in `case_detail.header.current_stage` verifies the current stage identity. It does not prove that stage is complete.

The shared AI summary preserves every workflow node, Chinese status, completion counts and source basis. In Lark-enabled mode, `/node-assignments` provides `derived_status` and task done/total counts. These override the matching workflow presentation while the original workflow evidence remains available. `progress.production[*].progress` is a separate production-work-item measure, retained separately with its own basis. `/sop-tasks` provides SOP case and node counts, also retained separately because linked execution and checklist tasks can overlap. Overall workflow/Lark counts explicitly identify their basis. They are not an asserted union with SOP counts.

Both project context and global `case_progress` use this summary. The global display includes a table of all workflow nodes in addition to the existing stage chart. Closed tasks remain absent from `unfinished_tasks`. Unavailable sources remain explicit. The existing project context cap stays at 12,000 characters, and global tool results retain their 6,000-character cap with nested node truncation supported.

## Verification

The first commit contains failing regressions before the fix. Their original failures are `AssertionError: {"error": "工具參數錯誤"}` and `KeyError: 'nodes'`. The same assertions now pass.

The final focused run has 82 passing tests. Eight scope regressions cover status-only search, invalid status and owner, member/manager UI parity, composed filters, lifecycle visibility, completed and zero-completion workflow contexts, global display, socket streaming and a SOP task created and completed through real demo routes. Existing real-route context truncation and source-unavailable tests also pass.

Three dedicated real-socket tests pass using curl against uvicorn, covering project chat, forbidden scope, status-only search, global tools and feedback. Providers are deterministic test doubles. This proves route, schema, SSE and projection behavior, not live model reasoning.

Runtime captures are in `ai-bugfix-runtime-before.txt` and `ai-bugfix-runtime-after.txt`. Regenerate the after capture with `PYTHONPATH=. /tmp/ai-backend-venv/bin/python docs/ai-bugfix-evidence.py`. Socket output is in `ai-socket-transcript.txt`.

The entire backend run is recorded in `ai-backend-suite.txt`. `python -m pytest backend -q` finished with 5676 passed, 39 skipped, 1 xfailed and 4 warnings in 606.22 seconds. The final focused run includes two additional regressions added while the full run was in flight.

Live Lark authorization, remote node assignments, production PostgreSQL and staging model behavior were not exercised. No independent reviewer was spawned because this task is the implementation sub-agent. No PR, push or deployment was requested.

Fix Root Causes changed the target from keyword matching to the UI's actual projection. Model the Domain changed scattered completion assumptions into a shared source-labelled summary and a status dictionary. Deslop review kept the patch within AI code, its tests and evidence documents, with no new inline comments.
