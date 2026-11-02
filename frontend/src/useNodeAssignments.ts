import {useCallback, useEffect, useRef, useState} from 'react';
import {getSessionEpoch} from './api';
import type {PageData} from './pageData';
import {useCaseData, caseKey, readCase, seedCase, useDetailRefresh} from './detailRefresh';
import {assignmentErrorMessage, assignmentsDisabled, fetchNodeAssignments, fetchNodeAssignmentDetail, mutateNodeAssignment, NodeAssignmentError, requestId, type AssignmentMutation, type NodeAssignmentDetail, type NodeAssignmentList} from './nodeAssignmentApi';

const lists = new Map<string, NodeAssignmentList>();
const details = new Map<string, {data:NodeAssignmentDetail;readAt:number}>();
export function prefetchNodeAssignmentDetail(projectId:string,nodeKey:string,expectedRevision?:string|null,force=false,owner?:PageData):Promise<NodeAssignmentDetail> {
 const key=caseKey(owner,`${projectId}/${nodeKey}`);
 const stored=details.get(key);
 const changed=!!stored&&expectedRevision!==undefined&&stored.data.node.revision!==expectedRevision;
 return readCase(owner,`${projectId}/${nodeKey}`,force||changed,current=>fetchNodeAssignmentDetail(projectId,nodeKey,new AbortController().signal,current)).then(data=>{details.set(key,{data,readAt:Date.now()});return data}).catch(error=>{if(error instanceof NodeAssignmentError&&[401,403,404].includes(error.status))details.delete(key);throw error});
}
function cached(projectId:string,owner?:PageData){return lists.get(caseKey(owner,projectId))}
export function prefetchNodeAssignments(projectId:string,force:boolean|symbol=false,owner?:PageData):Promise<NodeAssignmentList> {
 return readCase(owner,projectId,force,current=>fetchNodeAssignments(projectId,new AbortController().signal,current)).then(data=>{lists.set(caseKey(owner,projectId),data);return data});
}
export function seedNodeAssignments(id:string,data:NodeAssignmentList,owner?:PageData){lists.set(caseKey(owner,id),data);seedCase(owner,id,data,current=>fetchNodeAssignments(id,new AbortController().signal,current))}
export type AssignmentListState = {kind: 'loading'} | {kind: 'disabled'} | {kind: 'ready'; data: NodeAssignmentList} | {kind: 'error'; message: string; data?: NodeAssignmentList};
export function useNodeAssignments(projectId: string, enabled: boolean) {
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
  const reloadDetail = useCallback((batch:symbol)=>reload(false,batch),[reload]);
  const refreshDetail = useDetailRefresh(reloadDetail, enabled);
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
      listRequest.current++;
      const detailKey = caseKey(owner,`${projectId}/${mutation.nodeKey}`);
      details.set(detailKey, {data: detail, readAt: Date.now()});
      seedCase(owner,`${projectId}/${mutation.nodeKey}`,detail,current=>fetchNodeAssignmentDetail(projectId,mutation.nodeKey,new AbortController().signal,current),false);
      const prior=lists.get(key);
      if(prior){
        const data={...prior,writes_enabled:detail.writes_enabled,writes_disabled_reason:detail.writes_disabled_reason,roster:detail.roster,warnings:detail.warnings,summary:detail.summary,can:{...prior.can,[mutation.nodeKey]:detail.can},nodes:prior.nodes.map(n=>n.key===mutation.nodeKey?detail.node:n),node_details:{...prior.node_details,[mutation.nodeKey]:{tasks:detail.tasks,assignable_people:detail.assignable_people}}};
        seedNodeAssignments(projectId,data,owner);
        setState({kind:'ready',data});
      }
      setNotice('已儲存變更。'); if (refreshDetail) await refreshDetail(); return true;
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
  return {state:lifecycle.current.key===key&&lifecycle.current.epoch===getSessionEpoch()?state:{kind:'loading'} as AssignmentListState, refreshing, revision, pending, notice, error, reload: refreshDetail || reload, mutate, retryMutation: () => retryAttempt.current ? mutate(retryAttempt.current.mutation) : Promise.resolve(false), clearFeedback: () => {retryAttempt.current = null; setError(null); setNotice('')}};
}
export function cachedNodeAssignmentDetail(projectId: string, nodeKey: string, owner?:PageData): NodeAssignmentDetail | undefined {
  return details.get(caseKey(owner,`${projectId}/${nodeKey}`))?.data;
}
