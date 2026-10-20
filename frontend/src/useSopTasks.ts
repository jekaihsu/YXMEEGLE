import {useCallback, useEffect, useRef, useState} from 'react';
import {getSessionEpoch} from './api';
import {requestId} from './nodeAssignmentApi';
import {SOP_NODE_KEYS, SopError, sopApi, sopErrorText, type ImportPreview, type ImportReceipt, type SopNodeKey, type SopOverview, type SopTemplate, type SopAssignee} from './sopTaskApi';
import {previewBody, sameSelection, selectionBlockers, type Decisions} from './sopTaskModel';

export type SopListState = {kind: 'loading'} | {kind: 'forbidden'} | {kind: 'error'; message: string; data?: SopOverview} | {kind: 'ready'; data: SopOverview; refreshing: boolean};
let cacheEpoch = getSessionEpoch();
const cache = new Map<string, SopOverview>();
const cached = (key: string) => {
 if (cacheEpoch !== getSessionEpoch()) {cache.clear(); cacheEpoch = getSessionEpoch()}
 return cache.get(key);
};

export function useSopTasks(projectId: string, workspace: string) {
 const key = `${workspace}:${projectId}`;
 const [assignees,setAssignees]=useState<SopAssignee[]>([]);
 const [assigneeError,setAssigneeError]=useState('');
 const [state, setState] = useState<SopListState>(() => {const data = cached(key); return data ? {kind: 'ready', data, refreshing: true} : {kind: 'loading'}});
 const life = useRef({key, epoch: getSessionEpoch(), active: true, seq: 0});
 const reload = useCallback(async () => {
  const scope = life.current, seq = ++scope.seq;
  const current = () => scope.active && scope === life.current && seq === scope.seq && scope.epoch === getSessionEpoch();
  setState(s => s.kind === 'ready' ? {...s, refreshing: true} : s);
  try {
   const data = await sopApi.overview(projectId, current);
   if (!current()) return;
   const previous = cache.get(key);
   if (!previous || previous.checklistRevision <= data.checklistRevision) cache.set(key, data);
   setState({kind: 'ready', data: cache.get(key)!, refreshing: false});
  } catch (error) {
   if (!current()) return;
   if (error instanceof SopError && [401, 403, 404].includes(error.status)) {cache.delete(key); setState({kind: 'forbidden'}); return}
   setState(s => ({kind: 'error', message: sopErrorText(error), data: 'data' in s ? s.data : undefined}));
  }
 }, [projectId, key]);
 useEffect(() => {
  life.current = {key, epoch: getSessionEpoch(), active: true, seq: 0};
  const data = cached(key);
  setState(data ? {kind: 'ready', data, refreshing: true} : {kind: 'loading'});
  void reload();
  setAssignees([]); setAssigneeError('');
  const scope=life.current; const valid=()=>scope===life.current&&scope.active&&scope.epoch===getSessionEpoch();
  void sopApi.assignees(projectId,valid).then(people=>{if(valid())setAssignees(people)}).catch(e=>{if(valid())setAssigneeError(sopErrorText(e))});
  return () => {life.current.active = false};
 }, [key, reload]);
 const current = useCallback(() => life.current.active && life.current.epoch === getSessionEpoch(), []);
 return {state, reload, current, assignees, assigneeError};
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
