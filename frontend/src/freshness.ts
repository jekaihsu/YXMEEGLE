import type {Freshness,LiveDataset} from './types';

// Age is anchored to the response's server clock, then advances on the client.
export function ageFreshness(value:Freshness,receivedAt:number,now:number):Freshness {
 const elapsed=Math.max(0,(now-receivedAt)/1000);
 return {...value,datasets:Object.fromEntries(Object.entries(value.datasets).map(([key,d])=>{
  const inferred=d.as_of?(Date.parse(value.server_time)-Date.parse(d.as_of))/1000:NaN;
  const initial=Number.isFinite(inferred)?Math.max(0,inferred,d.age_seconds??0):d.age_seconds;
  const age=initial==null?null:initial+elapsed;
  return [key,{...d,age_seconds:age,status:d.status==='fresh'&&(age==null||age>=d.ttl_seconds)?'stale':d.status}];
 })) as Record<LiveDataset,Freshness['datasets'][LiveDataset]>};
}

export const datasetNames:Record<LiveDataset,string>={sources:'來源',roster:'名冊',attendance:'班表'};
export function retainedAge(age:number|null):string {
 if(age==null||!Number.isFinite(age))return '顯示先前資料（時間未知）';
 return age<60?`顯示 ${Math.max(0,Math.floor(age))} 秒前資料`:`顯示 ${Math.max(1,Math.floor(age/60))} 分鐘前資料`;
}
export function datasetNotice(key:LiveDataset,d:Freshness['datasets'][LiveDataset]):string {
 const name=datasetNames[key];
 switch(d.status){
  case 'error':return `${name}：Lark 暫時無法讀取，${retainedAge(d.age_seconds)}`;
  case 'blocked':return `${name}：Lark 權限不足（1254302），請聯絡管理員`;
  case 'refreshing':return `${name}仍在更新中…`;
  case 'never':return `正在讀取 Lark ${name}…`;
  case 'stale':return `${name}資料待更新`;
  default:return '';
 }
}
