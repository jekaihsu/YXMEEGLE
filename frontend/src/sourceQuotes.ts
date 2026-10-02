import type {Project,Workspace,Quote} from './types';

export function projectQuotes(w:Workspace,p:Project):Quote[]{
 const confirmations=(w.source_confirmations||[]).filter((row:any)=>row.project_id===p.id);
 const entities=(w.source_quotes||[]).filter((row:any)=>row.project_id===p.id||row.project_ids?.includes(p.id)||confirmations.some((c:any)=>c.quote_ids?.includes(row.id)||row.confirmation_ids?.includes(c.id)));
 if(!entities.length)return p.quotes||[];
 return entities.map((row:any)=>{const previous=p.quotes?.find(q=>q.id===row.review_quote_id);return {...row,id:previous?.id||row.id,quote_code:row.code,engineering_code:previous?.engineering_code,review_available:!!previous&&row.review_project_ids?.includes(p.id),confirmation_count:row.confirmation_ids?.length||0}});
}
