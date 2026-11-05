import {buildFlowModel} from './flowModel';
import {withLocalChecklist} from './nodeWorkbenchModel';
import {useFlowDetails} from './useFlowDetails';
import {useProjectProgress} from './useProjectProgress';
import type {Ctx} from './appCommon';
import type {Project} from './types';
import type {useNodeAssignments} from './useNodeAssignments';
import type {useSopTasks} from './useSopTasks';

/** Same page-owned snapshot and merge for the header, overview and node workspace. */
export function useCaseFlowModel(c:Ctx,p:Project,assignments:ReturnType<typeof useNodeAssignments>,sop:ReturnType<typeof useSopTasks>,selected:string,all:boolean){
 const read=useProjectProgress(p.id);
 const list='data' in assignments.state?assignments.state.data:undefined;
 const details=useFlowDetails(p.id,list,selected,all,assignments.revision);
 const merged=list?{...list,node_details:{...list.node_details,...Object.fromEntries(Object.entries(details.details).map(([key,d])=>[key,{tasks:d.tasks,assignable_people:d.assignable_people}]))}}:undefined;
 const data=read.state.kind==='ready'&&read.state.data.project_id===p.id?read.state.data:undefined;
 const isLegacy=assignments.state.kind==='disabled';
 const flow=buildFlowModel({project:isLegacy?p:{...p,nodes:[]},assignments:merged,progress:data,today:c.w.as_of,users:c.w.users});
 const sopData='data' in sop.state?sop.state.data:undefined;
 const model={...flow,nodes:withLocalChecklist(flow.nodes,sopData,sop.assignees)};
 return {read,list,details,merged,isLegacy,sopData,model};
}
