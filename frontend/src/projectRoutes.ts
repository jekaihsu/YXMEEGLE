export const PROJECT_TABS=[{key:'overview',label:'總覽'},{key:'flow',label:'流程與任務'},{key:'items',label:'工項與進度'},{key:'people',label:'排程與人員'},{key:'files',label:'文件與交付'},{key:'data',label:'案件資料'}] as const;
type ProjectRoute={tab?:string;section?:string;node?:string;task?:string;focus?:string;approval?:string;comment?:string;all_tasks?:string};
export function projectFlowRoute(route:ProjectRoute){
 const original=route.tab || (route.node || route.task || route.focus ? 'flow' : route.approval ? 'data' : route.comment ? 'data' : 'overview');
 const aliases:Record<string,string>={tasks:'flow',progress:'items',daily:'items',logs:'data'};
 const tab=original==='data' && route.section==='files' ? 'files' : aliases[original] || original;
 const section=route.section || (original==='tasks' ? 'all-tasks' : original==='daily' ? 'reports' : original==='logs' || !route.tab && route.comment ? 'activity' : !route.tab && route.approval ? 'approvals' : undefined);
 const allTasks=original==='tasks' || section==='all-tasks' || route.all_tasks==='1';
 return {tab,focus:allTasks ? 'tasks' : 'node',allTasks,...(section ? {section} : {})};
}
