// Opt-in load timing (?perf=1) lives here so api.ts stays self-contained; off means one boolean check.
// Shared with App so every request captures the active session epoch.
let sessionEpoch=0;
const etagCache=new Map<string,{etag:string;data:unknown}>();
export type ApiRequestInit=RequestInit & {etag?:boolean;timeoutMs?:number};
const pendingMutations=new Map<number,number>();
export const getPendingMutations=()=>pendingMutations.get(sessionEpoch)||0;
const mutationChanged=()=>{if(typeof window!=='undefined')window.dispatchEvent(new Event('yx:mutation-state'))};
export const getSessionEpoch=()=>sessionEpoch;
export const invalidateSessionEpoch=()=>{sessionEpoch++;etagCache.clear()};
export class ApiError extends Error {constructor(public status:number,message:string,public code?:string,public ceiling_seconds?:number,public warming?:boolean,public retry_after?:number){super(message)}}
export async function api<T>(url:string,init?:ApiRequestInit,isCurrent:()=>boolean=()=>true,onResponse?:(status:number)=>void):Promise<T>{
  const epoch=getSessionEpoch();
  const mutating=!!init?.method&&!['GET','HEAD'].includes(init.method.toUpperCase());
  if(mutating){pendingMutations.set(epoch,(pendingMutations.get(epoch)||0)+1);mutationChanged()}
  const {etag,timeoutMs,...request}=init||{};
  const controller=timeoutMs?new AbortController():undefined;
  let timer:ReturnType<typeof setTimeout>|undefined;
  let cancel:()=>void=()=>{};
  const deadline=controller?new Promise<never>((_resolve,reject)=>{
   cancel=()=>{reject(new DOMException('aborted','AbortError'));controller.abort()};
   request.signal?.addEventListener('abort',cancel,{once:true});
   timer=setTimeout(()=>{reject(new ApiError(408,'讀取逾時，請重試。','client_timeout'));controller.abort()},timeoutMs);
   if(request.signal?.aborted)cancel();
  }):undefined;
  const bounded=<V>(work:Promise<V>):Promise<V>=>deadline?Promise.race([work,deadline]):work;
  try{
  const cacheable=etag===true&&!mutating&&(!init?.method||init.method.toUpperCase()==='GET');
  const cached=cacheable&&init?.cache!=='reload'&&init?.cache!=='no-store'?etagCache.get(url):undefined;
  const headers=new Headers(init?.headers);
  if(!(init?.body instanceof FormData)&&!headers.has('Content-Type'))headers.set('Content-Type','application/json');
  if(cached)headers.set('If-None-Match',cached.etag);
  else if(cacheable)headers.delete('If-None-Match');
  const trace=perfStart(url);
  const response=await bounded(fetch(url,{credentials:'same-origin',...request,headers,...(controller?{signal:controller.signal}:{})}));
  perfHeaders(trace,response);
  onResponse?.(response.status);
  if(response.status===304&&cached)return cached.data as T;
  const malformed='服務回應格式不正確，請稍後再試。';
  let data:any;let parsed=true;
  try{const text=await bounded(response.text());data=JSON.parse(text);perfParsed(trace,text)}catch(error){if(controller?.signal.aborted)throw error;data={detail:malformed};parsed=false}
  if(response.status===401&&epoch===getSessionEpoch()&&isCurrent())window.dispatchEvent(new Event('yx:session-expired'));
  if(!response.ok)throw new ApiError(response.status,typeof data?.message==='string'?data.message:typeof data?.detail==='string'?data.detail:JSON.stringify(data?.detail||'操作未完成'),typeof data?.code==='string'?data.code:undefined,Number.isFinite(data?.ceiling_seconds)?data.ceiling_seconds:undefined,data?.warming===true,Number.isFinite(data?.retry_after)?data.retry_after:undefined);
  if(!parsed||data===null||typeof data!=='object')throw new ApiError(response.status,malformed);
  if(cacheable&&epoch===getSessionEpoch()&&isCurrent()&&!init?.signal?.aborted){
   const value=response.headers.get('ETag');
   if(value&&init?.cache!=='no-store'){
    etagCache.delete(url);etagCache.set(url,{etag:value,data});
    if(etagCache.size>100)etagCache.delete(etagCache.keys().next().value!);
   }else etagCache.delete(url);
  }
  return data;
  }finally{if(timer!==undefined)clearTimeout(timer);request.signal?.removeEventListener('abort',cancel);if(mutating){const remaining=(pendingMutations.get(epoch)||1)-1;if(remaining)pendingMutations.set(epoch,remaining);else pendingMutations.delete(epoch);mutationChanged()}}
}
export function normalizeRoute<T extends {view:string;tab?:string;section?:string}>(route:T):T {
 if(route.view==='pm-glance')return {...route,view:'dashboard'};
 if(route.view==='learning')return {...route,view:'admin',tab:'people'};
 if(route.view!=='project')return route;
 if(['quotes','family','basic','participants','files'].includes(route.tab||''))return {...route,tab:'data',section:route.tab};
 if(route.tab==='operations')return {...route,tab:'flow',section:route.section||'review'};
 if(route.tab==='approvals')return {...route,tab:'flow',section:'approvals'};
 return route;
}
export function parseRoute(hash:string){const p=new URLSearchParams(hash.replace(/^#\/?/,''));return normalizeRoute({view:p.get('view')||'dashboard',project:p.get('project')||undefined,node:p.get('node')||undefined,task:p.get('task')||undefined,tab:p.get('tab')||undefined,section:p.get('section')||undefined,completion:p.get('completion')||undefined,focus:p.get('focus')||undefined,comment:p.get('comment')||undefined,approval:p.get('approval')||undefined,ctx:p.get('ctx')||undefined})}
export const readRoute=()=>parseRoute(location.hash);

type LiveResult={freshness:import('./types').Freshness};
async function checkedLive(request:Promise<LiveResult>):Promise<LiveResult>{
 const result=await request;const value=result.freshness;
 const statuses=['fresh','stale','refreshing','error','blocked','needs-permission','unconfigured','never'];
 if(!value||!Number.isFinite(Date.parse(value.server_time))||typeof value.enabled!=='boolean'||!['sources','roster','attendance'].every(key=>{
  const d=value.datasets?.[key as import('./types').LiveDataset];
  return d&&statuses.includes(d.status)&&Number.isFinite(d.ttl_seconds)&&d.ttl_seconds>0&&(d.age_seconds===null||Number.isFinite(d.age_seconds));
 }))throw new ApiError(502,'資料讀取結果尚未確認，請稍後重試。');
 return result;
}
export function liveStatus(signal?:AbortSignal){return checkedLive(api<LiveResult>('/api/live/status',{signal}))}
export function liveRefresh(datasets:import('./types').LiveDataset[],wait=false,signal?:AbortSignal){
 let status=200;
 return checkedLive(api<LiveResult>('/api/live/refresh',{signal,timeoutMs:120000,method:'POST',body:JSON.stringify({datasets,wait,force:false})},()=>true,value=>{status=value})).then(result=>{
  if(status!==202)return result;
  // Accepted work is still in flight, even if the response includes an older fresh snapshot.
  return {...result,freshness:{...result.freshness,datasets:Object.fromEntries(Object.entries(result.freshness.datasets).map(([key,d])=>[key,{...d,status:datasets.includes(key as import('./types').LiveDataset)&&!['error','blocked','needs-permission','unconfigured'].includes(d.status)?'refreshing':d.status}])) as import('./types').Freshness['datasets']}};
 });
}

export const perfOn=typeof location!=='undefined'&&new URLSearchParams(location.search).get('perf')==='1';
export type PerfTrace={id:number;url:string;status?:number;bytes?:number;serverTiming?:string|null;headersMs?:number;parseMs?:number};
type PerfSummary={requests:PerfTrace[];firstRenderMs?:number;marks:Record<string,number>};
let seq=0,firstFetch:string|undefined;
const summary:PerfSummary={requests:[],marks:{}};
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
// Named render marks (?perf=1), e.g. shell-first-render and project-page-render: ms from the first request, recorded once per name.
export function perfMark(name:string){
  if(!perfOn||name in summary.marks||!firstFetch)return;
  summary.marks[name]=-1;
  requestAnimationFrame(()=>{
    performance.mark(`yx:${name}`);
    summary.marks[name]=measure(`yx:fetch->${name}`,firstFetch!,`yx:${name}`);
    console.log('[yx-perf]',name,summary.marks[name].toFixed(1),'ms');
  });
}

export const fetchPilotShadow=(signal?:AbortSignal)=>api<unknown>('/api/lark-pilot/shadow',{method:'GET',cache:'no-store',signal,timeoutMs:120000});

export const fetchCaseNavigation=(projectId:string,signal?:AbortSignal)=>api<import('./CaseNavigation').Navigation>(`/api/projects/${encodeURIComponent(projectId)}/navigation`,{signal});

// P2 read-only pages (VCC-128..132): one GET per page view; the caller owns retry (the identical GET only).
export const fetchP2=(url:string,signal?:AbortSignal)=>api<unknown>(url,{method:'GET',cache:'no-store',signal,timeoutMs:60000});

export function disabledRouteFeature(route:import('./types').Route,features:import('./types').FeatureContract|undefined):'change_extension'|'routines'|'dispatch_board'|undefined {
 const normalized=normalizeRoute(route);
 if(normalized.view==='dispatch'&&features?.dispatch_board!==true)return 'dispatch_board';
 if((normalized.view==='approvals'||normalized.approval)&&features?.change_extension!==true)return 'change_extension';
 if((normalized.view==='routines'||(normalized.view==='project'&&normalized.tab==='flow'&&normalized.section==='routines'))&&features?.routines!==true)return 'routines';
 return undefined;
}
