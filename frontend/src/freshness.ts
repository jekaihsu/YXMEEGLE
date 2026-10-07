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
