import {useCallback, useEffect, useRef, useState} from 'react';
import type {PageData} from './pageData';
import {useCaseData, caseKey, readCase, seedCase, useDetailRefresh} from './detailRefresh';
import {getSessionEpoch} from './api';
import {assignmentErrorMessage, assignmentRequest, NodeAssignmentError, requestId} from './nodeAssignmentApi';
import {canConfirmSop, fetchSop, parseSopResult, sopResultMessage, SOP_ERRORS, sopPath, type SopPreview} from './startSop';
type State = {kind: 'hidden'} | {kind: 'forbidden'; reason: string} | {kind: 'ready'; data: SopPreview};
const cache=new Map<string,SopPreview>();
export function prefetchStartSop(id:string,force:boolean|symbol=false,owner?:PageData){
 return readCase(owner,`start:${id}`,force,current=>fetchSop(id,current)).then(data=>{cache.set(caseKey(owner,id),data);return data});
}
export function seedStartSop(id:string,data:SopPreview,owner?:PageData){cache.set(caseKey(owner,id),data);seedCase(owner,`start:${id}`,data,current=>fetchSop(id,current))}
export function useStartSop(id: string, enabled: boolean, refreshOverview: () => Promise<void>) {
 const owner=useCaseData(),key=caseKey(owner,id);
 const [state, setState] = useState<State>({kind: 'hidden'});
 const [busy, setBusy] = useState(false), [notice, setNotice] = useState('');
 const life = useRef({active: false, epoch: getSessionEpoch(),key});
 const pendingSync = useRef(false);
 const posting = useRef(false), attempt = useRef<{hash: string; id: string}|null>(null);
 const current = () => life.current.active && life.current.epoch === getSessionEpoch();
 const reload = useCallback(async (force: boolean | symbol = false) => {
  const scope=life.current;
  const valid=()=>scope===life.current&&scope.active&&scope.epoch===getSessionEpoch();
  try {const data = await prefetchStartSop(id, force, owner); if (valid()) setState({kind: 'ready', data: pendingSync.current ? {...data, already_started: false, eligible: data.can_start && !data.blockers.length} : data})}
  catch (e) {if (valid()) setState(e instanceof NodeAssignmentError && e.status === 403 ? {kind: 'forbidden', reason: assignmentErrorMessage(e)} : {kind: 'hidden'})}
 }, [id,owner]);
 useEffect(() => {life.current = {active: true, epoch: getSessionEpoch(),key}; setNotice(''); pendingSync.current = false; attempt.current = null; setState(enabled && life.current.epoch === getSessionEpoch() && cache.has(key) ? {kind: 'ready', data: cache.get(key)!} : {kind: 'hidden'}); if (enabled) void reload(); return () => {life.current.active = false}}, [id, enabled, reload]);
 const reloadDetail=useCallback((batch:symbol)=>reload(batch),[reload]);
 const refreshDetail=useDetailRefresh(reloadDetail,enabled);
 const confirm = async (seed = false) => {
  if (posting.current || state.kind !== 'ready' || !canConfirmSop(state.data, seed)) return false;
  posting.current = true; setBusy(true); setNotice('');
  const scope = life.current, valid = () => scope.active && scope === life.current && scope.epoch === getSessionEpoch();
  const hash = state.data.preview_hash, attemptKey = seed ? hash + ':seed' : hash;
  if (attempt.current?.hash !== attemptKey) attempt.current = {hash: attemptKey, id: requestId()};
  try {
   const result = parseSopResult(await assignmentRequest(sopPath(id), {method: 'POST', body: JSON.stringify({request_id: attempt.current.id, preview_hash: hash, ...(seed ? {seed_tasks: true} : {})})}, valid));
   if (!valid()) return false;
   attempt.current = null;
   pendingSync.current = result.results.some(node => node.sync === 'failed');
   setNotice(sopResultMessage(result, state.data, seed));
   await refreshOverview(); if(!refreshDetail)await reload(true); return result.complete;
  } catch (e) {
   if (!valid()) return false;
   if (e instanceof NodeAssignmentError && e.code === 'preview_stale') {attempt.current = null; await reload(true); setNotice('計畫已變更，已重新讀取預覽，請確認後再啟動。')}
   else if (e instanceof NodeAssignmentError && e.code === 'rate_limited') {setNotice(`已完成 ${state.data.nodes.filter(n => seed ? n.seed_task_exists : n.node_exists).length} 個節點。${SOP_ERRORS.rate_limited}`)}
   else {setNotice(e instanceof NodeAssignmentError ? SOP_ERRORS[e.code || ""] || assignmentErrorMessage(e) : assignmentErrorMessage(e)); if (e instanceof NodeAssignmentError && [403,404].includes(e.status)) await reload(true)}
   return false;
  } finally {posting.current = false; if (valid()) setBusy(false)}
 };
 return {state:life.current.key===key&&life.current.epoch===getSessionEpoch()?state:{kind:'hidden'} as State, busy, notice, confirm};
}
