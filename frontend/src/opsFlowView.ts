// Wording and pure helpers for the synthetic local vertical flow. All people, eligibility and dates here are mock fixtures:
// nothing is bound to a Lark field, so every mapping is labelled unconfirmed and no live-sync claim is made.
import type {OpsState} from './opsSyncView';
export type Person={person_id:string;name:string;active:boolean;eligibility:'eligible'|'ineligible'|'unknown';person_key:string};
export type Proposal={proposal_id:string;state:string;reason?:string|null;expected:string|null;expected_revision:number;intended:string|null;actor:string;receipt_id?:string|null;mock_receipt:boolean};
export type Entity={entity_id:string;kind:'case'|'node';project_id:string;node_id?:string|null;seat_field:string;seat:{person_id:string|null;name:string|null;revision:number;state:string;open_conflicts:string[]};
 deadline:{original:string|null;effective:{value:string|null;revision:number};proposals:Proposal[]}};
export type Denial={suspended:{reason:string;since:string;command_id:string}[];held_commands:string[]};
export const MAPPING_BADGE='未確認／模擬';
export const MOCK_DECISION_NOTE='以下核准／駁回／過期為本機模擬（mock）：只會經由已綁定的核准消耗流程，不會產生真實 Lark 核准。';
export const ELIGIBILITY:Record<Person['eligibility'],string>={eligible:'具資格（模擬資料）',ineligible:'資格已撤銷（模擬資料）',unknown:'無資格紀錄（模擬資料）'};
export const personLabel=(p:Person)=>`${p.name}（${p.person_id}）— ${p.active?ELIGIBILITY[p.eligibility]:'已停用帳號（模擬資料）'}`;
export const SEAT_LABEL:Record<string,string>={case:'案件 PM（資格為模擬規則，不由案件 PM／案件負責人標籤推得）',node:'節點負責人（對應關係未確認，不由案件 PM 推斷）'};
export const DEADLINE_LABEL='模擬任務期限（非合約結束日；合約結束日不等於任務期限）';
export const PROPOSAL_STATE:Record<string,string>={waiting_approval:'提案：等待核准（尚未生效）',confirmed:'已核准（模擬收據已消耗）',failed:'已結案：未生效',conflict:'衝突：基準已變動，未生效',denied:'被拒：未生效'};
export const DECISION_RESULT:Record<string,string>={approved:'模擬核准',rejected:'模擬駁回',stale:'模擬過期核准'};
export const MOCK_OUTCOME_LABEL:Record<string,string>={normal:'正常',timeout_after_commit:'寫入後逾時（結果未確認）',permission_lost:'寫入權限被拒（全域暫停派送）',concurrent_edit:'他人同時編輯（衝突）'};
export const entityTitle=(e:Entity)=>e.kind==='case'?`案件 ${e.project_id}`:`節點 ${e.project_id} / ${e.node_id}`;
// Outcome sentence for the delivery state. Never reports success before the mock read-back confirms it.
export const deliverySentence=(state:OpsState|undefined,labels:Record<OpsState,{label:string}>)=>state?`派送狀態：${labels[state].label}`:'尚未產生派送';
export type Draft={cid:string|null;occurredAt:string|null;people:string[];date:string;outcome:string};
export const emptyDraft=():Draft=>({cid:null,occurredAt:null,people:[],date:'',outcome:'normal'});
// Editing a draft changes its payload, so it must not reuse an operation id that already recorded another payload.
export const edited=(d:Draft,patch:Partial<Draft>):Draft=>({...d,...patch,cid:null,occurredAt:null});
export const withIdentity=(d:Draft,uuid:()=>string,now:()=>string):Draft=>d.cid?d:{...d,cid:uuid(),occurredAt:now()};
