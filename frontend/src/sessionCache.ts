import {onSessionEpochChange} from './api';

/** Small legacy snapshot stores; page-owner entries remain authoritative. */
export class SessionCache<K,V> extends Map<K,V>{
 constructor(private readonly limit=64){super();onSessionEpochChange(()=>this.clear())}
 override get(key:K):V|undefined{
  const value=super.get(key);
  if(super.has(key)){super.delete(key);super.set(key,value!)}
  return value;
 }
 override set(key:K,value:V):this{
  super.delete(key);super.set(key,value);
  while(this.size>this.limit){const oldest=this.keys().next();if(oldest.done)break;super.delete(oldest.value)}
  return this;
 }
}
