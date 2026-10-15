export const HOME_CARDS = [
 {id:'work',title:'我的工作',description:'指派給你的工作、案件與期限'},
 {id:'confirmation',title:'待我確認',description:'需要你覆核或確認的具體事項'},
 {id:'cases',title:'案件與期限',description:'授權案件的名稱、負責人與交付期限'},
 {id:'leave',title:'今日請假',description:'今天已核實的請假人員'},
 {id:'trips',title:'今日出差',description:'今天的出差人員與期間'},
 {id:'delegated',title:'我交辦的',description:'追蹤交辦內容與目前進度'},
 {id:'proxy',title:'代理工作',description:'目前指派給你的代理工作'},
 {id:'local',title:'本地 SOP 工作',description:'工作台內的作業與交接'},
] as const;
export type HomeCardId=typeof HOME_CARDS[number]['id'];
export type HomeLayout={order:HomeCardId[];hidden:HomeCardId[]};
const valid=(id:unknown):id is HomeCardId=>HOME_CARDS.some(card=>card.id===id);
export function defaultHomeLayout(role?:string):HomeLayout {
 const main:HomeCardId[]=['work','confirmation','cases','leave','trips'];
 return {order:[...main,'delegated','proxy','local'],hidden:['delegated','proxy','local']};
}
export function parseHomeLayout(raw:string|null,role?:string):HomeLayout {
 const fallback=defaultHomeLayout(role);
 try {
  const value=JSON.parse(raw||'null');
  if(value?.version!==1||!Array.isArray(value.order)||!Array.isArray(value.hidden))return fallback;
  const order:HomeCardId[]=[...new Set(value.order.filter(valid))] as HomeCardId[];
  return {order:[...order,...fallback.order.filter(id=>!order.includes(id))],hidden:[...new Set(value.hidden.filter(valid))] as HomeCardId[]};
 }catch{return fallback}
}
export function moveHomeCard(layout:HomeLayout,id:HomeCardId,direction:-1|1):HomeLayout {
 const order=[...layout.order],index=order.indexOf(id),next=index+direction;
 if(index<0||next<0||next>=order.length)return layout;
 [order[index],order[next]]=[order[next],order[index]];
 return {...layout,order};
}
export function homeLayoutKey(workspace:string,user:string,role:string,mode:string):string {
 return 'yx.home.v1:'+JSON.stringify([workspace,user,role,mode]);
}
export const homeHref=(target:Record<string,string|undefined>):string=>'#'+new URLSearchParams(Object.entries(target).filter((entry):entry is [string,string]=>entry[1]!==undefined)).toString();
export const taipeiToday=()=>new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Taipei'});
export function deadlineLabel(deadline:string|null|undefined):string {
 if(!deadline)return '期限待確認';
 return `期限 ${deadline.slice(0,10).replaceAll('-','/')}`;
}
