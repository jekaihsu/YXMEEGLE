# Meegle V1 backend audit

Baseline: `687a98b0921cbf6296b954bfd757726d974979ed`, intended branch and clean worktree. No diff from pinned review. Companion PRD absent; supplied v0.2 brief and task instructions are the specification.

- Already fixed: system managers pass SOP capabilities (25d1861); ordinary active users can be assigned; immutable published templates/origins/events; transactional workspace/case locks; revision conflicts; source-derived suggestions and close-node evidence.
- Present gaps: completion policy absent; all imports have unresolved evidence; proof suggestions and close-node can complete without a review policy; no submission revisions or review queue. No separate bulk-complete API; bulk suggestion acceptance is the bulk completion path.
- Present projections: SOP overview and quote register count local tasks. My Work and company dashboard use the legacy workspace task engine; add separate SOP counters without changing legacy totals or inventing shared identities (V1-04 remains separate).
- Blocked by configuration / out of scope: production writes, formal approval/publication integration, live Lark, PostgreSQL acceptance and A01–A55 (missing PRD). No flags enabled or remote writes attempted.
- Baseline freshly run: `python -m pytest backend/test_sop_import*.py backend/test_sop_suggestions.py -q`: **72 passed**, 4.23s.

## Classification

Policy v1 uses explicit source review/formal language, independently of evidence. No global importance/priority column exists. Formal source markers: #7 (簽呈核准), #54 (撥款核准) -> formal_external. Explicit reviewer/countersign markers: #8,16,19,24,25,29,32,33,34,35,37,41,51,56 -> reviewer_required. Other rows default executor_self; excluded/reference dispositions remain excluded/reference. #42 is template-definition review, not task review; remains unselected/unresolved.

Critical unresolved source semantics: #18 extension approval authority, #22 whether three-party re-sign is required, #33 whether engineer certification needs a separate formal process, #42 meaning/owner/merge, #54 payment approver. Defaults on #18/#22 do not authorize external approval or publication. Existing unresolved evidence guards remain; these rows are not production-ready. Human decision/notification text alone is not an importance marker. Do not interpret source proof as review approval. The local checker/PM/manager review is not a replacement for multi-seat formal Lark approval.

Evidence overlay is deliberately limited to explicit no-upload confirmations (#24,32,56,59,60) and explicit file-output tasks (#20,43,52). Other rows retain existing unresolved evidence validation; this work does not claim to encode every business completion condition.

## Delivered V1-01–03

New imports freeze policy v1 independently of evidence. Old origins are unchanged and resolve policy from their own row snapshot. Routine executor completion validates current typed uploaded files when required and retries do not duplicate events. Important submission/approve/return uses the existing transactional locks and append-only event table: immutable numbered evidence/note/assignment snapshots, exact-revision approval, reasoned return, current reviewer authority and permission-scoped queue/history. Content/assignment edits require resubmission; an external PM change also permits a fresh executor submission. System managers retain all existing SOP capability authority but cannot bypass completion policy. Reviewed terminal tasks remain immutable. No new roles or capabilities.

Project progress, My Work and dashboard expose separate `sop_counts`; legacy totals are unchanged. The real-app demonstration verifies an ordinary grantless assignee completes #59 and all three counts change to done=1. Important #24 supports note-only submission and #19 supports a typed file submission. Review submission leaves done=0. Concurrent approval retries produce one decision event.

No schema migration: new policy data uses immutable origin JSON; submissions/replay receipts use existing append-only TaskEvent JSON; task-local JSON stores only the current review pointer/status. All existing backup tables remain sufficient. No production configuration was read or changed, and no outbound write was made. `SOP_TASK_WRITES_ENABLED`, `LOCAL_CASE_CREATION_ENABLED`, quote/dispatch publication and remote write gates were not enabled (synthetic tests explicitly enable isolated local SOP writes).

## Fresh verification

Every command used `/Users/vc/Local/YXMEEGLE/.venv/bin/python` (3.12), from this worktree.

- Baseline: `-m pytest backend/test_sop_import*.py backend/test_sop_suggestions.py -q`: **72 passed**, 4.23s.
- Final targeted: `-m pytest backend/test_sop*.py backend/test_my_work.py backend/test_company_dashboard.py backend/test_project_progress.py backend/test_p2_int_routes.py -q`: **551 passed**, 12.72s. Covers all SOP tests (the package has no separate test directory), real app SOP routes, progress/My Work/dashboard, policy bypasses, typed/stale files, retry/concurrent approval, return/resubmit, assignment/PM changes, source-grant revocation, history immutability and queue scoping.
- Full smoke: `-m pytest backend -x -q`: **904 passed, 7 skipped, 1 failed**, 56.74s. Stops at `test_home_executable_tasks.py::test_valid_current_proxy_stays_visible_on_historical_data_date` (`assigned_to_viewer` false for a historical delegation ending October 20). Same failure reproduced with **1 failed** against an isolated `git archive 687a98b backend` copy inside this worktree; temporary copy removed. This is pre-existing, not reported as a passing full suite.
- `git diff --check`: passed. No production/PostgreSQL/remote acceptance or latency benchmark claimed. Existing Starlette deprecation and unregistered perf-mark warnings remain.

During implementation, prior suggestion/close-node expectations that assumed important work could directly complete were changed to exercise routine rows; dedicated negative tests now cover protected rows and whole-request rollback.

## Risks and rollback

Critical source ambiguities above remain unresolved and must be reviewed before production rollout. Evidence metadata intentionally covers only the explicit rows listed above; other source business obligations remain unresolved. The existing uploader authorization is unchanged: an SOP-only assignee may need an already authorized uploader to supply a case output file. File validation checks the existing uploader's recorded hash/version metadata, not a fresh disk rehash. V1-04 row/queue aggregation and panel-query projections are deferred. Local SQLite acceptance is complete; PostgreSQL and A01–A55 are not claimed.

Disable `SOP_TASK_WRITES_ENABLED` to halt writes and retain all origin/event JSON and SOP tables. Revert code only with writes disabled; older completion code must not be re-enabled against protected tasks. No destructive migration or data deletion is needed. API payloads and error codes are in `backend/sop_import/README.md`.
