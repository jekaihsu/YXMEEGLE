export const PROJECT_TABS=[{key:'overview',label:'總覽'},{key:'flow',label:'流程與任務'},{key:'items',label:'工項與進度'},{key:'people',label:'排程與人員'},{key:'files',label:'文件與交付'},{key:'data',label:'案件資料'}] as const;
type ProjectRoute={tab?:string;section?:string;node?:string;task?:string;focus?:string;approval?:string;comment?:string;all_tasks?:string;task_filters?:string};
export function projectFlowRoute(route:ProjectRoute){
 const original=route.tab || (route.node || route.task || route.focus ? 'flow' : route.approval ? 'data' : route.comment ? 'data' : 'overview');
 const aliases:Record<string,string>={tasks:'flow',progress:'items',daily:'items',logs:'data'};
 const tab=original==='data' && route.section==='files' ? 'files' : aliases[original] || original;
 const section=route.section || (original==='tasks' ? 'all-tasks' : original==='daily' ? 'reports' : original==='logs' || !route.tab && route.comment ? 'activity' : !route.tab && route.approval ? 'approvals' : undefined);
 const allTasks=original==='tasks' || section==='all-tasks' || route.all_tasks==='1';
 return {tab,focus:allTasks ? 'tasks' : 'node',allTasks,...(section ? {section} : {})};
}

export function homeTarget({assignment_node,assignment_task,...target}:import('./useHomePanels').HomeTarget){
 return {...target,node:assignment_node ?? target.node,task:assignment_task ?? target.task};
}

export function withTaskScope<T extends ProjectRoute>(route:T,all:boolean):T {
 return {...route,section:all ? 'all-tasks' : undefined,all_tasks:undefined};
}

const TASK_FILTER_KEYS=['pending','unassigned','blocked','mine','overdue'] as const;
export type TaskFilterKey=typeof TASK_FILTER_KEYS[number];
export function taskFilters(route:Pick<ProjectRoute,'task_filters'>):Record<TaskFilterKey,boolean> {
 const active=new Set(route.task_filters?.split(','));
 return {pending:active.has('pending'),unassigned:active.has('unassigned'),blocked:active.has('blocked'),mine:active.has('mine'),overdue:active.has('overdue')};
}
export function withTaskFilter<T extends ProjectRoute>(route:T,key:TaskFilterKey,on:boolean):T {
 const next={...taskFilters(route),[key]:on};
 return {...route,task_filters:TASK_FILTER_KEYS.filter(k=>next[k]).join(',') || undefined};
}
