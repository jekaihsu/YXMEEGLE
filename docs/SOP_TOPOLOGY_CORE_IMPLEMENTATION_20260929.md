# SOP topology batches 1–2: core implementation, integration pending

Implemented `backend/sop_topology.py`; this is a pure compiler/readiness library,
not a deployed or integrated execution engine. No company template was published,
no existing case migrated, and no Lark or salary/capability source was written.

## Implemented and verified

- `index_contracts(catalog)` indexes template ID + version + node key + task key.
  Same display names remain separate; duplicate or invalid identities fail.
- `compile_condition(source, schema)` supports typed scalar `Eq`/`Ne`, structured
  `AND`/`OR`, and explicit boolean literals. Radio options require an explicitly
  provided metadata schema. Missing fields, unknown options, unsupported modes,
  operators, formulas and schema conflicts produce `Evaluation(None, reasons)`.
  BQL strings are never executed. Unknown operands remain unknown even when
  another operand would normally decide a boolean expression.
- `Topology(fixture)` uses actual edges only, rejects cycles/unknown endpoints
  and unsupported start modes, and retains disabled states 52/58 for provenance.
- `readiness(applicability, completed)` returns per-node ready/blocked/completed/
  not_applicable/disabled plus exact pending source keys. False applicability
  excludes a branch without adding a completion; its upstream dependencies still
  block. Missing or incorrectly typed applicability is unknown. Existing
  completion cannot hide unresolved upstream applicability.
- Source leaf names never create reverse edges or imply project closure.
  Source auto/single-user flags have no authorization effect.

Validation: `python -m pytest backend/test_sop_topology.py
backend/test_sop_contracts.py backend/test_sop_contract_integration.py -q`:
**57 passed** (28 new semantic tests). The tests use the preserved full
334662/v137 fixture: 62 nodes, 71 edges; 52 distinct source task identities.
They cover unknown subcontract, explicit no-subcontract convergence,
upstream blockers through excluded nodes, independent 75/76/77 readiness,
disabled 52/58 and no inferred state_65 return edge.

## Required runtime integration

1. Resolve the project's pinned template/version and verified field metadata.
   Feed source IDs/typed values, never translated names, to the compiler. Do not
   infer an allowed radio-option universe solely from expressions in the fixture.
2. Build node applicability from approved, attributed, versioned decisions.
   The core boolean mapping is an internal trust boundary, not a client payload.
   Source visibility output must not authorize skip, completion or exclusion.
   Explicit no-subcontract decisions must cover all approved excluded nodes
   (including state_35); the core never guesses descendants from their names.
3. Map actual node/task evidence to source keys in the pinned execution round.
   Supply real completion keys; not_applicable and disabled are never completion.
   Apply readiness as an additional activation/completion gate alongside current
   permission, deliverable and native approval checks. A readiness result alone
   cannot approve a financial action or close a project.
4. Add endpoint/state-transition integration tests proving clients cannot submit
   fabricated applicability/completion; exercise persistence/reload and pinned
   revisions. Only then report batches 1–2 as runtime-integrated.

The graph can report readiness without side effects today. Issuance handoff,
shared technical work identities, approved revision rounds, project closure,
versioned cutover baseline, and production publishing remain outside this core.

## Follow-up authority audit: no new approval route implemented

Only the three new files named above were written by this workstream. No
`sop_scope_propose` or `sop_scope_confirm` route/module was added, and this
workstream did not edit operations.py, sop_contracts.py or workflow_rules.py.
The suggested local two-seat confirmation route was stopped before any code
was written: source responsibility wording does not authorize a new approval
policy. There is no UI entry, and this core must not be described as a complete
usable production flow.

Exact existing decision evidence:

- `SOP_MAPPING_DECISIONS.md`, fifth batch, state_29:
  「PM 彙整需求，對應組主管確認；保存是否下包及下包資訊」.
- Same batch, state_35:
  「行政收件整理，PM／對應組主管確認工作範圍；金額核准權仍依設定」.
- Same batch:
  「無下包案件的相關工作標示不適用，不偽造完成或刪除來源 SOP」.
- `SOP_IMPLEMENTATION_CROSSWALK_20260929.md`, implementation boundary 2:
  「核准仍引用既有原生審批，不另外做本地『通過』假成功」.

These establish work responsibilities and the distinction between exclusion
and completion. They do **not** establish a new PM + supervisor AND approval,
two distinct approver identities, a new native approval type, or authority to
treat a PM-entered boolean as a final exclusion decision.

Document precedence also matters: `APPROVED_PRODUCTION_PLAN_20260928.md` says
「普通成果在工作台依 SOP 提交／確認／退回；重大財務確認、設計變更、展延、跳過節點才走 Lark 原生審批。舊文件的『所有本地確認遷移 Lark』已被取代。」
The 9/27 blanket migration inventory therefore cannot establish today's scope
policy. The current instruction explicitly disallows creating a new local
two-seat approval route; no such route was implemented.

Existing technical inputs, and their limits:

- `project.pm_id` and node supervisor assignment identify existing responsible
  people, but assignment alone is not an approval receipt or scope decision.
- `review_cycles` attest a particular node delivery/review; they do not encode
  a subcontract applicability decision.
- `payment.technical_approved_by` attests a payment-related delivery check;
  it cannot authorize the subcontract branch.
- Native change/extension/node-skip/finance receipts have their own immutable
  types and scope hashes. They must not be silently relabeled as subcontract
  scope approval.
- Existing `sop_applicability` dictionaries check attribution/version/reason,
  but currently have no proven authorized input flow for this new branch.

The unresolved integration decision is the specific authoritative record and
fields that establish subcontract applicability under the already-approved
responsibilities. If a new approval type or approval rule is necessary, that
requires an explicit decision; ordinary data structures, hash keys, persistence
and UI implementation do not. Until then, conditional defaults stay disabled,
unknown remains unknown, and a future proposal UI may save only a draft without
activating tasks, excluding branches or changing the published SOP.
