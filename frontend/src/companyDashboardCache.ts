import {getSessionEpoch} from './api';
import type {CompanyDashboard} from './CompanyCockpit';

const snapshots=new Map<string,CompanyDashboard>();
let namespace='';
function key(version:number,params:string){
 const next=JSON.stringify([getSessionEpoch(),version]);
 if(next!==namespace){snapshots.clear();namespace=next}
 return params;
}
export function cachedDashboard(version:number,params:string){
 return snapshots.get(key(version,params));
}
export function rememberDashboard(epoch:number,version:number,params:string,data:CompanyDashboard){
 if(epoch!==getSessionEpoch())return;
 snapshots.set(key(version,params),data);
 if(snapshots.size>32){const oldest=snapshots.keys().next();if(!oldest.done)snapshots.delete(oldest.value)}
}
