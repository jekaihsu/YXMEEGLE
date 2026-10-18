import type {HomeReport,Kpi} from './reports/types';
type Parser<T>=(value:unknown)=>T;
const fail=():never=>{throw new Error('週報資料格式不正確，請稍後再試。')};
const text:Parser<string>=v=>typeof v==='string'?v:fail();
const num:Parser<number>=v=>typeof v==='number'&&Number.isFinite(v)?v:fail();
const bool:Parser<boolean>=v=>typeof v==='boolean'?v:fail();
const nullable=<T>(parse:Parser<T>):Parser<T|null>=>v=>v===null?null:parse(v);
const optional=<T>(parse:Parser<T>):Parser<T|undefined>=>v=>v===undefined?undefined:parse(v);
const list=<T>(parse:Parser<T>):Parser<T[]>=>v=>Array.isArray(v)?v.map(parse):fail();
function object<T>(shape:{[K in keyof T]-?:Parser<T[K]>}):Parser<T>{
 return value=>{
  if(value===null||typeof value!=='object'||Array.isArray(value))return fail();
  const result=Object.fromEntries(Object.entries<Parser<unknown>>(shape).map(([key,parse])=>[key,parse(Reflect.get(value,key))]));
  return result as T;
 };
}
const rate=nullable(num);
const kpi=object<Kpi>({total:num,passed:num,returned:num,pending:num,unset:num,error_rate:rate,pending_rate:rate,coverage:rate});
const asset=object<NonNullable<HomeReport['assets']>['instrument']>({kpi:object({mileage_excluded:optional(num),coverage:optional(rate),total:num,active:num,in_use:num,idle:num,repair:num,km:rate,daily_rent_total:rate}),by_category:list(object({category:text,total:num,in_use:num,repair:num}))});
const parse=object<HomeReport>({
 meta:object({can_refresh:optional(bool),fetched_at:text,stale:bool,refresh_error:optional(bool),snapshot:text,gaps:list(object({id:text,severity:v=>v==='info'||v==='warn'?v:fail(),message:text}))}),week:text,
 quality:nullable(object({kpi,kpi_prev:kpi,trend:list(object({week:text,total:num,returned:num,passed:num,error_rate:rate})),by_group:list(object({group:text,total:num,passed:num,returned:num,pending:num,unset:num,error_rate:rate,pending_rate:rate,coverage:rate})),control:object({checked:num,unchecked:num,violated:num})})),
 quality_office:nullable(object({kpi})),
 sales:nullable(object({kpi:object({cases:num,contract_total:rate,billed_total:rate,received_total:rate,unbilled_billable:rate,receivable:rate}),by_status:list(object({status:text,count:num,contract_total:rate})),top_receivable:list(object({id:text,code:text,name:text,client:text,pm:text,status:text,contract:rate,progress_revenue:rate,progress_cost:rate,progress_billing:rate,billable_unbilled:rate,receivable:rate,link:text}))})),
 progress:nullable(object({week:text,basis:v=>v==='days'||v==='points'?v:fail(),kpi:object({planned_days:num,actual_days:num,unplanned_days:optional(num),matched_days:optional(num),matched_points:optional(num),planned_points:rate,actual_points:num,achievement:rate,open_cases:num,remaining_points:rate}),by_group:list(object({group:text,group_label:optional(text),planned_days:optional(num),matched_days:optional(num),matched_points:optional(num),unplanned_days:optional(num),planned:num,actual:num,achievement:rate}))})),
 assets:nullable(object({instrument:asset,vehicle:asset})),
});
export function parseHomeReport(value:unknown):HomeReport{return parse(value)}
