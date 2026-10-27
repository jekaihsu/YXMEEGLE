import {useEffect,useState} from 'react';
import {ApiError,getSessionEpoch} from './api';
import type {Ctx} from './appCommon';
import type {CompanyDashboard} from './companyDashboardTypes';
import {readDashboard} from './companyDashboardCache';
export function useHomeCompany(c:Ctx){
 const [state,setState]=useState<{data?:CompanyDashboard;error:string;pending:boolean}>({error:'',pending:true});
 const identity=JSON.stringify([getSessionEpoch(),c.s.workspace_id,c.s.user]);
 useEffect(()=>{
  const controller=new AbortController();
  setState({error:'',pending:true});
  readDashboard('/api/company-dashboard?offset=0&limit=5',controller.signal,identity,{reloadVersion:c.reloadVersion})
   .then(data=>{if(!controller.signal.aborted)setState({data,error:'',pending:false})})
   .catch(error=>{if(!controller.signal.aborted)setState({error:error instanceof ApiError&&error.status===403?'目前沒有公司資料權限，請切換至我的工作。':'公司資料讀取失敗，請重新讀取。',pending:false})});
  return()=>controller.abort();
 },[identity,c.reloadVersion??c.w.version]);
 return state;
}
