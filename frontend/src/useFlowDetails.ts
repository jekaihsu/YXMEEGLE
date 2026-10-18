import {useEffect,useRef,useState} from 'react';
import {getSessionEpoch} from './api';
import {assignmentErrorMessage,overviewDetail,type NodeAssignmentDetail,type NodeAssignmentList} from './nodeAssignmentApi';
import {prefetchNodeAssignmentDetail} from './useNodeAssignments';
export function useFlowDetails(projectId:string,list:NodeAssignmentList|undefined,selected:string,all:boolean,version:number){
 const [loaded,setLoaded]=useState<Record<string,NodeAssignmentDetail>>({});
 const [errors,setErrors]=useState<Record<string,string>>({});
 const [retry,setRetry]=useState(0);
 const previous=useRef({version,retry});
 useEffect(()=>{
  if(!list)return;
  const force=(version>1 && previous.current.version!==version) || previous.current.retry!==retry;
  previous.current={version,retry};
  let active=true;const epoch=getSessionEpoch();
  const nodes=all ? list.nodes : list.nodes.filter(n=>n.key===selected);
  for(const node of nodes){
   if(overviewDetail(list,node))continue;
   void prefetchNodeAssignmentDetail(projectId,node.key,node.revision,force).then(detail=>{if(active && epoch===getSessionEpoch()){setLoaded(data=>({...data,[node.key]:detail}));setErrors(data=>{const next={...data};delete next[node.key];return next})}}).catch(error=>{if(active && epoch===getSessionEpoch())setErrors(data=>({...data,[node.key]:assignmentErrorMessage(error)}))});
  }
  return()=>{active=false};
 },[projectId,list,selected,all,version,retry]);
 const details=Object.fromEntries((list?.nodes || []).flatMap(node=>{const embedded=list && overviewDetail(list,node);const stored=loaded[node.key];const detail=embedded || (stored?.node.revision===node.revision ? stored : undefined);return detail ? [[node.key,detail]] : []}));
 const visibleErrors=Object.fromEntries(Object.entries(errors).filter(([key])=>!list?.node_details?.[key]));
 return {details,errors:visibleErrors,retry:()=>setRetry(v=>v+1)};
}
