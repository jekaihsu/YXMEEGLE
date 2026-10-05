export class ApiError extends Error {constructor(public status:number,message:string){super(message)}}
export async function api<T>(url:string,init?:RequestInit,isCurrent:()=>boolean=()=>true):Promise<T>{
  const response=await fetch(url,{credentials:'same-origin',...init,headers:{...(init?.body instanceof FormData?{}:{'Content-Type':'application/json'}),...init?.headers}});
  const data=await response.json().catch(()=>({detail:'服務回應格式不正確，請稍後再試。'}));
  if(response.status===401&&isCurrent())window.dispatchEvent(new Event('yx:session-expired'));
  if(!response.ok)throw new ApiError(response.status,typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||'操作未完成'));
  return data;
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
