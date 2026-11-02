import {ApiError} from './api';
import type {Ctx} from './appCommon';
import type {CompanyDashboard} from './companyDashboardTypes';
import {useHomeResource,homeValue} from './useHomePanels';
export function useHomeCompany(c:Ctx){
 const read=useHomeResource(c,{endpoint:'/api/company-dashboard',query:{offset:0,limit:5}},raw=>{const data=raw as CompanyDashboard;return homeValue(data,data.complete!==false,data.source?.last_success_at??null)});
 const denied=read.error instanceof ApiError&&(read.error.status===401||read.error.status===403);
 return {data:denied?undefined:read.data,pending:read.loading,error:read.error?denied?'目前沒有公司資料權限，請切換至我的工作。':'公司資料讀取失敗，請重新讀取。':'',retry:read.retry};
}
