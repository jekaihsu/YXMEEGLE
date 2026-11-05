// Pure recovery rules for Input registration drafts. The draft's request_id is
// the submission identity: it is never regenerated except after the server is
// known to hold the revision, a success, or an explicit user reset.
import {ApiError} from './api';
export type InputDraft={label:string;value:string;request_id:string;attempted:boolean};
export type FailureKind='auth'|'rejected'|'conflict'|'unknown';
export const SUBMIT_TIMEOUT_MS=30000;

export const freshDraft=():InputDraft=>({label:'',value:'',request_id:crypto.randomUUID(),attempted:false});

// 401 expires the session; 403/422 (and other 4xx) are definite rejections that
// persist nothing; 409 is a stale version or an identity mismatch. 5xx, 429,
// timeouts and network errors do not say whether the server saved the request.
export function classifyFailure(error:unknown):FailureKind{
 if(!(error instanceof ApiError))return 'unknown';
 if(error.status===401)return 'auth';
 if(error.status===409)return 'conflict';
 if([408,429].includes(error.status)||error.status>=500)return 'unknown';
 return error.status>=400?'rejected':'unknown';
}

// Keep entered content and request_id in every case; only the lock changes.
export function draftAfterFailure(draft:InputDraft,kind:FailureKind,wasAttempted:boolean):InputDraft{
 if(kind==='unknown')return {...draft,attempted:true};
 if(kind==='rejected')return {...draft,attempted:false};
 return {...draft,attempted:wasAttempted};
}

export const needsRefresh=(kind:FailureKind)=>kind==='auth'||kind==='conflict'||kind==='unknown';

// A revision already carrying this request_id means the earlier submit landed.
export const persistedFor=(rows:any[],requestId:string)=>rows.find(r=>r.request_id===requestId);

export function timeoutInit(ms=SUBMIT_TIMEOUT_MS):{signal:AbortSignal;done:()=>void}{
 const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),ms);
 return {signal:controller.signal,done:()=>clearTimeout(timer)};
}

export const DISPOSAL_REASON_MAX=500;
export const disposalReady=(confirmed:boolean,reason:string)=>confirmed&&reason.trim().length>0&&reason.trim().length<=DISPOSAL_REASON_MAX;
