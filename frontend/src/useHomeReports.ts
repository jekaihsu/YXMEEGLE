import {ApiError} from './api';
import type {Ctx} from './appCommon';
import type {HomeReport} from './reports/types';
import type {HomeCardId,HomeViewId} from './homeLayout';
import {canReadHomeReports,isReportCard} from './homeReportCards';
import {parseHomeReport} from './homeReports';
import {useHomeResource,homeValue} from './useHomePanels';
export type HomeReportsRead={data?:HomeReport;loading:boolean;error:string;unavailable:boolean};
export function useHomeReports(c:Ctx,view:HomeViewId,ids:HomeCardId[],_today:string):HomeReportsRead{
 const enabled=view==='company'&&canReadHomeReports(c.s.user?.role)&&ids.some(isReportCard);
 const read=useHomeResource(c,{endpoint:'/api/reports/home'},raw=>{const data=parseHomeReport(raw);return homeValue(data,true,data.meta.fetched_at)},enabled);
 const unavailable=read.error instanceof ApiError&&(read.error.status===403||read.error.status===404);
 return {data:unavailable?undefined:read.data,loading:read.loading,error:read.error&&!unavailable?`週報資料暫時無法更新；已保留上次資料。${read.data?`資料時間：${read.dataTime??'未提供'}`:''}`:'',unavailable};
}
