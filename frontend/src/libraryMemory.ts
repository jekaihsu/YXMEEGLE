import type {CaseFilters} from './projectsListModel';
const KEY='yx.library.state.v1';
export type LibraryMemory={scope:string;filters:CaseFilters;view:string;expanded:string[];scrollY:number};
export function readLibraryMemory(scope:string,storage:Pick<Storage,'getItem'>=window.sessionStorage):LibraryMemory|undefined {
 try{
  const value=JSON.parse(storage.getItem(KEY)||'null');
  if(!value||value.scope!==scope||typeof value.filters!=='object'||typeof value.view!=='string'||!Array.isArray(value.expanded))return undefined;
  return {scope,filters:value.filters,view:value.view,expanded:value.expanded.filter((x:unknown)=>typeof x==='string'),scrollY:Number.isFinite(value.scrollY)?Math.max(0,value.scrollY):0};
 }catch{return undefined}
}
export function writeLibraryMemory(memory:LibraryMemory,storage:Pick<Storage,'setItem'>=window.sessionStorage){
 try{storage.setItem(KEY,JSON.stringify(memory))}catch{}
}
