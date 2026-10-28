import {useEffect,useState} from 'react';
import {ApiError,getSessionEpoch} from './api';
import type {Ctx} from './appCommon';
import type {CompanyDashboard} from './companyDashboardTypes';
import {cachedDashboardRead,readDashboard} from './companyDashboardCache';
const url='/api/company-dashboard?offset=0&limit=5';
type CompanyRead={data?:CompanyDashboard;error:string;pending:boolean};
export function useHomeCompany(c:Ctx){
 const epoch=getSessionEpoch();
 const identity=JSON.stringify([epoch,c.s.workspace_id||c.w.workspace_id,c.s.user,c.s.features,c.s.access_mode]);
 const [retryTick,setRetryTick]=useState(0);
 const [state,setState]=useState<{identity:string;read:CompanyRead}>(()=>({identity,read:{data:cachedDashboardRead(url,identity),error:'',pending:true}}));
 useEffect(()=>{
  const controller=new AbortController();
  setState(previous=>({identity,read:{data:cachedDashboardRead(url,identity)??(previous.identity===identity?previous.read.data:undefined),error:'',pending:true}}));
  readDashboard(url,controller.signal,identity,{reloadVersion:[c.reloadVersion??c.w.version,retryTick]})
   .then(data=>{if(!controller.signal.aborted&&epoch===getSessionEpoch())setState({identity,read:{data,error:'',pending:false}})})
   .catch(error=>{
    if(controller.signal.aborted||epoch!==getSessionEpoch())return;
    const denied=error instanceof ApiError&&(error.status===401||error.status===403);
    setState(previous=>({identity,read:{data:denied?undefined:previous.identity===identity?previous.read.data:undefined,error:denied?'目前沒有公司資料權限，請切換至我的工作。':'公司資料讀取失敗，請重新讀取。',pending:false}}));
   });
  return()=>controller.abort();
 },[identity,c.reloadVersion??c.w.version,retryTick]);
 const read=state.identity===identity?state.read:{data:cachedDashboardRead(url,identity),error:'',pending:true};
 return {...read,retry:()=>setRetryTick(value=>value+1)};
}
