import type {Route} from './types';
import {normalizeRoute} from './api';
import {isP2View} from './p2RouteNames';

function shared<T>(load:()=>Promise<T>){
 let pending:Promise<T>|undefined;
 return ()=>pending??(pending=load().catch(error=>{pending=undefined;throw error}));
}

export const routeLoaders={
 Assistant:shared(()=>import('./Assistant')),
 HowToUse:shared(()=>import('./HowToUse').then(m=>({default:m.HowToUse}))),
 Projects:shared(()=>import('./ProjectsList').then(m=>({default:m.Projects}))),
 AdministrationEntry:shared(()=>import('./Operations').then(m=>({default:m.AdministrationEntry}))),
 Routines:shared(()=>import('./Operations').then(m=>({default:m.Routines}))),
 DispatchPage:shared(()=>import('./DispatchWorkflowPage').then(m=>({default:m.DispatchWorkflowPage}))),
 LegacyTabs:shared(()=>import('./IntegratedPages').then(m=>({default:m.LegacyTabs}))),
 SourceHealthPage:shared(()=>import('./IntegratedPages').then(m=>({default:m.SourceHealthPage}))),
 WorkPage:shared(()=>import('./IntegratedPages').then(m=>({default:m.WorkPage}))),
 PeopleAttendancePanel:shared(()=>import('./PeopleDirectoryPanel').then(m=>({default:m.PeopleAttendancePanel}))),
 LarkPilotPanel:shared(()=>import('./LarkPilotPanel').then(m=>({default:m.LarkPilotPanel}))),
 Quotes:shared(()=>import('./Quotes').then(m=>({default:m.Quotes}))),
 AssignedSopTaskPage:shared(() => import('./AssignedSopTaskPage')),
 ProjectDetailGate:shared(() => import('./ProjectDetail').then(module => ({default: module.ProjectDetailGate}))),
 MyWorkBoard:shared(() => import('./MyWorkBoard').then(module => ({default: module.MyWorkBoard}))),
 TaskTimeline:shared(() => import('./TaskTimeline')),
 P2Page:shared(() => import('./P2Pages').then(module => ({default: module.P2Page}))),
 StageFixture:shared(()=>import('./StageFixture').then(m=>({default:m.StageFixture}))),
 ReportsPage:shared(() => import('./reports/ReportsPage'))
};

export function prefetchRoute(input:Route){
 const route=normalizeRoute(input);
 const name=route.view==='assistant'?'Assistant':route.view==='howto'?'HowToUse':route.view==='projects'?'Projects':route.view==='admin'?'AdministrationEntry':route.view==='routines'?'Routines':route.view==='dispatch'?'DispatchPage':route.view==='work'?'WorkPage':route.view==='sources'?'SourceHealthPage':route.view==='people'?'PeopleAttendancePanel':route.view==='quotes'?'Quotes':route.view==='reports'?'ReportsPage':route.view==='project'?(route.section==='assigned-sop'&&route.task_source==='sop_local'?'AssignedSopTaskPage':'ProjectDetailGate'):isP2View(route.view)?'P2Page':undefined;
 if(name)void routeLoaders[name]().catch(()=>{});
}

export function createRoutePrefetch(){
 let timer:ReturnType<typeof setTimeout>|undefined;
 const cancel=()=>{clearTimeout(timer);timer=undefined};
 return {cancel,schedule:(route:Route)=>{cancel();timer=setTimeout(()=>prefetchRoute(route),120)}};
}
