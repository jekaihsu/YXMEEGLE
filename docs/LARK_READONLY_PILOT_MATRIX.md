# Read-only pilot draft field matrix

Status: proposed mappings only. No live runtime read is claimed. Base is ava-apple/yxs-lark-authoritative-operations at c7ed20d7b93f2d077cb10c563abf6a68f2ee18cb. The candidate is on ava-apple/yxs-54-lark-readonly-pilot; exact tested head is recorded in the canonical Paperclip receipt. The owner conditionally approved the exact auth-path candidate for independent review. Every new row uses `LarkPilotPanel` on `/sources`, runtime identity category `application` intended but unproven, classification `proposed`, source badge `未對映` until runtime proof; synthetic browser fixtures are not live evidence.

Base: H7W6b0PFWaVF1BsgqXJj3pQ9pXb. Evidence file is `/Users/vc/Documents/Codex/2026-10-11/task-2/schema-fields-live.csv`; row numbers below include the header. It contains schema metadata only, read locally without a Lark call.

| UI field identifier | Table/name/ID | Schema field/type | Null/omitted behavior | Permission needed | Evidence | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| fldgZDflpb | 工程確認單/tblmSQrcCs9vPQZx | 工程確認單編號/text | 明確空值 / 未回傳 | bitable:app:readonly + application Base/table read grant | schema row 77; E07 | Raw source value, no business inference |
| flddfFq9zI | 工程確認單/tblmSQrcCs9vPQZx | 外業工作單/link | Same; empty list remains present | Same | row 72; E11 | Sorted stable linked IDs, unknown cardinality stays a list |
| fldjfxJIMb | 外業工作單/tbl5zPLS0ExWNEty | 工作單號/auto_number | Same | Same | row 352; E07 | No local case replacement |
| fldlqnGoTh | 外業工作單/tbl5zPLS0ExWNEty | 組長人員-津貼來源V2/link | Same | Same | row 449; E11 | Links to Base people records, no name matching |
| fldvSpUqa9 | 外業工作單/tbl5zPLS0ExWNEty | 組員人員-津貼來源V2/link | Same | Same | row 336; E11 | Shared 10-person cap |
| fldJs4RTUm | 外業工作單/tbl5zPLS0ExWNEty | 組長帳號-津貼自動化/user | Same | Same | row 321; E10 | Raw identity category, no role inference |
| fldnCPisZ5 | 外業工作單/tbl5zPLS0ExWNEty | 組員帳號-津貼自動化/user | Same | Same | row 325; E10 | No contact fallback or extra contact scope |
| fldCTLvsWG | 人員名單/tblfaCO2xPUNptQH | Lark帳號/user | Same | Same | row 188; E10 | Stable ID projection only |

Each record carries fetched_at in UTC, a 60-second TTL and explicit freshness; panel displays Asia/Taipei HH:MM:SS and age. Partial/denied/unmapped table states never render zero or deleted records. Live-fresh, stale, cached, mock and local badges have separate rendering tests. No cross-request retained cache is implemented; a supplied cached payload always renders stale. A reader failure preserves only records already read in that same call, marked partial. No database/coordinator handle enters the module.

内業工作單/tblrCo8KeZiuJUNh has no case link in the selected schema field set. Its fldMEnE6IM mapping remains unmapped and unqueried; no inferred case or schedule relationship is added. Owner/Lead resolve any future scope change. Existing Dashboard/Projects use local workspace projections; ops-sync is mock. Those pages and labels remain unchanged.

Runtime preflight, actual sample counts and minimum denied endpoint permission are NOT RUN pending exact-head independent Review PASS. Integrated browser before/after uses the exact base and candidate application with synthetic identity/data on own ports. No authorized private live preview is recorded. The synthetic suite exercises requested 3/10/10 and overreturned 40-record fixtures, no pagination, denied work table, timeout and fixed error copy. It does not establish application access.
