/** Store IDs only: names and authority always come from the current workspace. */
export const recentCasesKey=(user:string,workspace:string,epoch:number)=>`yx.recent-cases:${JSON.stringify([user,workspace,epoch])}`;
export type RecentStorage=Pick<Storage,'getItem'|'setItem'|'removeItem'>;
export function readRecentCases(storage:RecentStorage|null,key:string):string[]{
 try{const value=JSON.parse(storage?.getItem(key)||'[]');return Array.isArray(value)?[...new Set(value.filter((id):id is string=>typeof id==='string'&&!!id))].slice(0,5):[]}catch{return []}
}
export function openRecentCase(ids:string[],id:string):string[]{return [id,...ids.filter(value=>value!==id)].slice(0,5)}
export function saveRecentCases(storage:RecentStorage|null,key:string,ids:string[]){try{storage?.setItem(key,JSON.stringify(ids))}catch{}}
export function clearRecentCases(storage:RecentStorage|null,key:string){try{storage?.removeItem(key)}catch{}}
