import {isProductionNode} from './nodeAssignmentApi';
import type {AssignmentTask} from './nodeAssignmentApi';
import type {LinkBasis, ProductionStage} from './projectProgressApi';
import {departmentLabels} from './workItemsModel';
import type {FlowNode} from './flowModel';
import {gapHint} from './projectProgressView';

export type ProductionPlan = {
 source:'evidence'|'task-detail'; quantity:string|null; lines:number|null; items:number|null;
 basis:{key:LinkBasis; count:number}[];
};
export function isProductionSeedTask(task:Pick<AssignmentTask,'title'|'detail'>, nodeKey:string) {
 if(!isProductionNode(nodeKey))return false;
 return task.title.trim()===`${departmentLabels[nodeKey]}：依計畫數量完成` ||
  task.detail?.split('\n').some(line=>line.trim()===`[SOP-START:v1:${nodeKey}]`)===true;
}
export function productionPlanFacts(task:Pick<AssignmentTask,'title'|'detail'>, nodeKey:string, stage?:ProductionStage):ProductionPlan|null {
 if(!isProductionSeedTask(task,nodeKey))return null;
 if(stage){
  const planned=stage.planned;
  return {source:'evidence',quantity:planned?.qty || null,lines:planned?.lines ?? null,items:planned?.items ?? null,
   basis:planned ? Object.entries(planned.basis).flatMap(([key,count])=>isLinkBasis(key) ? [{key,count}] : []) : []};
 }
 const detail=(task.detail || '').replace(/\[SOP-START:[^\]\n]*\]/g,'');
 const count=(label:string)=>{const value=detail.match(new RegExp(`${label}[：:]?\\s*(\\d+)(?=\\s|[、；;]|$)`))?.[1];return value===undefined ? null : Number(value)};
 const quantity=detail.match(/(?:^|\n)計畫數量[：:]\s*([+-]?\d+(?:\.\d+)?)(?=\s|$)/)?.[1] ?? null;
 const basis=([['native','原生'],['derived','推導'],['ambiguous','待確認'],['unlinked','未連結']] satisfies [LinkBasis,string][])
  .flatMap(([key,label])=>{const value=count(label);return value===null ? [] : [{key,count:value}]});
 return {source:'task-detail',quantity,lines:count('合約明細'),items:count('工項'),basis};
}
function isLinkBasis(key:string):key is LinkBasis {
 return key==='native' || key==='derived' || key==='ambiguous' || key==='unlinked';
}
export function productionPlanGaps(node:FlowNode) {
 const stage=node.production;
 if(!stage)return [];
 return [
  ...(node.quantity.actual===null ? [{key:'actual',title:'實際完成量未知',why:`${node.quantity.reason || '來源尚無可確認的完成量'}。不代表尚未施工，也無法計算工程量完成百分比。`,fix:gapHint('no_daily_linked')}] : []),
  ...(stage.planned && stage.planned.needs_review>0 ? [{key:'plan',title:'合約明細待核對',why:`來源有 ${stage.planned.needs_review} 筆明細待人工確認，未計入可信計畫。`,fix:'請 PM 在 Lark 工程確認單核對重複明細。'}] : []),
  ...(stage.items.some(item=>item.link_basis==='ambiguous' || item.link_basis==='unlinked') ? [{key:'links',title:'工項關聯待核對',why:'部分工項尚無唯一合約關聯，不計入可信完成率。',fix:'請在 Lark 工項指定對應合約工項。'}] : []),
  ...node.gaps.filter(gap=>gap!==node.quantity.reason).map(gap=>({key:gap,title:'節點待核對',why:gap,fix:'請節點主管在 Lark 節點指派與來源紀錄核對後更新。'})),
 ];
}
