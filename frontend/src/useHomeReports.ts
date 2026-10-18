import {useEffect,useRef,useState} from 'react';
import {api,ApiError,getSessionEpoch} from './api';
import type {Ctx} from './appCommon';
import type {HomeReport} from './reports/types';
import type {HomeCardId,HomeViewId} from './homeLayout';
import {canReadHomeReports,isReportCard} from './homeReportCards';
import {parseHomeReport} from './homeReports';
export type HomeReportsRead={data?:HomeReport;loading:boolean;error:string;unavailable:boolean};
const denied=new Set<string>();
export function useHomeReports(c:Ctx,view:HomeViewId,ids:HomeCardId[]):HomeReportsRead{
 const identity=JSON.stringify([getSessionEpoch(),c.s.workspace_id,c.s.mode,c.s.user?.id,c.s.user?.role]);
 const enabled=view==='company'&&canReadHomeReports(c.s.user?.role)&&ids.some(isReportCard);
 const token=JSON.stringify([identity,c.reloadVersion]);
 const sequence=useRef(0),completed=useRef('');
 const [state,setState]=useState<HomeReportsRead&{identity:string}>({identity,loading:false,error:'',unavailable:denied.has(identity)});
 useEffect(()=>{
  if(!enabled||denied.has(identity)||completed.current===token)return;
  const controller=new AbortController(),seq=++sequence.current,epoch=getSessionEpoch();
  const current=()=>!controller.signal.aborted&&seq===sequence.current&&epoch===getSessionEpoch();
  setState(previous=>({identity,data:previous.identity===identity?previous.data:undefined,loading:true,error:'',unavailable:false}));
  void Promise.resolve().then(()=>{if(!current())throw new DOMException('aborted','AbortError');return api<unknown>('/api/reports/home',{signal:controller.signal},current)}).then(parseHomeReport).then(data=>{
   if(current()){completed.current=token;setState({identity,data,loading:false,error:'',unavailable:false})}
  }).catch(error=>{
   if(!current())return;
   completed.current=token;
   if(error instanceof ApiError&&(error.status===403||error.status===404)){
    denied.add(identity);setState({identity,loading:false,error:'',unavailable:true});
   }else setState(previous=>({...previous,loading:false,error:'週報資料暫時無法更新；已保留上次資料。',unavailable:false}));
  });
  return()=>controller.abort();
 },[identity,enabled,token]);
 return enabled?(state.identity===identity?state:{loading:true,error:'',unavailable:denied.has(identity)}):{loading:false,error:'',unavailable:denied.has(identity)};
}
