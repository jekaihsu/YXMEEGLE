import {ApiError, getSessionEpoch, liveRefresh, liveStatus} from './api';

export async function refreshSources() {
 const epoch=getSessionEpoch(), controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),90000);
 const current=()=>{if(epoch!==getSessionEpoch())throw new Error('登入狀態已變更，請重新讀取')};
 try {
  let result=await liveRefresh(['sources'],true,controller.signal,true);
  while(true){
   current();
   const source=result.freshness.datasets.sources;
   if(source.status==='fresh')return;
   if(['error','blocked','needs-permission','unconfigured'].includes(source.status))throw new ApiError(502,(source.last_error==='Lark refresh failed'?null:source.last_error) || (source.status==='needs-permission' || source.status==='blocked'?'Lark 權限不足，請聯絡主管':'Lark 讀取失敗，請重試'));
   result=await liveStatus(controller.signal);
   if(result.freshness.datasets.sources.status!=='fresh')await new Promise<void>((resolve,reject)=>{
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
