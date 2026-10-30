type Listener=(nodeKey:string,taskId:string)=>void;
const listeners=new Set<Listener>();
let pending:{nodeKey:string;taskId:string}|null=null;
export const assignRequests={
 request(nodeKey:string,taskId:string){pending={nodeKey,taskId};for(const l of [...listeners])l(nodeKey,taskId)},
 subscribe(listener:Listener){listeners.add(listener);if(pending){const {nodeKey,taskId}=pending;pending=null;queueMicrotask(()=>listener(nodeKey,taskId))}return()=>{listeners.delete(listener)}},
 consume(){pending=null},
};
