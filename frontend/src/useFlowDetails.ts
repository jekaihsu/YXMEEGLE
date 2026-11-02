import {useEffect,useRef,useState} from 'react';
import {useCaseData} from './detailRefresh';
import {getSessionEpoch} from './api';
import {NodeAssignmentError,assignmentErrorMessage,overviewDetail,type NodeAssignmentDetail,type NodeAssignmentList} from './nodeAssignmentApi';
import {cachedNodeAssignmentDetail,prefetchNodeAssignmentDetail} from './useNodeAssignments';
export function useFlowDetails(projectId:string,list:NodeAssignmentList|undefined,selected:string,all:boolean,version:number){
 const owner=useCaseData();
 const scope=useRef({projectId,epoch:getSessionEpoch()});
 const [loaded,setLoaded]=useState<Record<string,NodeAssignmentDetail>>({});
 const [errors,setErrors]=useState<Record<string,string>>({});
 if(scope.current.projectId!==projectId||scope.current.epoch!==getSessionEpoch()){scope.current={projectId,epoch:getSessionEpoch()};setLoaded({});setErrors({})}
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
   void prefetchNodeAssignmentDetail(projectId,node.key,node.revision,force,owner).then(detail=>{if(active && epoch===getSessionEpoch()){setLoaded(data=>({...data,[node.key]:detail}));setErrors(data=>{const next={...data};delete next[node.key];return next})}}).catch(error=>{if(active&&epoch===getSessionEpoch()){if(error instanceof NodeAssignmentError&&[401,403,404].includes(error.status))setLoaded(data=>{const next={...data};delete next[node.key];return next});setErrors(data=>({...data,[node.key]:assignmentErrorMessage(error)}))}});
  }
  return()=>{active=false};
 },[projectId,list,selected,all,version,retry,owner]);
 const details=Object.fromEntries((list?.nodes || []).flatMap(node=>{const embedded=list && overviewDetail(list,node);const stored=loaded[node.key] ?? cachedNodeAssignmentDetail(projectId,node.key,owner);const detail=embedded || (stored?.node.revision===node.revision ? stored : undefined);return detail ? [[node.key,detail]] : []}));
 const visibleErrors=Object.fromEntries(Object.entries(errors).filter(([key])=>!list?.node_details?.[key]));
 return {details,errors:visibleErrors,retry:()=>setRetry(v=>v+1)};
}
