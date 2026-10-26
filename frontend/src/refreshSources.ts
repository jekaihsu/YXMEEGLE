import {api, ApiError, getSessionEpoch, liveRefresh, liveStatus} from './api';

import type {Freshness, LiveDataset} from './types';

type SyncResult={freshness?:Freshness;status?:string};
export async function refreshSources(dataset:LiveDataset='sources', legacy?:{url:string;body?:string}) {
 const epoch=getSessionEpoch(), controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),90000);
 const current=()=>{if(epoch!==getSessionEpoch())throw new Error('登入狀態已變更，請重新讀取')};
 try {
  let status=200;
  let result:SyncResult=legacy?await api<SyncResult>(legacy.url,{method:'POST',body:legacy.body,signal:controller.signal},()=>true,value=>{status=value}):await liveRefresh([dataset],true,controller.signal,dataset==='sources');
  if(legacy && status!==202)return result;
  if(legacy && result.freshness)result={...result,freshness:{...result.freshness,datasets:{...result.freshness.datasets,[dataset]:{...result.freshness.datasets[dataset],status:'refreshing'}}}};
  while(true){
   current();
   const source=result.freshness!.datasets[dataset];
   if(source.status==='fresh')return {...result,status:'ready'};
   if(['error','blocked','needs-permission','unconfigured'].includes(source.status))throw new ApiError(502,(source.last_error==='Lark refresh failed'?null:source.last_error) || (source.status==='needs-permission' || source.status==='blocked'?'Lark 權限不足，請聯絡主管':'Lark 讀取失敗，請重試'));
   result=await liveStatus(controller.signal);
   if(['refreshing','never','stale'].includes(result.freshness!.datasets[dataset].status))await new Promise<void>((resolve,reject)=>{
    if(controller.signal.aborted){reject(new Error('資料仍在更新，請稍後重試'));return}
    const abort=()=>{clearTimeout(wait);reject(new Error('資料仍在更新，請稍後重試'))};
    const wait=setTimeout(()=>{controller.signal.removeEventListener('abort',abort);resolve()},1000);
    controller.signal.addEventListener('abort',abort,{once:true});
   });
  }
 }catch(error){
  if(controller.signal.aborted)throw new Error('資料仍在更新，請稍後重試');
  if(error instanceof TypeError)throw new Error('Lark 讀取失敗，請重試');
  throw error;
 }finally{clearTimeout(timer)}
}
