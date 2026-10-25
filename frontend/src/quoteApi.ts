import {api, ApiError} from './api';
import {SopError, parseReceipt, type ImportReceipt} from './sopTaskApi';

export const QUOTE_STAGES = {inquiry:'詢價', quoted:'已報價', quote_expired:'報價逾期', returned:'已回簽', numbered:'已編號', confirmation:'確認單', field:'外業', office:'內業', pricing:'計價請款', paid:'已入帳', cancelled:'已取消'};
export type QuoteStage = keyof typeof QUOTE_STAGES;
export interface Quote {
 origin:'local'|'source'; quote_no:string; local_reference:string|null; engineering_no:string|null; name:string; client:string;
 quoted_on:string|null; quote_deadline:string|null; contract_amount:number|null; amount_restricted:boolean;
 quote_owners:string[]; pm_names:string[]; pm_id:string|null; project_id:string|null; stage:QuoteStage;
 sop_counts:{done:number; total:number}|null;
}
export interface QuoteDetail {quote:Quote; facts:Record<string,unknown>; records:unknown[]}
export interface QuoteForm {name:string; pm_id:string|null; client:string; description:string; official_quote_no:string; import_tasks:boolean}
export interface QuoteCase {project_id:string; local_reference:string; official_quote_no:string|null; name:string; client:string; description:string; pm_id:string|null}
export interface QuoteDraft {draft_id:string; expires_at:number; case:QuoteCase; taskCount:number}
export interface QuoteReceipt extends QuoteCase {request_id:string; imported:ImportReceipt|null}
const bad = () => new SopError(502,'malformed');
export const record = (v:unknown):Record<string,unknown> => {if (!v || typeof v !== 'object' || Array.isArray(v)) throw bad(); return v as Record<string,unknown>};
const str = (v:unknown):string => {if(typeof v !== 'string') throw bad(); return v};
const ns = (v:unknown) => v == null ? null : str(v);
const num = (v:unknown):number => {if(typeof v !== 'number' || !Number.isFinite(v)) throw bad(); return v};
const bool = (v:unknown):boolean => {if(typeof v !== 'boolean') throw bad(); return v};
const strings = (v:unknown):string[] => {if(!Array.isArray(v)) throw bad(); return v.map(str)};
export function parseQuote(v:unknown):Quote {
 const q=record(v); if(q.origin!=='source' && q.origin!=='local') throw bad();
 if(typeof q.stage!=='string' || !Object.hasOwn(QUOTE_STAGES,q.stage)) throw bad();
 const c=q.sop_counts==null?null:record(q.sop_counts), restricted=bool(q.amount_restricted);
 return {origin:q.origin,quote_no:ns(q.quote_no)||ns(q.local_reference)||'',local_reference:ns(q.local_reference),engineering_no:ns(q.engineering_no),name:ns(q.name)||'未設定',client:ns(q.client)||'',quoted_on:ns(q.quoted_on),quote_deadline:ns(q.quote_deadline),contract_amount:restricted?null:q.contract_amount==null?null:num(q.contract_amount),amount_restricted:restricted,quote_owners:strings(q.quote_owners),pm_names:strings(q.pm_names),pm_id:ns(q.pm_id),project_id:ns(q.project_id),stage:q.stage as QuoteStage,sop_counts:c?{done:num(c.done),total:num(c.total)}:null};
}
export function parseQuotePage(v:unknown) {const p=record(v); if(!Array.isArray(p.items)) throw bad(); return {total:num(p.total),items:p.items.map(parseQuote)}}
function parseCase(v:unknown):QuoteCase {const c=record(v);return {project_id:str(c.project_id),local_reference:str(c.local_reference),official_quote_no:ns(c.official_quote_no),name:str(c.name),client:str(c.client),description:str(c.description),pm_id:ns(c.pm_id)}}
export function parseQuoteDraft(v:unknown):QuoteDraft {const d=record(v);return {draft_id:str(d.draft_id),expires_at:num(d.expires_at),case:parseCase(d.case),taskCount:d.import==null?0:num(record(record(d.import).counts).new_tasks)}}
export function parseQuoteReceipt(v:unknown):QuoteReceipt {const r=record(v);return {...parseCase(r),request_id:str(r.request_id),imported:r.import==null?null:parseReceipt(r.import)}}
export async function quoteRequest(url:string, body?:unknown, current:()=>boolean=()=>true,signal?:AbortSignal):Promise<unknown> {
 try{return await api<unknown>(url,{cache:'no-store',timeoutMs:20000,signal,...(body===undefined?{}:{method:'POST',body:JSON.stringify(body)})},current)}
 catch(e){if(e instanceof ApiError) throw new SopError(e.status,e.code||'request_failed');if(e instanceof DOMException && e.name==='AbortError')throw e;throw new SopError(0,'network')}
}
export const quoteKey = (q:Quote) => q.local_reference || q.quote_no;
export const amountLabel = (q:Quote) => q.amount_restricted?'受限':q.contract_amount==null?'未設定':q.contract_amount.toLocaleString('zh-TW');
export type QuoteSort='quote_no'|'name'|'quoted_on'|'quote_deadline'|'contract_amount';
const quoteCollator=new Intl.Collator('zh-TW',{numeric:true});
export function sortQuotes(items:Quote[],key:QuoteSort,dir:number) {return [...items].sort((a,b)=>{const x=a[key],y=b[key];if(x==null)return y==null?0:1;if(y==null)return -1;return dir*(typeof x==='number'&&typeof y==='number'?x-y:quoteCollator.compare(String(x),String(y)))||a.quote_no.localeCompare(b.quote_no)})}
export const QUOTE_PAGE_SIZE = 2000;
export const quoteApi={
 list:async(query:string,current:()=>boolean,signal?:AbortSignal)=>parseQuotePage(await quoteRequest(`/api/quotes?${query}`,undefined,current,signal)),
 detail:async(key:string,current:()=>boolean,signal?:AbortSignal):Promise<QuoteDetail>=>{const d=record(await quoteRequest(`/api/quotes/${encodeURIComponent(key)}`,undefined,current,signal));return {quote:parseQuote(d),facts:record(d.facts),records:Array.isArray(d.records)?d.records:[]}},
 preview:async(form:QuoteForm,current:()=>boolean)=>parseQuoteDraft(await quoteRequest('/api/quotes/preview',form,current)),
 create:async(draft_id:string,request_id:string,current:()=>boolean)=>parseQuoteReceipt(await quoteRequest('/api/quotes',{draft_id,request_id},current)),
 recover:async(id:string,current:()=>boolean)=>parseQuoteReceipt(await quoteRequest(`/api/quotes/requests/${encodeURIComponent(id)}`,undefined,current)),
};
