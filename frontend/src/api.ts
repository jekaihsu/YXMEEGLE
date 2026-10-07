// Opt-in load timing (?perf=1) lives here so api.ts stays self-contained; off means one boolean check.
// Shared with App so every request captures the active session epoch.
let sessionEpoch=0;
const etagCache=new Map<string,{etag:string;data:unknown}>();
export type ApiRequestInit=RequestInit & {etag?:boolean};
const pendingMutations=new Map<number,number>();
export const getPendingMutations=()=>pendingMutations.get(sessionEpoch)||0;
const mutationChanged=()=>{if(typeof window!=='undefined')window.dispatchEvent(new Event('yx:mutation-state'))};
export const getSessionEpoch=()=>sessionEpoch;
export const invalidateSessionEpoch=()=>{sessionEpoch++;etagCache.clear()};
export class ApiError extends Error {constructor(public status:number,message:string){super(message)}}
export async function api<T>(url:string,init?:ApiRequestInit,isCurrent:()=>boolean=()=>true,onResponse?:(status:number)=>void):Promise<T>{
  const epoch=getSessionEpoch();
  const mutating=!!init?.method&&!['GET','HEAD'].includes(init.method.toUpperCase());
  if(mutating){pendingMutations.set(epoch,(pendingMutations.get(epoch)||0)+1);mutationChanged()}
  try{
  const {etag,...request}=init||{};
  const cacheable=etag===true&&!mutating&&(!init?.method||init.method.toUpperCase()==='GET');
  const cached=cacheable&&init?.cache!=='reload'&&init?.cache!=='no-store'?etagCache.get(url):undefined;
  const headers=new Headers(init?.headers);
  if(!(init?.body instanceof FormData)&&!headers.has('Content-Type'))headers.set('Content-Type','application/json');
  if(cached)headers.set('If-None-Match',cached.etag);
  else if(cacheable)headers.delete('If-None-Match');
  const trace=perfStart(url);
  const response=await fetch(url,{credentials:'same-origin',...request,headers});
  perfHeaders(trace,response);
  onResponse?.(response.status);
  if(response.status===304&&cached)return cached.data as T;
  const malformed='服務回應格式不正確，請稍後再試。';
  let data:any;let parsed=true;
  try{const text=await response.text();data=JSON.parse(text);perfParsed(trace,text)}catch{data={detail:malformed};parsed=false}
  if(response.status===401&&epoch===getSessionEpoch()&&isCurrent())window.dispatchEvent(new Event('yx:session-expired'));
  if(!response.ok)throw new ApiError(response.status,typeof data?.detail==='string'?data.detail:JSON.stringify(data?.detail||'操作未完成'));
  if(!parsed||data===null||typeof data!=='object')throw new ApiError(response.status,malformed);
  if(cacheable&&epoch===getSessionEpoch()&&isCurrent()&&!init?.signal?.aborted){
   const value=response.headers.get('ETag');
   if(value&&init?.cache!=='no-store'){
    etagCache.delete(url);etagCache.set(url,{etag:value,data});
    if(etagCache.size>100)etagCache.delete(etagCache.keys().next().value!);
   }else etagCache.delete(url);
  }
  return data;
  }finally{if(mutating){const remaining=(pendingMutations.get(epoch)||1)-1;if(remaining)pendingMutations.set(epoch,remaining);else pendingMutations.delete(epoch);mutationChanged()}}
}
export function normalizeRoute<T extends {view:string;tab?:string;section?:string}>(route:T):T {
 if(route.view==='learning')return {...route,view:'admin',tab:'people'};
 if(route.view!=='project')return route;
 if(['quotes','family','basic','participants','files'].includes(route.tab||''))return {...route,tab:'data',section:route.tab};
 if(route.tab==='operations')return {...route,tab:'flow',section:route.section||'review'};
 if(route.tab==='approvals')return {...route,tab:'flow',section:'approvals'};
 return route;
}
export function readRoute(){const p=new URLSearchParams(location.hash.replace(/^#\/?/,''));return normalizeRoute({view:p.get('view')||'dashboard',project:p.get('project')||undefined,node:p.get('node')||undefined,task:p.get('task')||undefined,tab:p.get('tab')||undefined,section:p.get('section')||undefined,completion:p.get('completion')||undefined,focus:p.get('focus')||undefined,comment:p.get('comment')||undefined,approval:p.get('approval')||undefined})}

type LiveResult={freshness:import('./types').Freshness};
async function checkedLive(request:Promise<LiveResult>):Promise<LiveResult>{
 const result=await request;const value=result.freshness;
 const statuses=['fresh','stale','refreshing','error','blocked','unconfigured','never'];
 if(!value||!Number.isFinite(Date.parse(value.server_time))||typeof value.enabled!=='boolean'||!['sources','roster','attendance'].every(key=>{
  const d=value.datasets?.[key as import('./types').LiveDataset];
  return d&&statuses.includes(d.status)&&Number.isFinite(d.ttl_seconds)&&d.ttl_seconds>0&&(d.age_seconds===null||Number.isFinite(d.age_seconds));
 }))throw new ApiError(502,'資料讀取結果尚未確認，請稍後重試。');
 return result;
}
export function liveStatus(signal?:AbortSignal){return checkedLive(api<LiveResult>('/api/live/status',{signal}))}
export function liveRefresh(datasets:import('./types').LiveDataset[],wait=false,signal?:AbortSignal){
 let status=200;
 return checkedLive(api<LiveResult>('/api/live/refresh',{signal,method:'POST',body:JSON.stringify({datasets,wait,force:false})},()=>true,value=>{status=value})).then(result=>{
  if(status!==202)return result;
  // Accepted work is still in flight, even if the response includes an older fresh snapshot.
  return {...result,freshness:{...result.freshness,datasets:Object.fromEntries(Object.entries(result.freshness.datasets).map(([key,d])=>[key,{...d,status:datasets.includes(key as import('./types').LiveDataset)&&!['error','blocked','unconfigured'].includes(d.status)?'refreshing':d.status}])) as import('./types').Freshness['datasets']}};
 });
}

export const perfOn=typeof location!=='undefined'&&new URLSearchParams(location.search).get('perf')==='1';
export type PerfTrace={id:number;url:string;status?:number;bytes?:number;serverTiming?:string|null;headersMs?:number;parseMs?:number};
type PerfSummary={requests:PerfTrace[];firstRenderMs?:number};
let seq=0,firstFetch:string|undefined;
const summary:PerfSummary={requests:[]};
const measure=(name:string,from:string,to:string)=>performance.measure(name,from,to).duration;
if(perfOn)(window as any).__yxPerf=summary;
export function perfStart(url:string):PerfTrace|undefined{
  if(!perfOn)return;
  const trace={id:++seq,url};performance.mark(`yx:${trace.id}:fetch`);
  firstFetch??=`yx:${trace.id}:fetch`;return trace;
}
export function perfHeaders(trace:PerfTrace|undefined,response:Response){
  if(!trace)return;
  performance.mark(`yx:${trace.id}:headers`);
  trace.status=response.status;trace.serverTiming=response.headers.get('Server-Timing');
  trace.headersMs=measure(`yx:${trace.id}:fetch->headers`,`yx:${trace.id}:fetch`,`yx:${trace.id}:headers`);
}
export function perfParsed(trace:PerfTrace|undefined,text:string){
  if(!trace)return;
  performance.mark(`yx:${trace.id}:parsed`);
  trace.bytes=new TextEncoder().encode(text).length;
  trace.parseMs=measure(`yx:${trace.id}:headers->parsed`,`yx:${trace.id}:headers`,`yx:${trace.id}:parsed`);
  summary.requests.push(trace);console.log('[yx-perf]',trace);
}
export function perfFirstRender(){
  if(!perfOn||summary.firstRenderMs!==undefined||!firstFetch)return;
  requestAnimationFrame(()=>{
    performance.mark('yx:first-render');
    summary.firstRenderMs=measure('yx:fetch->first-render',firstFetch!,'yx:first-render');
    console.log('[yx-perf] first render',summary.firstRenderMs.toFixed(1),'ms',summary);
  });
}
