import {ApiError} from './api';
import type {PortfolioPage} from './projectsListModel';
export type PortfolioSequence = {first:PortfolioPage;items:PortfolioPage['items'];complete:boolean;error:string;denied?:boolean};
/** Continue this open's intent; restart conflicts at most twice, without timers. */
export async function readPortfolioSequence(initial:PortfolioPage, fetchPage:(page:number,snapshot?:string)=>Promise<PortfolioPage>, signal:AbortSignal, publish:(value:PortfolioSequence)=>void) {
 let first=initial,items:PortfolioPage['items']=[],restarts=0;
 const state=(complete:boolean,error='',denied=false)=>({first,items:[...items],complete,error,denied});
 while(!signal.aborted){
  try{
   let page=first.next_page;
   const seen=new Set<number>();
   while(page&&!signal.aborted){
    if(seen.has(page))throw new Error('案件分頁重複，請重新讀取。');
    seen.add(page);
    const next=await fetchPage(page,first.snapshot);
    if(signal.aborted)return;
    if(next.snapshot_replaced&&next.page===1&&next.next_page==null&&next.items.length===next.total){
     first=next;items=[];publish(state(true));return;
    }
    if(next.snapshot!==first.snapshot)throw new ApiError(409,'案件清單持續更新，請重新讀取。');
    if(next.stale)first={...first,stale:true};
    items.push(...next.items);page=next.next_page;
    publish(state(!page));
   }
   if(!signal.aborted)publish(state(true));
   return;
  }catch(error){
   if(signal.aborted)return;
   if(error instanceof ApiError&&error.status===409&&restarts++<2){
    try{
     const replacement=await fetchPage(1);
     if(signal.aborted)return;
     first=replacement;items=[];publish(state(!first.next_page));continue;
    }catch(reloadError){error=reloadError}
   }
   const denied=error instanceof ApiError&&(error.status===401||error.status===403);
   publish(state(false,error instanceof Error?error.message:'案件清單讀取失敗',denied));return;
  }
 }
}
