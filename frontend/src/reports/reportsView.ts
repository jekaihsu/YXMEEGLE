export const number = (v:number|null|undefined) => v==null||!Number.isFinite(v)?'—':new Intl.NumberFormat('zh-TW',{maximumFractionDigits:1}).format(v);
export const rate = (v:number|null|undefined) => v==null||!Number.isFinite(v)?'無法計算':`${number(v*100)}%`;
export const money = (v:number|null|undefined) => v==null||!Number.isFinite(v)?'—':`NT$ ${number(v)}`;
export const clamp = (v:number,min=0,max=1) => Math.max(min,Math.min(max,Number.isFinite(v)?v:min));
export function query(values:Record<string,string|number|undefined>){const p=new URLSearchParams();Object.entries(values).forEach(([k,v])=>{if(v!==undefined&&v!=='')p.set(k,String(v))});return p.toString()}
export function shiftWeek(week:string,delta:number){const d=new Date(`${week}T00:00:00+08:00`);d.setUTCDate(d.getUTCDate()+delta*7);return new Date(d.getTime()+8*3600000).toISOString().slice(0,10)}
export function lastWeek(now=new Date()){const local=new Date(now.getTime()+8*3600000);const day=local.getUTCDay();local.setUTCDate(local.getUTCDate()-((day+6)%7)-7);return local.toISOString().slice(0,10)}
export function change(current:number|null,previous:number|null){if(current==null||previous==null)return '前週無可比較資料';const d=(current-previous)*100;return `較前週 ${d>0?'+':''}${number(d)} 個百分點`}
export const statusLabel={passed:'已通過',returned:'已退回',pending:'待檢核',unset:'未填'};
export function safeLink(link:string){try{const u=new URL(link);return u.protocol==='https:'?link:undefined}catch{return undefined}}

export function sample(reviewed:number){return `${number(reviewed)} 筆已檢核${reviewed>0&&reviewed<20?' · 樣本少':''}`}
export function compactMoney(v:number|null|undefined){if(v==null||!Number.isFinite(v))return '來源無資料';return `NT$ ${number(v>=100000000?v/100000000:v>=10000?v/10000:v)}${v>=100000000?' 億':v>=10000?' 萬':''}`}

export function nextSortOrder(current:string,order:string,next:string){if(current===next)return order==='asc'?'desc':'asc';return ['points','contract','progress_revenue','progress_cost','progress_billing','billable_unbilled','receivable','uses','km','idle_days','daily_rent','planned','actual','planned_days','actual_days','achievement','diff','expected_total','done_total','remaining'].includes(next)?'desc':'asc'}
