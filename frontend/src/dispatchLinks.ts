import type {DispatchSlot} from './dispatchBoardModel';
import type {Project} from './types';
import {homeHref} from './homeLayout';
export type DispatchProject = Pick<Project,'id'|'code'|'name'>;
export function dispatchCaseHref(subject:DispatchSlot['case'],projects:DispatchProject[]):string|null {
 const code=subject.code?.trim(),name=subject.name?.trim();
 const matches=projects.filter(project=>(code&&project.code===code)||(name&&project.name===name));
 return matches.length===1&&(!code||matches[0].code===code)?homeHref({view:'project',project:matches[0].id,tab:'flow'}):null;
}

export function parseDispatchProjects(value:unknown):DispatchProject[]|null {
 if(!value||typeof value!=='object'||!('items' in value)||!Array.isArray(value.items)||!('total' in value)||value.total!==value.items.length)return null;
 const projects:DispatchProject[]=[];
 for(const item of value.items){
  if(!item||typeof item!=='object'||!('id' in item)||typeof item.id!=='string'||!('code' in item)||typeof item.code!=='string'||!('name' in item)||typeof item.name!=='string')return null;
  projects.push({id:item.id,code:item.code,name:item.name});
 }
 return projects;
}
