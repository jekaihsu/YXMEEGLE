import {useCallback, useEffect, useRef, useState} from 'react';
import {getSessionEpoch, getPendingMutations} from './api';
import {assignmentErrorMessage, assignmentsDisabled, fetchNodeAssignments, fetchNodeAssignmentDetail, mutateNodeAssignment, NodeAssignmentError, requestId, type AssignmentMutation, type NodeAssignmentDetail, type NodeAssignmentList} from './nodeAssignmentApi';

let cacheEpoch = getSessionEpoch();
const lists = new Map<string, NodeAssignmentList>();
const listReadAt = new Map<string, number>();
const requests = new Map<string, Promise<NodeAssignmentList>>();
const details = new Map<string, {data: NodeAssignmentDetail; readAt: number}>();
const detailRequests = new Map<string, Promise<NodeAssignmentDetail>>();
function syncEpoch() {
  if (cacheEpoch !== getSessionEpoch()) {lists.clear(); listReadAt.clear(); requests.clear(); details.clear(); detailRequests.clear(); cacheEpoch = getSessionEpoch()}
}
export function prefetchNodeAssignmentDetail(projectId: string, nodeKey: string, expectedRevision?: string | null, force = false): Promise<NodeAssignmentDetail> {
  syncEpoch();
  const key = `${projectId}/${nodeKey}`, cached = details.get(key), pending = detailRequests.get(key);
  if (pending) return pending;
  if (!force && cached && Date.now() - cached.readAt < 60000 && (expectedRevision === undefined || cached.data.node.revision === expectedRevision)) return Promise.resolve(cached.data);
  const epoch = getSessionEpoch();
  const request = fetchNodeAssignmentDetail(projectId, nodeKey, new AbortController().signal, () => epoch === getSessionEpoch()).then(data => {
    if (epoch === getSessionEpoch() && detailRequests.get(key) === request) details.set(key, {data, readAt: Date.now()});
    return data;
  }).catch(error => {if (epoch === getSessionEpoch()) details.delete(key); throw error}).finally(() => {if (detailRequests.get(key) === request) detailRequests.delete(key)});
  detailRequests.set(key, request);
  return request;
}
function cached(projectId: string) {syncEpoch(); return lists.get(projectId)}
export function prefetchNodeAssignments(projectId: string, force = false): Promise<NodeAssignmentList> {
  syncEpoch();
  const existing = requests.get(projectId);
  if (existing) return existing;
  const stored=lists.get(projectId);
  if(!force && stored && Date.now()-(listReadAt.get(projectId)||0)<60000)return Promise.resolve(stored);
  const epoch = getSessionEpoch();
  const request = fetchNodeAssignments(projectId, new AbortController().signal, () => epoch === getSessionEpoch()).then(data => {
    if (epoch === getSessionEpoch() && requests.get(projectId) === request) {lists.set(projectId, data);listReadAt.set(projectId,Date.now())};
    return data;
  }).catch(failure => {if (epoch === getSessionEpoch() && (assignmentsDisabled(failure) || failure instanceof NodeAssignmentError && [401, 403].includes(failure.status))) lists.delete(projectId); throw failure}).finally(() => {if (requests.get(projectId) === request) requests.delete(projectId)});
  requests.set(projectId, request);
  return request;
}
export type AssignmentListState = {kind: 'loading'} | {kind: 'disabled'} | {kind: 'ready'; data: NodeAssignmentList} | {kind: 'error'; message: string; data?: NodeAssignmentList};
export function useNodeAssignments(projectId: string, enabled: boolean) {
  const [state, setState] = useState<AssignmentListState>(() => {const data = enabled ? cached(projectId) : undefined; return !enabled ? {kind: 'disabled'} : data ? {kind: 'ready', data} : {kind: 'loading'}});
  const [refreshing, setRefreshing] = useState(false);
  const [revision, setRevision] = useState(0);
  const [pending, setPending] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState<NodeAssignmentError | null>(null);
  const lifecycle = useRef({controller: new AbortController(), epoch: getSessionEpoch()});
  const retryAttempt = useRef<{mutation: AssignmentMutation; id: string} | null>(null);
  const listRequest = useRef(0), mutating = useRef(false);
  const current = useCallback(() => !lifecycle.current.controller.signal.aborted && lifecycle.current.epoch === getSessionEpoch(), []);
  const reload = useCallback(async (silent = false, force = true) => {
    if (!enabled) return;
    const sequence = ++listRequest.current;
    if (!silent) setRefreshing(true);
    try {
      const data = await prefetchNodeAssignments(projectId,force);
      if (current() && sequence === listRequest.current) {
        setState(previous => {
          if (!current() || sequence !== listRequest.current) return previous;
          const prior = 'data' in previous ? previous.data : undefined;
          const node_details = data.node_details || (prior?.node_details && Object.fromEntries(data.nodes.flatMap(n => prior.nodes.find(p => p.key === n.key)?.revision === n.revision && prior.node_details?.[n.key] ? [[n.key, prior.node_details[n.key]]] : [])));
          const merged = {...data, node_details};
          lists.set(projectId, merged);
          return {kind: 'ready', data: merged};
        });
        if (!silent) setRevision(r => r + 1);
      }
    } catch (failure) {
      if (current() && sequence === listRequest.current) setState(previous => assignmentsDisabled(failure) ? {kind: 'disabled'} : {
        kind: 'error', message: assignmentErrorMessage(failure), data: failure instanceof NodeAssignmentError && [401, 403].includes(failure.status) ? undefined : 'data' in previous ? previous.data : undefined,
      });
    } finally {if (!silent && current() && sequence === listRequest.current) setRefreshing(false)}
  }, [projectId, current, enabled]);
  useEffect(() => {
    retryAttempt.current = null;
    lifecycle.current = {controller: new AbortController(), epoch: getSessionEpoch()};
    const data = enabled ? cached(projectId) : undefined;
    setState(!enabled ? {kind: 'disabled'} : data ? {kind: 'ready', data} : {kind: 'loading'});
    void reload(false,false);
    const controller = lifecycle.current.controller;
    return () => {controller.abort(); listRequest.current++};
  }, [reload]);
  useEffect(() => {
    const refresh = () => {if (enabled && document.visibilityState !== 'hidden' && !refreshing && !mutating.current && !getPendingMutations() && !document.activeElement?.closest('.node-assignments')) void reload(true)};
    const timer = window.setInterval(refresh, 60000);
    document.addEventListener('visibilitychange', refresh);
    return () => {window.clearInterval(timer); document.removeEventListener('visibilitychange', refresh)};
  }, [enabled, reload, refreshing]);
  const mutate = async (mutation: AssignmentMutation): Promise<boolean> => {
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
      listRequest.current++; requests.delete(projectId);
      const detailKey = `${projectId}/${mutation.nodeKey}`;
      detailRequests.delete(detailKey); details.set(detailKey, {data: detail, readAt: Date.now()});
      setState(previous => {
        if (!mutationCurrent()) return previous;
        if (!('data' in previous) || !previous.data) return previous;
        const data = {...previous.data, writes_enabled: detail.writes_enabled, writes_disabled_reason: detail.writes_disabled_reason, roster: detail.roster, warnings: detail.warnings, summary: detail.summary, can: {...previous.data.can, [mutation.nodeKey]: detail.can}, nodes: previous.data.nodes.map(n => n.key === mutation.nodeKey ? detail.node : n), node_details: {...previous.data.node_details, [mutation.nodeKey]: {tasks: detail.tasks, assignable_people: detail.assignable_people}}};
        lists.set(projectId, data);
        return {kind: 'ready', data};
      });
      setNotice('已儲存變更。'); void reload(); return true;
    } catch (failure) {
      const uncertain = !(failure instanceof NodeAssignmentError) || failure.status === 408 || failure.code === 'client_timeout' || failure.code === 'outcome_unknown' || failure.code === 'readback_mismatch' || failure.code === 'busy' || (failure.status >= 500 && !['lark_unconfigured', 'writes_disabled', 'disabled'].includes(failure.code || ''));
      if (!uncertain) retryAttempt.current = null;
      if (!mutationCurrent()) return false;
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
  return {state, refreshing, revision, pending, notice, error, reload, mutate, retryMutation: () => retryAttempt.current ? mutate(retryAttempt.current.mutation) : Promise.resolve(false), clearFeedback: () => {retryAttempt.current = null; setError(null); setNotice('')}};
}
