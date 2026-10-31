export type Provider = '' | 'claude' | 'gpt';
export type Filters = {from:string; to:string; actor:string; provider:Provider};
export type Metrics = {questions:number; input_tokens:number; output_tokens:number; cost_usd:number};
export type PersonUsage = Metrics & {actor_id:string; name:string; last_at:string};
export type DayUsage = Metrics & {day:string};
export type Usage = {
 range:{from:string; to:string}; totals:Metrics & {unpriced_calls:number};
 by_person:PersonUsage[]; by_day:DayUsage[]; by_provider:(Metrics & {provider:string})[];
 people:{actor_id:string; name:string}[];
 recent:{created_at:string; actor_id:string; name:string; provider:string; input_tokens:number; output_tokens:number; cost_usd:number|null; latency_ms:number; status:string}[];
};
export type SortKey = keyof PersonUsage;
export const isTokenDashboardPath = (path:string) => path.replace(/\/+$/, '') === '/token_dashboard';
export const canViewUsage = (role:string|undefined) => role === 'manager';
export function taipeiDay(now=new Date()):string {
 return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
}
function shift(day:string, amount:number) {const date=new Date(day+'T00:00:00Z');date.setUTCDate(date.getUTCDate()+amount);return date.toISOString().slice(0,10)}
export function presetRange(preset:'today'|'week'|'month'|'thisMonth', now=new Date()) {
 const to=taipeiDay(now);return {from:preset==='thisMonth'?to.slice(0,8)+'01':shift(to,preset==='today'?0:preset==='week'?-6:-29),to};
}
function validDay(value:string|null):value is string {return !!value&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&!Number.isNaN(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value}
export function readFilters(search:string, now=new Date()):Filters {
 const q=new URLSearchParams(search), defaults=presetRange('month',now);
 const from=q.get('from'),to=q.get('to'),provider=q.get('provider');
 return {from:validDay(from)?from:defaults.from,to:validDay(to)?to:defaults.to,actor:q.get('actor')||'',provider:provider==='claude'||provider==='gpt'?provider:''};
}
export function filterQuery(filters:Filters):string {
 const q=new URLSearchParams({from:filters.from,to:filters.to});
 if(filters.actor)q.set('actor',filters.actor);if(filters.provider)q.set('provider',filters.provider);return q.toString();
}
export const formatNumber = (value:number) => new Intl.NumberFormat('zh-TW',{maximumFractionDigits:0}).format(value);
export const formatCost = (value:number|null) => value===null?'未計價':new Intl.NumberFormat('zh-TW',{style:'currency',currency:'USD',minimumFractionDigits:Math.abs(value)<1?4:2,maximumFractionDigits:Math.abs(value)<1?4:2}).format(value);
export const formatTime = (value:string) => value?new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)):'尚無紀錄';
export function sortPeople(rows:PersonUsage[],key:SortKey='cost_usd',direction:'asc'|'desc'='desc') {
 return [...rows].sort((a,b)=>{const av=a[key],bv=b[key];const comparison=typeof av==='number'&&typeof bv==='number'?av-bv:String(av).localeCompare(String(bv),'zh-TW');return (direction==='desc'?-comparison:comparison)||a.actor_id.localeCompare(b.actor_id)});
}
export function chartSeries(rows:DayUsage[],range:{from:string;to:string}) {
 const days=new Map(rows.map(row=>[row.day,row]));const result:DayUsage[]=[];
 for(let day=range.from;day<=range.to&&result.length<3660;day=shift(day,1))result.push(days.get(day)||{day,questions:0,input_tokens:0,output_tokens:0,cost_usd:0});
 return result;
}
