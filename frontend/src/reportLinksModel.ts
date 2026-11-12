import vocabulary from '../../backend/report_link_vocabulary.json';
export const linkVocabulary=vocabulary;
export type ReportLinkBasis=typeof vocabulary[keyof typeof vocabulary]['value'];
export const REASON_LABELS={missing_reference:'缺少關聯',unresolved_reference:'暫填案號無對應',ambiguous_reference:'多個候選，關聯有歧義'};
export type LinkReason=keyof typeof REASON_LABELS;
export type Candidate={project_id:string;rank:number;reasons:string[]};
export type LinkRow={id:string;date?:string;department?:string;person?:string;description?:string;source_case_code?:string;source_fields?:Record<string,unknown>;source_identity?:Record<string,string>;candidate_evidence:Candidate[];case_mapping_status?:LinkReason|'matched';project_id:string|null;project_code:string|null;match_basis?:string;work_item_id?:string;source_missing?:boolean;can_review:boolean};
export type LinkProject={id:string;code:string;name:string;can_review:boolean;items:{id:string;name:string}[]};
export type Bridge={project_id:string;project_code:string;status:'auto_exact'|'reviewed'|'rejected'|'pending';codes:string[];candidates:{case_key:string;case_code:string;match:string}[];reason:string;actor_id:string;decided_at:string;can_review:boolean};
export type LinkQueue={rows:LinkRow[];projects:LinkProject[];reasons:Record<LinkReason,number>;reviews:{id:string;daily_id:string;project_id:string;reason:string;status:string}[];bridges:Bridge[];available_codes:string[]};
export type LinkCounts={linked:number;unlinked:number;latest_date:string|null;basis:Record<string,number>};
export type LinkSummary=LinkCounts&{total:number;unlinked_scope:string;departments:Record<string,LinkCounts>;reasons:Record<LinkReason,number>;bridges?:Record<string,number>;bridge_unknown?:number};
export function basisLabel(value?:string){return Object.values(vocabulary).find(v=>v.value===value)?.label || (value==='manual_reviewed'?'人工核對':'待配對')}
export function groupedQueue(rows:LinkRow[]){return Object.entries(REASON_LABELS).map(([reason,label])=>({reason,label,rows:rows.filter(r=>!r.project_id && (r.case_mapping_status || 'missing_reference')===reason)}))}
export function summaryLine(summary:Pick<LinkSummary,'linked'|'total'|'unlinked'>){return `日報已連結 ${summary.linked} / ${summary.total} 筆，待配對 ${summary.unlinked} 筆`}
export function candidateReason(reason:string){return reason==='legacy_containment_unknown_provenance'?'舊資料位於此案件，來源依據未知':reason==='typed_native_identity'?'同 Base／表格／紀錄的原生關聯':reason==='exact_full_case_code'?'完整案號完全一致':reason.startsWith('reviewed_alias:')?`已核對別名 ${reason.slice(15)}`:reason}
export function sameCodeRows(rows:LinkRow[],row:LinkRow){const code=row.source_case_code?.trim();return code?rows.filter(r=>!r.project_id&&!r.source_missing&&r.source_case_code?.trim()===code):[]}
