import {projectQuotes} from './sourceQuotes';
import type {Project,Workspace} from './types';

const rows=(value:unknown):{id?:string;project_id?:string;confirmation_ids?:string[];task_refs?:{project_id?:string}[]}[]=>Array.isArray(value)?value.filter(row=>!!row&&typeof row==='object'):[];

const SOURCE_KINDS:Record<string,string>={demo:'獨立示範資料',lark:'Lark',v4:'報價總表／V4',meegle:'Meegle'};
/** 資料來源 shown in 案件資料. Only kinds this app knows get a name; anything else is flagged for review instead of being passed off as a known source. */
export function sourceKindLabel(kind:unknown):string{
 const key=typeof kind==='string'?kind.trim():'';
 return SOURCE_KINDS[key]||(key?`來源類型待核對（${key}）`:'來源類型待核對');
}

/** 案件資料 destinations. An empty one is hidden only when the source read is verified (demo or ready); an unknown read keeps it so 「尚未讀取」 is never mistaken for 「沒有」. 參與人員 and 附件索引 live in their own tabs. */
export function caseDataSections(w:Workspace,p:Project,current:string):[string,string][]{
 const verified=p.source_kind==='demo'||w.source_status?.status==='ready';
 const quotes=projectQuotes(w,p).length;
 const confirmations=rows(w.source_confirmations).filter(r=>r.project_id===p.id);
 const contracts=confirmations.length+rows(w.contract_items).filter(r=>r.project_id===p.id||r.task_refs?.some(ref=>ref.project_id===p.id)||r.confirmation_ids?.some(id=>confirmations.some(c=>c.id===id))).length;
 const code=p.parent_code||p.code;
 const family=w.projects.some(x=>x.id!==p.id&&x.case_type!=='intake'&&(x.code===code||x.parent_code===code));
 const hide=(section:string,count:number|boolean)=>verified&&!count&&current!==section;
 return ([
  ['basic','基本資料'],
  ...(hide('quotes',quotes)?[]:[['quotes',`報價（${quotes}）`]]),
  ...(hide('contracts',contracts)?[]:[['contracts','確認單與合約工項']]),
  ...(hide('family',family)?[]:[['family','母子案']]),
  ['approvals','審批與變更'],
  ['activity','討論與紀錄'],
  ['sources','資料來源與同步'],
 ] as [string,string][]);
}
