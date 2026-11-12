import {useCallback, useEffect, useRef, useState} from 'react';
import {getSessionEpoch, onSessionEpochChange} from './api';
import type {PageData, FetchIntent} from './pageData';
import {type CaseSnapshot, useCaseData, caseKey, readCase, seedCase, useDetailRefresh, useCaseWrite, caseIntent} from './detailRefresh';
import {assignmentErrorMessage, assignmentsDisabled, assignmentRequest, parseNodeAssignments, overviewDetail, mutateNodeAssignment, NodeAssignmentError, requestId, type AssignmentMutation, type NodeAssignmentDetail, type NodeAssignmentList} from './nodeAssignmentApi';

const intentHeaders=(intent:FetchIntent)=>({'X-YX-Fetch-Intent':intent.reason,'X-YX-Fetch-Generation':'id' in intent?intent.id:'initial'});
const assignmentPath=(id:string)=>`/api/projects/${encodeURIComponent(id)}/node-assignments`;
function loadList(id:string,current:()=>boolean,intent:FetchIntent,signal:AbortSignal){return assignmentRequest(assignmentPath(id),{signal,cache:'no-store',headers:intentHeaders(intent)},current).then(parseNodeAssignments)}
async function loadDetail(id:string,nodeKey:string,current:()=>boolean,intent:FetchIntent,signal:AbortSignal){
 const raw=await assignmentRequest(`${assignmentPath(id)}/nodes/${encodeURIComponent(nodeKey)}`,{signal,cache:'no-store',headers:intentHeaders(intent)},current);
 if(!raw||typeof raw!=='object')throw new NodeAssignmentError(0,'節點資料格式待核對');
 const body=raw as Record<string,unknown>;
 const list=parseNodeAssignments({...body,stale:false,code:'',nodes:[body.node],can:{[nodeKey]:body.can},node_details:{[nodeKey]:{tasks:body.tasks,assignable_people:body.assignable_people}}});
 if(list.nodes[0].key!==nodeKey)throw new NodeAssignmentError(0,'節點資料不符');
 return overviewDetail(list,list.nodes[0])!;
}
export const ASSIGNMENT_CACHE_LIMIT=100;
class AssignmentCache<T> extends Map<string,T>{
 override get(key:string){const value=super.get(key);if(value!==undefined){super.delete(key);super.set(key,value)}return value}
 override set(key:string,value:T){super.delete(key);super.set(key,value);while(this.size>ASSIGNMENT_CACHE_LIMIT)super.delete(this.keys().next().value!);return this}
}
const lists = new AssignmentCache<NodeAssignmentList>();
const details = new AssignmentCache<{data:NodeAssignmentDetail;readAt:number}>();
onSessionEpochChange(()=>{lists.clear();details.clear()});
export const assignmentCacheSizes=()=>({lists:lists.size,details:details.size});
export function prefetchNodeAssignmentDetail(projectId:string,nodeKey:string,expectedRevision?:string|null,force:boolean|FetchIntent=false,owner?:PageData):Promise<NodeAssignmentDetail> {
 const key=caseKey(owner,`${projectId}/${nodeKey}`);
 const stored=details.get(key);
 const changed=!!stored&&expectedRevision!==undefined&&stored.data.node.revision!==expectedRevision;
 return readCase(owner,`${projectId}/${nodeKey}`,force||changed,(current,intent,signal)=>loadDetail(projectId,nodeKey,current,intent,signal)).then(data=>{details.set(key,{data,readAt:Date.now()});return data}).catch(error=>{if(error instanceof NodeAssignmentError&&[401,403,404].includes(error.status))details.delete(key);throw error});
}
function cached(projectId:string,owner?:PageData){return lists.get(caseKey(owner,projectId))}
export function prefetchNodeAssignments(projectId:string,force:boolean|symbol=false,owner?:PageData):Promise<NodeAssignmentList> {
 return readCase(owner,projectId,force,(current,intent,signal)=>loadList(projectId,current,intent,signal)).then(data=>{lists.set(caseKey(owner,projectId),data);return data});
}
export function seedNodeAssignments(id:string,data:NodeAssignmentList,owner?:PageData,meta?:CaseSnapshot,batch?:symbol){lists.set(caseKey(owner,id),data);seedCase(owner,id,data,(current,intent,signal)=>loadList(id,current,intent,signal),true,meta,batch)}
export type AssignmentListState = {kind: 'loading'} | {kind: 'disabled'} | {kind: 'ready'; data: NodeAssignmentList} | {kind: 'error'; message: string; data?: NodeAssignmentList};
export function useNodeAssignments(projectId: string, enabled: boolean) {
  const commit=useCaseWrite();
  const owner=useCaseData(), key=caseKey(owner,projectId);
  const [state, setState] = useState<AssignmentListState>(() => {const data = enabled ? cached(projectId,owner) : undefined; return !enabled ? {kind: 'disabled'} : data ? {kind: 'ready', data} : {kind: 'loading'}});
  const [refreshing, setRefreshing] = useState(false);
  const [revision, setRevision] = useState(0);
  const [pending, setPending] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState<NodeAssignmentError | null>(null);
  const lifecycle = useRef({controller: new AbortController(), epoch: getSessionEpoch(), key});
  const retryAttempt = useRef<{mutation: AssignmentMutation; id: string} | null>(null);
  const listRequest = useRef(0), mutating = useRef(false);
  const current = useCallback(() => !lifecycle.current.controller.signal.aborted && lifecycle.current.epoch === getSessionEpoch(), []);
  const reload = useCallback(async (silent = false, force: boolean | symbol = true) => {
    if (!enabled) return;
    const sequence = ++listRequest.current;
    if (!silent) setRefreshing(true);
    try {
      const data = await prefetchNodeAssignments(projectId,force,owner);
      if (current() && sequence === listRequest.current) {
        setState(previous => {
          if (!current() || sequence !== listRequest.current) return previous;
          const prior = 'data' in previous ? previous.data : undefined;
          const node_details = data.node_details || (prior?.node_details && Object.fromEntries(data.nodes.flatMap(n => prior.nodes.find(p => p.key === n.key)?.revision === n.revision && prior.node_details?.[n.key] ? [[n.key, prior.node_details[n.key]]] : [])));
          const merged = {...data, node_details};
          lists.set(key, merged);
          return {kind: 'ready', data: merged};
        });
        if (!silent) setRevision(r => r + 1);
      }
    } catch (failure) {
      if (current() && sequence === listRequest.current) setState(previous => assignmentsDisabled(failure) ? {kind: 'disabled'} : {
        kind: 'error', message: assignmentErrorMessage(failure), data: failure instanceof NodeAssignmentError && [401, 403].includes(failure.status) ? undefined : 'data' in previous ? previous.data : undefined,
      });
    } finally {if (!silent && current() && sequence === listRequest.current) setRefreshing(false)}
  }, [projectId, current, enabled, owner, key]);
  useEffect(() => {
    retryAttempt.current = null;
    lifecycle.current = {controller: new AbortController(), epoch: getSessionEpoch(), key};
    const data = enabled ? cached(projectId,owner) : undefined;
    setState(!enabled ? {kind: 'disabled'} : data ? {kind: 'ready', data} : {kind: 'loading'});
    void reload(false,false);
    const controller = lifecycle.current.controller;
    return () => {controller.abort(); listRequest.current++};
  }, [reload]);
  const reloadDetail = useCallback((batch:symbol)=>reload(caseIntent(batch).reason==='own_write_committed',batch),[reload]);
  const refreshDetail = useDetailRefresh(reloadDetail, enabled);
  const applyDetail=(nodeKey:string,detail:NodeAssignmentDetail)=>{
      listRequest.current++;
      const detailKey = caseKey(owner,`${projectId}/${nodeKey}`);
      details.set(detailKey, {data: detail, readAt: Date.now()});
      seedCase(owner,`${projectId}/${nodeKey}`,detail,(current,intent,signal)=>loadDetail(projectId,nodeKey,current,intent,signal),false);
      const prior=lists.get(key);
      if(prior){
        const data={...prior,writes_enabled:detail.writes_enabled,writes_disabled_reason:detail.writes_disabled_reason,roster:detail.roster,warnings:detail.warnings,summary:detail.summary,can:{...prior.can,[nodeKey]:detail.can},nodes:prior.nodes.map(n=>n.key===nodeKey?detail.node:n),node_details:{...prior.node_details,[nodeKey]:{tasks:detail.tasks,assignable_people:detail.assignable_people}}};
        seedNodeAssignments(projectId,data,owner);
        setState({kind:'ready',data});
      }
  };
  const verifyNode=async(nodeKey:string)=>{const detail=await prefetchNodeAssignmentDetail(projectId,nodeKey,undefined,{reason:'own_write_outcome_unknown_recovery',id:requestId()},owner);if(current())applyDetail(nodeKey,detail);return detail};
  const mutate = async (mutation: AssignmentMutation, onFailure?: (message:string, failure:unknown)=>void): Promise<boolean> => {
    if (mutating.current || !current()) return false;
    const scope = lifecycle.current;
    const mutationCurrent = () => !scope.controller.signal.aborted && scope.epoch === getSessionEpoch();
    const attempt = retryAttempt.current && JSON.stringify(retryAttempt.current.mutation) === JSON.stringify(mutation) ? retryAttempt.current : {mutation, id: requestId()};
    retryAttempt.current = attempt;
    mutating.current = true; setPending(mutation.action); setError(null); setNotice('');
    try {
      const detail = await mutateNodeAssignment(projectId, mutation, scope.controller.signal, mutationCurrent, attempt.id);
      retryAttempt.current = null;
      if (!mutationCurrent()) return false;
      applyDetail(mutation.nodeKey,detail);
      setNotice('已儲存變更。'); await commit([{endpoint:`progress:${projectId}`}]); return true;
    } catch (failure) {
      const uncertain = !(failure instanceof NodeAssignmentError) || failure.status === 408 || failure.code === 'client_timeout' || failure.code === 'outcome_unknown' || failure.code === 'readback_mismatch' || failure.code === 'busy' || (failure.status >= 500 && !['lark_unconfigured', 'writes_disabled', 'disabled'].includes(failure.code || ''));
      if (!uncertain) retryAttempt.current = null;
      if (!mutationCurrent()) return false;
      onFailure?.(assignmentErrorMessage(failure), failure);
      if (assignmentsDisabled(failure)) {setState({kind: 'disabled'}); return false}
      if (failure instanceof NodeAssignmentError && failure.code === 'revision_conflict') {
        setNotice('資料已被他人更新，已為你重新載入'); await reload();
      } else {
        setError(failure instanceof NodeAssignmentError ? failure : new NodeAssignmentError(0, assignmentErrorMessage(failure)));
        if (failure instanceof NodeAssignmentError && failure.status === 404) await reload();
      }
      return false;
    } finally {mutating.current = false; if (mutationCurrent()) setPending('')}
  };
  return {state:lifecycle.current.key===key&&lifecycle.current.epoch===getSessionEpoch()?state:{kind:'loading'} as AssignmentListState, refreshing, revision, pending, notice, error, reload: refreshDetail || reload, mutate, retryMutation: () => retryAttempt.current ? mutate(retryAttempt.current.mutation) : Promise.resolve(false), owner, verifyNode, reloadList: reload, clearFeedback: () => {retryAttempt.current = null; setError(null); setNotice('')}};
}
export function cachedNodeAssignmentDetail(projectId: string, nodeKey: string, owner?:PageData): NodeAssignmentDetail | undefined {
  return details.get(caseKey(owner,`${projectId}/${nodeKey}`))?.data;
}
