export type Provider = '' | 'claude' | 'gpt';
export type Rating = '' | 'up' | 'down' | 'none';
export type FeedbackCounts = {up?:number; down?:number};
export type FeedbackReason = 'wrong' | 'incomplete' | 'slow' | 'other';
export type Scope = '' | 'global' | 'project';
export const scopeLabel=(scope:Scope|undefined)=>scope==='global'?'全域':scope==='project'?'案件':'—';
export type Filters = {from:string; to:string; actor:string; provider:Provider; rating:Rating; scope:Scope};
export type Metrics = FeedbackCounts & {questions:number; input_tokens:number; output_tokens:number; cost_usd:number};
export type PersonUsage = Metrics & {unpriced_calls?:number;actor_id:string; name:string; last_at:string};
export type DayUsage = Metrics & {day:string};
export type Usage = {
 range:{from:string; to:string}; totals:Metrics & {unpriced_calls:number; feedback?:{up:number;down:number;rated:number;up_rate:number|null}};
 by_person:PersonUsage[]; by_day:DayUsage[]; by_provider:(Metrics & {provider:string;unpriced_calls?:number})[];
 reasons?:Partial<Record<FeedbackReason|'unspecified',number>>;
 people:{actor_id:string; name:string}[];
 recent:{scope?:Exclude<Scope,''>;created_at:string; actor_id:string; name:string; provider:string; input_tokens:number; output_tokens:number; cost_usd:number|null; latency_ms:number; status:string; rating?:'up'|'down'|null; reason?:FeedbackReason|null}[];
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
 const from=q.get('from'),to=q.get('to'),provider=q.get('provider'),rating=q.get('rating'),scope=q.get('scope');
 return {scope:scope==='global'||scope==='project'?scope:'',from:validDay(from)?from:defaults.from,to:validDay(to)?to:defaults.to,actor:q.get('actor')||'',provider:provider==='claude'||provider==='gpt'?provider:'',rating:rating==='up'||rating==='down'||rating==='none'?rating:''};
}
export function filterQuery(filters:Filters):string {
 const q=new URLSearchParams({from:filters.from,to:filters.to});
 if(filters.scope)q.set('scope',filters.scope);
 if(filters.rating)q.set('rating',filters.rating);
 if(filters.actor)q.set('actor',filters.actor);if(filters.provider)q.set('provider',filters.provider);return q.toString();
}
export const formatNumber = (value:number) => new Intl.NumberFormat('zh-TW',{maximumFractionDigits:0}).format(value);
export const formatPercent = (value:number|null|undefined) => value==null?'尚無評分':new Intl.NumberFormat('zh-TW',{style:'percent',minimumFractionDigits:1,maximumFractionDigits:1}).format(value);
export const satisfaction = (row:FeedbackCounts) => {const rated=(row.up??0)+(row.down??0);return formatPercent(rated?(row.up??0)/rated:null)};
export const reasonLabels:Record<FeedbackReason,string> = {wrong:'答錯',incomplete:'不完整',slow:'太慢',other:'其他'};
export function reasonSeries(reasons:Usage['reasons'],down=0) {
 const named=(Object.keys(reasonLabels) as FeedbackReason[]).map(key=>({key,label:reasonLabels[key],value:reasons?.[key]??0}));
 const unspecified=reasons?.unspecified??Math.max(0,down-named.reduce((sum,item)=>sum+item.value,0));
 return [...named,{key:'unspecified',label:'未填寫',value:unspecified}];
}
export function sortProviders(rows:Usage['by_provider'],key:'up'|'down',direction:'asc'|'desc') {return [...rows].sort((a,b)=>((a[key]??0)-(b[key]??0))*(direction==='asc'?1:-1)||a.provider.localeCompare(b.provider))}
export const formatCost = (value:number|null) => value===null?'未計價':new Intl.NumberFormat('zh-TW',{style:'currency',currency:'USD',minimumFractionDigits:Math.abs(value)<1?4:2,maximumFractionDigits:Math.abs(value)<1?4:2}).format(value);
export const formatTime = (value:string) => value?new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)):'尚無紀錄';
export function sortPeople(rows:PersonUsage[],key:SortKey='cost_usd',direction:'asc'|'desc'='desc') {
 return [...rows].sort((a,b)=>{const av=a[key]??(key==='up'||key==='down'?0:''),bv=b[key]??(key==='up'||key==='down'?0:'');const comparison=typeof av==='number'&&typeof bv==='number'?av-bv:String(av).localeCompare(String(bv),'zh-TW');return (direction==='desc'?-comparison:comparison)||a.actor_id.localeCompare(b.actor_id)});
}
export function rangeError(range:{from:string;to:string}):string|null {
 if(range.from>range.to)return '開始日期不能晚於結束日期。';
 return (Date.parse(range.to)-Date.parse(range.from))/86400000+1>366?'日期範圍最多 366 天。':null;
}
export function chartSeries(rows:DayUsage[],range:{from:string;to:string}) {
 const days=new Map(rows.map(row=>[row.day,row]));const result:DayUsage[]=[];
 for(let day=range.from;day<=range.to;day=shift(day,1)){
  const row=days.get(day)||{day,questions:0,input_tokens:0,output_tokens:0,cost_usd:0};
  result.push({...row,up:row.up??0,down:row.down??0});
 }
 if(result.length<=62)return result;
 const weeks:DayUsage[]=[];
 for(let index=0;index<result.length;index+=7){
  const bucket={day:result[index].day,questions:0,input_tokens:0,output_tokens:0,cost_usd:0,up:0,down:0};
  for(const row of result.slice(index,index+7)){
   bucket.up+=row.up??0;bucket.down+=row.down??0;bucket.questions+=row.questions;bucket.input_tokens+=row.input_tokens;bucket.output_tokens+=row.output_tokens;bucket.cost_usd+=row.cost_usd;
  }
  weeks.push(bucket);
 }
 return weeks;
}
