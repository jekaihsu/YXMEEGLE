import {isPlainDecimal} from './caseDetailView';
import type {LinkBasis, ProductionKey, ProductionStage, ProjectProgress} from './projectProgressApi';

export const departmentLabels: Record<ProductionKey, string> = {field:'外業', control:'控制', mapping:'圖資', report:'報告'};
export const basisLabels: Record<LinkBasis, string> = {native:'原生關聯', derived:'推導關聯', ambiguous:'關聯有歧義', unlinked:'未關聯'};
export const basisExplanations: Record<LinkBasis, string> = {
 native:'來源直接連結此工項。', derived:'來源依工編推導合約關係，並非原生關聯；本頁仍以工項 ID 識別，不以重複工編連結任務。',
 ambiguous:'有多筆可能的合約關係，待人工核對。此工項不計入可信完成率。', unlinked:'來源尚未連結合約工項，此工項不計入可信完成率。',
};
export type ProductionItem = ProductionStage['items'][number];
export type WorkItemRow = {
 id:string; code:string; name:string; planned:string; actualDisplay:'未知'; progressDisplay:string;
 basis:LinkBasis; verified:boolean; points:{planned:number; earned:number}|null; source:ProductionItem;
};
export const percentDisplay = (value:number) => `${Math.round(value * 10) / 10}%`;
export function workItemRows(stage:ProductionStage, stale=false):WorkItemRow[] {
 return stage.items.map(item => {
  const planned=isPlainDecimal(item.planned_points) ? Number(item.planned_points) : NaN;
  const remaining=isPlainDecimal(item.remaining_points) ? Number(item.remaining_points) : NaN;
  const verified=!stale && (item.link_basis==='native' || item.link_basis==='derived') && (item.status==='done' || item.status==='partial') && Number.isFinite(planned) && Number.isFinite(remaining) && planned>0 && remaining>=0 && remaining<=planned;
  const points=verified ? {planned,earned:planned-remaining} : null;
  return {id:item.item_id,code:item.code || '尚未提供',name:item.name || '未命名工項',planned:item.planned_qty ?? '尚未提供',actualDisplay:'未知',progressDisplay:points ? `點數完成率 ${percentDisplay(points.earned / points.planned * 100)}` : '未知',basis:item.link_basis,verified,points,source:item};
 });
}
export function workItemsAggregate(stage:ProductionStage, rows:WorkItemRow[]) {
 const complete=!stage.items_truncated && rows.length===stage.items_total && rows.length>0 && rows.every(row=>row.verified && row.points);
 if(!complete)return {percent:null,label:'完成率未知'};
 const planned=rows.reduce((sum,row)=>sum+(row.points?.planned ?? 0),0),earned=rows.reduce((sum,row)=>sum+(row.points?.earned ?? 0),0);
 const percent=earned/planned*100;
 return {percent,label:`點數完成率 ${percentDisplay(percent)}（${rows.length} 筆工項）`};
}
export function workItemsTruncation(stage:ProductionStage) {
 return stage.items_truncated ? `僅顯示 ${stage.items.length}／${stage.items_total} 筆工項，清單未完整，完成率未知。` : null;
}
export function departmentItems(data:ProjectProgress, department:ProductionKey, stale=false) {
 const stage=data.production[department],rows=workItemRows(stage,stale);
 return {stage,rows,aggregate:workItemsAggregate(stage,rows),truncation:workItemsTruncation(stage)};
}
