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

Evidence overlay is deliberately limited to explicit no-upload confirmations (#59,60) and explicit file-output tasks (#1,15,16,17,19,20,30,43,52). Other rows retain existing unresolved evidence validation; this work does not claim to encode every business completion condition.
