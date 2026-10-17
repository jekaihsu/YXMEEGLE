import {useCallback, useEffect, useRef, useState} from 'react';
import {getSessionEpoch} from './api';
import {assignmentErrorMessage, assignmentRequest, NodeAssignmentError, requestId} from './nodeAssignmentApi';
import {fetchSop, parseSopResult, sopResultMessage, SOP_ERRORS, sopPath, type SopPreview} from './startSop';
type State = {kind: 'hidden'} | {kind: 'forbidden'; reason: string} | {kind: 'ready'; data: SopPreview};
let epoch = getSessionEpoch();
const cache = new Map<string, SopPreview>();
const readAt = new Map<string, number>();
const requests = new Map<string, Promise<SopPreview>>();
export function prefetchStartSop(id: string, force = false) {
 if (epoch !== getSessionEpoch()) {cache.clear(); readAt.clear(); requests.clear(); epoch = getSessionEpoch()}
 const activeEpoch = epoch;
 const current = () => activeEpoch === getSessionEpoch();
 if (force) {cache.delete(id); readAt.delete(id)}
 const cached = cache.get(id);
 if (cached && Date.now() - (readAt.get(id) || 0) < 60000) return Promise.resolve(cached);
 const pending = requests.get(id);
 if (pending) return pending;
 const promise = fetchSop(id, current).then(data => {if (current()) {cache.set(id, data); readAt.set(id, Date.now())} return data}).finally(() => {if (requests.get(id) === promise) requests.delete(id)});
 requests.set(id, promise); return promise;
}
export function useStartSop(id: string, enabled: boolean, refreshOverview: () => Promise<void>) {
 const [state, setState] = useState<State>({kind: 'hidden'});
 const [busy, setBusy] = useState(false), [notice, setNotice] = useState('');
 const life = useRef({active: false, epoch: getSessionEpoch()});
 const pendingSync = useRef(false);
 const posting = useRef(false), attempt = useRef<{hash: string; id: string}|null>(null);
 const current = () => life.current.active && life.current.epoch === getSessionEpoch();
 const reload = useCallback(async (force = false) => {
  try {const data = await prefetchStartSop(id, force); if (current()) setState({kind: 'ready', data: pendingSync.current ? {...data, already_started: false, eligible: data.can_start && !data.blockers.length} : data})}
  catch (e) {if (current()) setState(e instanceof NodeAssignmentError && e.status === 403 ? {kind: 'forbidden', reason: assignmentErrorMessage(e)} : {kind: 'hidden'})}
 }, [id]);
 useEffect(() => {life.current = {active: true, epoch: getSessionEpoch()}; setNotice(''); pendingSync.current = false; attempt.current = null; setState(enabled && epoch === getSessionEpoch() && cache.has(id) ? {kind: 'ready', data: cache.get(id)!} : {kind: 'hidden'}); if (enabled) void reload(); return () => {life.current.active = false}}, [id, enabled, reload]);
 const confirm = async () => {
  if (posting.current || state.kind !== 'ready' || !state.data.can_start || !state.data.eligible || state.data.blockers.length || state.data.already_started) return false;
  posting.current = true; setBusy(true); setNotice('');
  const scope = life.current, valid = () => scope.active && scope === life.current && scope.epoch === getSessionEpoch();
  const hash = state.data.preview_hash;
  if (attempt.current?.hash !== hash) attempt.current = {hash, id: requestId()};
  try {
   const result = parseSopResult(await assignmentRequest(sopPath(id), {method: 'POST', body: JSON.stringify({request_id: attempt.current.id, preview_hash: hash})}, valid));
   if (!valid()) return false;
   attempt.current = null;
   pendingSync.current = result.results.some(node => node.sync === 'failed');
   setNotice(sopResultMessage(result, state.data));
   await refreshOverview(); await reload(true); return result.complete;
  } catch (e) {
   if (!valid()) return false;
   if (e instanceof NodeAssignmentError && e.code === 'preview_stale') {attempt.current = null; await reload(true); setNotice('計畫已變更，已重新讀取預覽，請確認後再啟動。')}
   else if (e instanceof NodeAssignmentError && e.code === 'rate_limited') {setNotice(`已完成 ${state.data.nodes.filter(n => n.seed_task_exists).length} 個節點。${SOP_ERRORS.rate_limited}`)}
   else {setNotice(e instanceof NodeAssignmentError ? SOP_ERRORS[e.code || ""] || assignmentErrorMessage(e) : assignmentErrorMessage(e)); if (e instanceof NodeAssignmentError && [403,404].includes(e.status)) await reload(true)}
   return false;
  } finally {posting.current = false; if (valid()) setBusy(false)}
 };
 return {state, busy, notice, confirm};
}
