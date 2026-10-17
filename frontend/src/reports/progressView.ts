export const caseStatusStyles:Record<string,string>={報價中:'quote',執行中:'active',已完工:'complete',已結案:'closed',中止:'stopped',內部:'internal',未填:'unset'};
export function caseStatus(status:string){return {label:!status||status==='未填'?'狀態未填':status,tone:caseStatusStyles[status||'未填']??'neutral'}}
export type ProgressContext={dept:string;week:string;group:string;caseKey:string;status?:string;q?:string};
export function readProgressContext(hash:string,fallbackWeek:string):ProgressContext{
 const p=new URLSearchParams(hash.replace(/^#/,''));const week=p.get('week')??'';
 return {dept:p.get('dept')==='office'?'office':'field',week:/^\d{4}-\d{2}-\d{2}$/.test(week)&&Number.isFinite(Date.parse(week))&&new Date(`${week}T12:00:00Z`).getUTCDay()===1?week:fallbackWeek,group:p.get('group')??'',caseKey:p.get('case')??'',status:p.get('status')??'',q:p.get('q')??''};
}
export function progressHash(hash:string,context:ProgressContext){const p=new URLSearchParams(hash.replace(/^#/,''));p.set('view','reports');p.set('tab','progress');for(const [key,value] of Object.entries({dept:context.dept,week:context.week,group:context.group,case:context.caseKey,status:context.status,q:context.q})){if(value)p.set(key,value);else p.delete(key)}return '#'+p.toString()}
