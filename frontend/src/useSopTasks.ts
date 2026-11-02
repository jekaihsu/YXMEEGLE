import {useCallback, useEffect, useRef, useState} from 'react';
import {api, getSessionEpoch} from './api';
import type {PageData, FetchIntent} from './pageData';
import {type CaseSnapshot, useCaseData, caseKey, readCase, seedCase, useDetailRefresh, useCaseWrite} from './detailRefresh';
import {requestId} from './nodeAssignmentApi';
import {SOP_NODE_KEYS, parseOverview, SopError, type SopTask, sopApi, sopErrorText, type ImportPreview, type ImportReceipt, type SopNodeKey, type SopOverview, type SopTemplate, type SopAssignee} from './sopTaskApi';
import {previewBody, sameSelection, selectionBlockers, type Decisions} from './sopTaskModel';

function loadOverview(id:string,current:()=>boolean,intent:FetchIntent,signal:AbortSignal){
 return api(`/api/projects/${encodeURIComponent(id)}/sop-tasks`,{signal,cache:'no-store',headers:{'X-YX-Fetch-Intent':intent.reason,'X-YX-Fetch-Generation':'id' in intent?intent.id:'initial'}},current).then(parseOverview).catch(error=>{if(error&&typeof error==='object'&&'status' in error)throw new SopError(Number(error.status),'code' in error?String(error.code):'request_failed');throw error});
}
export type SopListState = {kind: 'loading'} | {kind: 'forbidden'} | {kind: 'error'; message: string; data?: SopOverview; retrying?: boolean} | {kind: 'ready'; data: SopOverview; refreshing: boolean};
const cache = new Map<string,SopOverview>();
export function seedSopTasks(id:string,workspace:string,data:SopOverview,owner?:PageData,meta?:CaseSnapshot,batch?:symbol) {
 const resource=`${workspace}:${id}:tasks`;cache.set(caseKey(owner,resource),data);
 seedCase(owner,resource,data,(current,intent,signal)=>loadOverview(id,current,intent,signal),true,meta,batch);
}
export function canReadSop(user:{active?:boolean}|null|undefined){return !!user&&user.active!==false}
export function prefetchSopTasks(projectId:string,workspace:string,force:boolean|symbol=false,_join=false,owner?:PageData){
 const resource=`${workspace}:${projectId}:tasks`;
 return readCase(owner,resource,force,(current,intent,signal)=>loadOverview(projectId,current,intent,signal)).then(data=>{const key=caseKey(owner,resource),prior=cache.get(key);if(!prior||prior.checklistRevision<=data.checklistRevision)cache.set(key,data);return cache.get(key)!});
}
export function prefetchSopAssignees(projectId:string,workspace:string,force:boolean|symbol=false,owner?:PageData){
 return readCase(owner,`${workspace}:${projectId}:assignees`,force,current=>sopApi.assignees(projectId,current));
}

export function useSopTasks(projectId: string, workspace: string, enabled=true) {
 const owner=useCaseData(),commit=useCaseWrite();
 const key = caseKey(owner,`${workspace}:${projectId}:tasks`);
 const [assignees,setAssignees]=useState<SopAssignee[]>([]);
 const [assigneeError,setAssigneeError]=useState('');
 const [state, setState] = useState<SopListState>(() => {const data = cache.get(key); return data ? {kind: 'ready', data, refreshing: true} : {kind: 'loading'}});
 const life = useRef({key, epoch: getSessionEpoch(), active: true, seq: 0});
 const readback = useCallback(async (force:boolean|symbol=true, join=false): Promise<boolean> => {
  if(!enabled){setState({kind:'forbidden'});return false}
  const scope = life.current, seq = ++scope.seq;
  const current = () => scope.active && scope === life.current && seq === scope.seq && scope.epoch === getSessionEpoch();
  setState(s => s.kind === 'ready' ? {...s, refreshing: true} : s.kind === 'error' ? {...s, retrying: true} : s);
  try {
   const data = await prefetchSopTasks(projectId,workspace,force,join,owner);
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
 }, [projectId, key, workspace, enabled, owner]);
 const reload = useCallback(async (force:boolean|symbol=true, join=false) => {await readback(force, join)}, [readback]);
 useEffect(() => {
  life.current = {key, epoch: getSessionEpoch(), active: true, seq: 0};
  if(!enabled){setState({kind:'forbidden'});setAssignees([]);setAssigneeError('');return()=>{life.current.active=false}}
  const data = cache.get(key);
  setState(data ? {kind: 'ready', data, refreshing: true} : {kind: 'loading'});
  setAssignees([]); setAssigneeError('');
  const scope=life.current; const valid=()=>scope===life.current&&scope.active&&scope.epoch===getSessionEpoch();
  void readback(false,true);
  void prefetchSopAssignees(projectId,workspace,false,owner).then(people=>{if(valid())setAssignees(people)}).catch(e=>{if(valid())setAssigneeError(sopErrorText(e))});
  return () => {life.current.active = false};
 }, [key, readback]);
 const applyTask = useCallback((task: SopTask, checklistRevision: number) => {
  const previous = cache.get(key);
  if (!previous || !life.current.active || life.current.epoch !== getSessionEpoch()) return;
  const next = {...previous, tasks: previous.tasks.map(t => t.id === task.id && t.revision <= task.revision ? task : t), checklistRevision: Math.max(previous.checklistRevision, checklistRevision)};
  life.current.seq++;
  seedSopTasks(projectId,workspace,next,owner);
  setState(s => ({kind: 'ready', data: next, refreshing: s.kind === 'ready' && s.refreshing}));
 }, [key,projectId,workspace,owner]);
 const reloadAll = useCallback(async (batch:symbol) => {
  const scope=life.current;
  await Promise.all([readback(batch), prefetchSopAssignees(projectId,workspace,batch,owner).then(people=>{
   if(scope===life.current&&scope.active&&scope.epoch===getSessionEpoch()){setAssignees(people);setAssigneeError('')}
  }).catch(error=>{if(scope===life.current&&scope.active&&scope.epoch===getSessionEpoch())setAssigneeError(sopErrorText(error))})]);
 }, [readback,projectId,workspace,owner]);
 useDetailRefresh(reloadAll, enabled);
 const current = useCallback(() => life.current.active && life.current.epoch === getSessionEpoch(), []);
 const sameScope=life.current.key===key&&life.current.epoch===getSessionEpoch();
 const snapshot=owner.state<SopOverview>({endpoint:`${workspace}:${projectId}:tasks`});
 const dataTime='value' in snapshot?snapshot.value.fetchedAt:'previous' in snapshot?snapshot.previous?.fetchedAt:null;
 return {dataTime,state:!enabled?{kind:'forbidden'} satisfies SopListState:!sameScope?{kind:'loading'} satisfies SopListState:state, reload: (afterWrite=true,join=false)=>join||!afterWrite?reload(true,join):commit([{endpoint:`${workspace}:${projectId}:tasks`},{endpoint:`progress:${projectId}`},{endpoint:`start:${projectId}`}]), readback, applyTask, current, assignees:enabled&&sameScope?assignees:[], assigneeError};
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
