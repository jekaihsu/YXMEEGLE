import {useCallback, useEffect, useRef, useState} from 'react';
import {getSessionEpoch} from './api';
import {useDetailRefresh} from './detailRefresh';
import {requestId} from './nodeAssignmentApi';
import {SOP_NODE_KEYS, SopError, type SopTask, sopApi, sopErrorText, type ImportPreview, type ImportReceipt, type SopNodeKey, type SopOverview, type SopTemplate, type SopAssignee} from './sopTaskApi';
import {previewBody, sameSelection, selectionBlockers, type Decisions} from './sopTaskModel';

export type SopListState = {kind: 'loading'} | {kind: 'forbidden'} | {kind: 'error'; message: string; data?: SopOverview; retrying?: boolean} | {kind: 'ready'; data: SopOverview; refreshing: boolean};
let cacheEpoch = getSessionEpoch();
const cache = new Map<string, SopOverview>();
const requests = new Map<string, Promise<SopOverview>>();
const assigneeRequests = new Map<string, Promise<SopAssignee[]>>();
const assigneeCache = new Map<string, SopAssignee[]>();
const readAt = new Map<string, number>();

const denied = new Map<string, SopError>();
const deniedAt = new Map<string, number>();
// A denial lapses so a person newly assigned a task is not locked out of it until the session resets.
const deniedFor = (key: string) => {const error = denied.get(key); if (error && Date.now() - (deniedAt.get(key) || 0) > 30000) {denied.delete(key); return undefined} return error};
const deny = (key: string, error: SopError) => {denied.set(key, error); deniedAt.set(key, Date.now())};
const cached = (key: string) => {
 if (cacheEpoch !== getSessionEpoch()) {cache.clear(); requests.clear(); assigneeRequests.clear(); assigneeCache.clear(); readAt.clear(); denied.clear(); cacheEpoch = getSessionEpoch()}
 return cache.get(key);
};

export function seedSopTasks(id:string,workspace:string,data:SopOverview) {const key=`${workspace}:${id}`;cached(key);denied.delete(key);cache.set(key,data);readAt.set(key,Date.now())}
export function canReadSop(user: {active?:boolean} | null | undefined){
 return !!user && user.active!==false;
}
export function prefetchSopTasks(projectId:string,workspace:string,force=false,join=false){
 const key=`${workspace}:${projectId}`, stored=cached(key), epoch=getSessionEpoch();
 const failure=deniedFor(key);if(failure)return Promise.reject(failure);
 // A passive caller (prefetch, retry) shares any read already in flight; only a reload after a write must not, since that read can predate the write.
 const pending=requests.get(key);if(pending&&(!force||join))return pending;
 if(!force&&stored&&Date.now()-(readAt.get(key)||0)<60000)return Promise.resolve(stored);
 const request=sopApi.overview(projectId,()=>epoch===getSessionEpoch()).then(data=>{
  if(epoch===getSessionEpoch()&&requests.get(key)===request){const prior=cache.get(key);if(!prior||prior.checklistRevision<=data.checklistRevision)cache.set(key,data);readAt.set(key,Date.now())}return data;
 }).catch(error=>{if(epoch===getSessionEpoch()&&requests.get(key)===request){cache.delete(key);readAt.delete(key);if(error instanceof SopError&&[401,403,404].includes(error.status))deny(key,error)}throw error}).finally(()=>{if(requests.get(key)===request)requests.delete(key)});
 requests.set(key,request);return request;
}
export function prefetchSopAssignees(projectId:string,workspace:string,force=false){
 const key=`${workspace}:${projectId}`;cached(key);const epoch=getSessionEpoch();
 const failure=deniedFor(key+':assignees');if(failure)return Promise.reject(failure);
 const pending=assigneeRequests.get(key);if(pending&&!force)return pending;
 const stored=assigneeCache.get(key);if(!force&&stored&&Date.now()-(readAt.get(key+':assignees')||0)<60000)return Promise.resolve(stored);
 const request=sopApi.assignees(projectId,()=>epoch===getSessionEpoch()).then(data=>{if(epoch===getSessionEpoch()&&assigneeRequests.get(key)===request){assigneeCache.set(key,data);readAt.set(key+':assignees',Date.now())}return data}).catch(error=>{if(epoch===getSessionEpoch()&&error instanceof SopError&&[401,403,404].includes(error.status)){assigneeCache.delete(key);deny(key+':assignees',error)}throw error}).finally(()=>{if(assigneeRequests.get(key)===request)assigneeRequests.delete(key)});
 assigneeRequests.set(key,request);return request;
}

export function useSopTasks(projectId: string, workspace: string, enabled=true) {
 const key = `${workspace}:${projectId}`;
 const [assignees,setAssignees]=useState<SopAssignee[]>([]);
 const [assigneeError,setAssigneeError]=useState('');
 const [state, setState] = useState<SopListState>(() => {const data = cached(key); return data ? {kind: 'ready', data, refreshing: true} : {kind: 'loading'}});
 const life = useRef({key, epoch: getSessionEpoch(), active: true, seq: 0});
 const readback = useCallback(async (force=true, join=false): Promise<boolean> => {
  if(!enabled){setState({kind:'forbidden'});return false}
  if(force)denied.delete(key);
  const scope = life.current, seq = ++scope.seq;
  const current = () => scope.active && scope === life.current && seq === scope.seq && scope.epoch === getSessionEpoch();
  setState(s => s.kind === 'ready' ? {...s, refreshing: true} : s.kind === 'error' ? {...s, retrying: true} : s);
  try {
   const data = await prefetchSopTasks(projectId,workspace,force,join);
   if (!current()) return false;
   const previous = cache.get(key);
   if (!previous || previous.checklistRevision <= data.checklistRevision) cache.set(key, data);
   setState({kind: 'ready', data: cache.get(key)!, refreshing: false});
   return true;
  } catch (error) {
   if (!current()) return false;
   if (error instanceof SopError && [401, 403, 404].includes(error.status)) {cache.delete(key); if(error.status===403&&error.code==='sop_import_forbidden')setState({kind:'forbidden'});else setState({kind:'error',message:sopErrorText(error)});return false}
   setState(s => ({kind: 'error', message: sopErrorText(error), data: 'data' in s ? s.data : undefined}));
   return false;
  }
 }, [projectId, key, workspace, enabled]);
 const reload = useCallback(async (force=true, join=false) => {await readback(force, join)}, [readback]);
 useEffect(() => {
  life.current = {key, epoch: getSessionEpoch(), active: true, seq: 0};
  if(!enabled){setState({kind:'forbidden'});setAssignees([]);setAssigneeError('');return()=>{life.current.active=false}}
  const data = cached(key);
  setState(data ? {kind: 'ready', data, refreshing: true} : {kind: 'loading'});
  setAssignees([]); setAssigneeError('');
  const scope=life.current; const valid=()=>scope===life.current&&scope.active&&scope.epoch===getSessionEpoch();
  void readback(false,true);
  void prefetchSopAssignees(projectId,workspace).then(people=>{if(valid())setAssignees(people)}).catch(e=>{if(valid())setAssigneeError(sopErrorText(e))});
  return () => {life.current.active = false};
 }, [key, readback]);
 const applyTask = useCallback((task: SopTask, checklistRevision: number) => {
  const previous = cache.get(key);
  if (!previous || !life.current.active || life.current.epoch !== getSessionEpoch()) return;
  const next = {...previous, tasks: previous.tasks.map(t => t.id === task.id && t.revision <= task.revision ? task : t), checklistRevision: Math.max(previous.checklistRevision, checklistRevision)};
  cache.set(key, next);
  setState(s => ({kind: 'ready', data: next, refreshing: s.kind === 'ready' && s.refreshing}));
 }, [key]);
 const reloadAll = useCallback(async () => {
  const scope=life.current;
  await Promise.all([readback(), prefetchSopAssignees(projectId,workspace,true).then(people=>{
   if(scope===life.current&&scope.active&&scope.epoch===getSessionEpoch()){setAssignees(people);setAssigneeError('')}
  }).catch(error=>{if(scope===life.current&&scope.active&&scope.epoch===getSessionEpoch())setAssigneeError(sopErrorText(error))})]);
 }, [readback,projectId,workspace]);
 const refreshDetail = useDetailRefresh(reloadAll, enabled);
 const current = useCallback(() => life.current.active && life.current.epoch === getSessionEpoch(), []);
 const sameScope=life.current.key===key&&life.current.epoch===getSessionEpoch();
 return {state:!enabled?{kind:'forbidden'} satisfies SopListState:!sameScope?{kind:'loading'} satisfies SopListState:state, reload: refreshDetail || reload, readback, applyTask, current, assignees:enabled&&sameScope?assignees:[], assigneeError};
}

export type ImportStep = 'version'|'select'|'confirm'|'receipt';
export type ImportStatus = 'idle'|'loading'|'applying'|'confirming'|'unknown';
export interface ImportScope {nodes: SopNodeKey[]}
export const defaultImportNodes = (startNode: SopNodeKey, only?: SopNodeKey): SopNodeKey[] => only ? [only] : SOP_NODE_KEYS.slice(SOP_NODE_KEYS.indexOf(startNode));

export function useSopImport(projectId: string, onApplied: () => Promise<void>) {
 const [step, setStep] = useState<ImportStep>('version');
 const [status, setStatus] = useState<ImportStatus>('idle');
 const [error, setError] = useState('');
 const [templates, setTemplates] = useState<SopTemplate[]|null>(null);
 const [version, setVersion] = useState('');
 const [nodes, setNodes] = useState<SopNodeKey[]>([]);
 const [preview, setPreview] = useState<ImportPreview|null>(null);
 const [defaults, setDefaults] = useState<ReadonlySet<string>>(new Set());
 const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
 const [decisions, setDecisions] = useState<Decisions>({});
 const [receipt, setReceipt] = useState<ImportReceipt|null>(null);
 // Kept across ambiguous failures so a retry or recovery reuses the same preview and request ids.
 const attempt = useRef<{previewId: string; requestId: string}|null>(null);
 const life = useRef({active: false, epoch: getSessionEpoch()});
 const current = () => life.current.active && life.current.epoch === getSessionEpoch();
 useEffect(() => {life.current = {active: true, epoch: getSessionEpoch()}; return () => {life.current.active = false}}, [projectId]);

 const open = async (initialNodes: SopNodeKey[]) => {
  const scope = life.current;
  setStep('version'); setStatus('loading'); setError(''); setPreview(null); setReceipt(null); setNodes(initialNodes); attempt.current = null;
  try {
   const list = await sopApi.templates(current);
   if (scope !== life.current || !current()) return;
   setTemplates(list); setVersion(list.find(t => t.is_default)?.version_id || '');
  } catch (e) {if (current()) setError(sopErrorText(e))}
  finally {if (current()) setStatus('idle')}
 };
 const loadDefault = async () => {
  if (!version || !nodes.length) return;
  setStatus('loading'); setError('');
  try {
   const next = await sopApi.preview(projectId, {template_version_id: version, node_keys: SOP_NODE_KEYS.filter(k => nodes.includes(k))}, current);
   if (!current()) return;
   const rows = new Set(next.rowKeys);
   setPreview(next); setDefaults(rows); setSelected(rows); setDecisions({}); setStep('select');
  } catch (e) {if (current()) setError(sopErrorText(e))}
  finally {if (current()) setStatus('idle')}
 };
 const blockers = preview ? selectionBlockers(preview, selected, decisions, defaults) : {};
 const toConfirm = async () => {
  if (!preview || Object.keys(blockers).length) return;
  if (sameSelection(preview, selected) && !Object.keys(decisions).some(k => selected.has(k) && !defaults.has(k))) {setStep('confirm'); return}
  await repreview('confirm');
 };
 const repreview = async (target: ImportStep, notice = '') => {
  if (!preview) return;
  setStatus('loading'); setError(notice);
  try {
   const next = await sopApi.preview(projectId, previewBody(preview, selected, decisions, defaults), current);
   if (!current()) return;
   setPreview(next); setSelected(new Set(next.rowKeys)); setStep(target);
  } catch (e) {if (current()) setError(sopErrorText(e))}
  finally {if (current()) setStatus('idle')}
 };
 const finish = async (result: ImportReceipt) => {
  attempt.current = null; setReceipt(result); setStep('receipt'); setStatus('idle'); setError('');
  await onApplied();
 };
 const recover = async () => {
  const pending = attempt.current;
  if (!pending) return;
  setStatus('confirming'); setError('');
  try {
   const result = await sopApi.run(projectId, pending.requestId, current);
   if (current()) await finish(result);
  } catch (e) {
   if (!current()) return;
   if (e instanceof SopError && e.code === 'run_not_found') {setStatus('idle'); setError('匯入尚未完成，可重試')}
   else {setStatus('unknown'); setError(sopErrorText(e))}
  }
 };
 const apply = async () => {
  if (!preview || status !== 'idle') return;
  if (attempt.current?.previewId !== preview.previewId) attempt.current = {previewId: preview.previewId, requestId: requestId()};
  const {previewId, requestId: rid} = attempt.current;
  setStatus('applying'); setError('');
  try {
   const result = await sopApi.apply(projectId, {preview_id: previewId, request_id: rid}, current);
   if (current()) await finish(result);
  } catch (e) {
   if (!current()) return;
   if (e instanceof SopError && e.ambiguous) {await recover(); return}
   attempt.current = null; setStatus('idle');
   if (e instanceof SopError && ['preview_stale','preview_not_found'].includes(e.code)) await repreview('confirm', sopErrorText(e));
   else if (e instanceof SopError && e.code === 'idempotency_mismatch') {setStep('select'); setError(sopErrorText(e))}
   else setError(sopErrorText(e));
  }
 };
 const toggle = (row: string) => setSelected(s => {const next = new Set(s); if (next.has(row)) next.delete(row); else next.add(row); return next});
 const toggleNode = (key: SopNodeKey) => setNodes(n => n.includes(key) ? n.filter(k => k !== key) : SOP_NODE_KEYS.filter(k => k === key || n.includes(k)));
 const back = () => {setError(''); setStep(step === 'confirm' ? 'select' : 'version')};
 const busy = status === 'loading' || status === 'applying' || status === 'confirming';
 return {step, status, busy, error, templates, version, setVersion, nodes, toggleNode, preview, defaults, selected, toggle, decisions,
  decide: (row: string, reason: string) => setDecisions(d => ({...d, [row]: reason})), blockers, receipt,
  open, loadDefault, toConfirm, apply, recover, back, hasAttempt: () => attempt.current !== null};
}
