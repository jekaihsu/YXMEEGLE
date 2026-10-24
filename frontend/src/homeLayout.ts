import {canReadDispatch} from './dispatchAccess';
import type {Session} from './types';
import {REPORT_CARDS,canReadHomeReports,isReportCard} from './homeReportCards';
export const HOME_VIEWS={mine:{label:'我的工作'},assign:{label:'分配工作'},company:{label:'全公司'}} as const;
export type HomeViewId=keyof typeof HOME_VIEWS;
export const HOME_SECTIONS={todo:{label:'需要處理',hint:'需要你決定或追蹤的項目'},quality:{label:'品質',hint:'PM 週報 · 檢核品質'},business:{label:'業務',hint:'PM 週報 · 請款與應收'},progress:{label:'進度',hint:'預排達成與各組工作概況'},resources:{label:'資源',hint:'PM 週報 · 儀器與車輛'},people:{label:'人',hint:'本週出勤與人員工作安排'},shortcuts:{label:'捷徑',hint:'開啟完整管理頁面'}} as const;
export type HomeSectionId=keyof typeof HOME_SECTIONS;
export const SECTION_ORDER:Record<HomeViewId,HomeSectionId[]>={mine:['todo'],assign:['people','todo'],company:['todo','quality','business','progress','resources','people','shortcuts']};
type CardDefinition={section:HomeSectionId|null;title:string;description:string;views:HomeViewId[];kind:'kpi'|'table'|'chart'};
const reportCards=Object.fromEntries(Object.entries(REPORT_CARDS).map(([id,card])=>[id,{...card,views:['company'],kind:'chart'}])) as {[K in keyof typeof REPORT_CARDS]:typeof REPORT_CARDS[K]&{views:['company'];kind:'chart'}};
export const HOME_CARDS={
 ...reportCards,
 dispatch:{section:'todo',title:'派工看板',description:'本週待派與重疊預排，保留來源缺口',views:['mine','assign','company'],kind:'table'},
 mycases:{section:'todo',title:'我的案件',description:'你負責或參與的案件',views:['mine'],kind:'table'},
 kpi:{section:null,title:'工作摘要',description:'目前視圖的重點數字',views:['mine', 'assign', 'company'],kind:'kpi'},
 work:{section:'todo',title:'我的工作',description:'依急迫程度排序的工作與期限',views:['mine', 'assign'],kind:'table'},
 confirmation:{section:'todo',title:'待我確認',description:'需要你覆核或確認的事項',views:['mine', 'company'],kind:'table'},
 deadlines:{section:'todo',title:'未來七天期限',description:'每天到期的工作數',views:['mine'],kind:'chart'},
 allocation:{section:'todo',title:'待分配與待審核',description:'所管理組別的指派與覆核',views:['assign'],kind:'table'},
 workload:{section:'people',title:'組員工作量',description:'各組員的未完成工作與逾期數',views:['assign'],kind:'chart'},
 delegated:{section:'todo',title:'我交辦的',description:'追蹤交辦內容與目前進度',views:['assign'],kind:'table'},
 groups:{section:'progress',title:'各組工作量',description:'已完成、未完成與逾期任務',views:['company'],kind:'chart'},
 cases:{section:'todo',title:'需留意案件',description:'逾期與待確認案件優先',views:['company'],kind:'table'},
 statuses:{section:'progress',title:'案件狀態分布',description:'工作台執行狀態',views:['company'],kind:'chart'},
 links:{section:'shortcuts',title:'管理捷徑',description:'開啟完整管理頁面',views:['company'],kind:'table'},
 leave:{section:'people',title:'今日請假',description:'今天已核實的請假人員',views:['mine', 'company'],kind:'table'},
 trips:{section:'people',title:'今日出差',description:'今天的出差人員與期間',views:['mine', 'company'],kind:'table'},
 absence:{section:'people',title:'本週出勤',description:'週一至週五的人員出勤',views:['assign','company'],kind:'table'},
 impact:{section:'people',title:'缺席影響',description:'缺席人員手上的未完成工作',views:['assign'],kind:'table'},
} satisfies Record<string,CardDefinition>;
export type HomeCardId=keyof typeof HOME_CARDS;
export type HomeLayout={order:HomeCardId[];hidden:HomeCardId[]};
export type HomeSettings={version:2;view:HomeViewId|null;layouts:Record<HomeViewId,HomeLayout>};
export const DEFAULT_LAYOUT:Record<HomeViewId,HomeLayout>={
 mine:{order:['kpi','work','mycases'],hidden:[]},
 assign:{order:['kpi','allocation','workload','delegated','absence','impact','work','dispatch'],hidden:[]},
 company:{order:['kpi','attention','confirmation','cases','qualityTrend','qualityGroups','funnel','receivables','achievement','statuses','groups','instruments','vehicles','leave','trips','absence','links','dispatch'],hidden:[]},
};
type PersonaUser={role?:string|null;department?:string|null}|null|undefined;
const companyPersona=(user:PersonaUser)=>!!user&&(user.role==='pm'||user.role==='manager'||/專案|PM|業務|管理/i.test(user.department||''));
export function availableViews(user:PersonaUser,managerViewAvailable:boolean|null):HomeViewId[]{
 return ['mine'];
}
export function resolvePersona(user:PersonaUser,managerViewAvailable:boolean|null):HomeViewId{return availableViews(user,managerViewAvailable)[0]}
export function defaultHomeLayout(view:HomeViewId='mine'):HomeLayout{return {order:[...DEFAULT_LAYOUT[view].order],hidden:[...DEFAULT_LAYOUT[view].hidden]}}
export function parseHomeLayout(raw:string|null):HomeSettings{
 const fallback:HomeSettings={version:2,view:null,layouts:{mine:defaultHomeLayout('mine'),assign:defaultHomeLayout('assign'),company:defaultHomeLayout('company')}};
 try{
  const value=JSON.parse(raw||'null');
  if(value?.version!==2)return fallback;
  if(typeof value.view==='string'&&Object.hasOwn(HOME_VIEWS,value.view))fallback.view=value.view as HomeViewId;
  for(const view of Object.keys(HOME_VIEWS) as HomeViewId[]){
   const layout=value.layouts?.[view];
   if(!Array.isArray(layout?.order)||!Array.isArray(layout?.hidden))continue;
   const valid=(id:unknown):id is HomeCardId=>typeof id==='string'&&DEFAULT_LAYOUT[view].order.includes(id as HomeCardId);
   const order=[...new Set<HomeCardId>(layout.order.filter(valid))];
   fallback.layouts[view]={order:[...order,...DEFAULT_LAYOUT[view].order.filter(id=>!order.includes(id))],hidden:[...new Set<HomeCardId>(layout.hidden.filter(valid))]};
  }
  return fallback;
 }catch{return fallback}
}
export function moveHomeCard(layout:HomeLayout,id:HomeCardId,direction:-1|1,available:HomeCardId[]=layout.order):HomeLayout{
 if(id==='attention'||!available.includes(id))return layout;
 const order=[...layout.order],index=order.indexOf(id),siblings=order.filter(card=>card!=='attention'&&available.includes(card)&&HOME_CARDS[card].section===HOME_CARDS[id].section),neighbour=siblings[siblings.indexOf(id)+direction];
 if(index<0||!neighbour)return layout;
 const next=order.indexOf(neighbour);
 [order[index],order[next]]=[order[next],order[index]];
 return {...layout,order};
}
export function homeLayoutKey(workspace:string,user:string,role:string,mode:string):string{return 'yx.home.v2:'+JSON.stringify([workspace,user,role,mode])}
export const homeHref=(target:Record<string,string|undefined>):string=>'#'+new URLSearchParams(Object.entries(target).filter((entry):entry is [string,string]=>entry[1]!==undefined)).toString();
export const taipeiToday=()=>new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Taipei'});
export function deadlineLabel(deadline:string|null|undefined):string {
 if(!deadline)return '期限待確認';
 return `期限 ${deadline.slice(0,10).replaceAll('-','/')}`;
}

export function homeSections(view:HomeViewId,layout:HomeLayout){
 return SECTION_ORDER[view].map(id=>({id,...HOME_SECTIONS[id],cards:layout.order.filter(card=>HOME_CARDS[card].section===id&&!layout.hidden.includes(card)).sort((a,b)=>Number(b==='attention')-Number(a==='attention'))})).filter(section=>section.cards.length);
}

export function availableCardIds(view:HomeViewId,user:PersonaUser,reportsState:{unavailable:boolean},session?:Session):HomeCardId[]{
 return DEFAULT_LAYOUT[view].order.filter(id=>id==='dispatch'?canReadDispatch(session):!isReportCard(id)||canReadHomeReports(user?.role)&&!reportsState.unavailable);
}
