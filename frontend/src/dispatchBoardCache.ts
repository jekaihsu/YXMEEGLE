import {api,ApiError,getSessionEpoch,onSessionEpochChange} from './api';
import {addDays,parseDispatchBoard,type DispatchBoardData} from './dispatchBoardModel';

type PendingRead={promise:Promise<DispatchBoardData>;controller:AbortController;readers:Set<AbortSignal>};
const snapshots=new Map<string,DispatchBoardData>();
const pending=new Map<string,PendingRead>();
const latest=new Map<string,AbortController>();
const active=new Set<AbortController>();
onSessionEpochChange(()=>{
 for(const controller of active)controller.abort();
 snapshots.clear();pending.clear();latest.clear();active.clear();
});

export const cachedDispatchBoard=(from:string)=>snapshots.get(from);

export function readDispatchBoard(from:string,signal:AbortSignal,fresh=false):Promise<DispatchBoardData> {
 const epoch=getSessionEpoch(),to=addDays(from,6);
 let entry=fresh?undefined:pending.get(from);
 if(!entry){
  const controller=new AbortController();latest.set(from,controller);active.add(controller);
  const current=()=>epoch===getSessionEpoch()&&!controller.signal.aborted;
  const promise=(async()=>{
   let raw:unknown;
   try{raw=await api<unknown>(`/api/v2/dispatch/board?${new URLSearchParams({from,to})}`,{signal:controller.signal,cache:'no-store',timeoutMs:30000},current)}
   catch(error){
    if(current()&&latest.get(from)===controller&&error instanceof ApiError&&(error.status===401||error.status===403))snapshots.delete(from);
    if(error instanceof ApiError&&error.status===403)raw={schema_version:1,window:{from,to,tz:'Asia/Taipei'},source:{quality:{states:['forbidden']}},slots:[]};
    else throw error;
   }
   const board=parseDispatchBoard(raw);
   if(board.window.from!==from||board.window.to!==to)throw new Error('回應週次與目前查詢不符，請重試。');
   if(current()&&latest.get(from)===controller){
    if(board.source.quality.states.includes('forbidden'))snapshots.delete(from);
    else snapshots.set(from,board);
    if(snapshots.size>32){const oldest=snapshots.keys().next();if(!oldest.done)snapshots.delete(oldest.value)}
   }
   return board;
  })().finally(()=>{
   active.delete(controller);
   if(pending.get(from)?.controller===controller)pending.delete(from);
   if(latest.get(from)===controller)latest.delete(from);
  });
  entry={promise,controller,readers:new Set()};pending.set(from,entry);
 }
 const shared=entry;
 shared.readers.add(signal);
 const release=()=>{
  shared.readers.delete(signal);
  if(!shared.readers.size){
   if(pending.get(from)===shared)pending.delete(from);
   shared.controller.abort();
  }
 };
 signal.addEventListener('abort',release,{once:true});
 if(signal.aborted)release();
 return shared.promise.finally(()=>{signal.removeEventListener('abort',release);shared.readers.delete(signal)});
}
