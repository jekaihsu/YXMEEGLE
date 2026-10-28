import {useEffect, useState} from 'react';
import {api, getSessionEpoch, onSessionEpochChange} from './api';

type State = {kind: 'idle' | 'preparing' | 'started' | 'not_permitted'} | {kind: 'failed'; reason: string};
const attempts = new Map<string, Promise<State>>();
onSessionEpochChange(() => attempts.clear());

async function ensure(projectId: string, epoch: number): Promise<State> {
 try {
  const result = await api<unknown>(`/api/projects/${encodeURIComponent(projectId)}/sop/ensure`, {method: 'POST'}, () => epoch === getSessionEpoch());
  if (result && typeof result === 'object' && 'state' in result) {
   if (result.state === 'started' || result.state === 'already_started') return {kind: 'started'};
   if (result.state === 'not_permitted') return {kind: 'not_permitted'};
   if (result.state === 'not_ready') return {kind: 'failed', reason: 'reason' in result && typeof result.reason === 'string' ? result.reason : 'not_ready'};
  }
  return {kind: 'failed', reason: 'invalid_response'};
 } catch {return {kind: 'failed', reason: 'unavailable'}}
}

export function useEnsureSop(projectId: string, mayStart: boolean, exists: boolean, reload: () => Promise<void>) {
 const [state, setState] = useState<State>({kind: 'idle'});
 const [retry, setRetry] = useState(0);
 useEffect(() => {
  let active = true;
  const epoch = getSessionEpoch(), key = `${epoch}:${projectId}`;
  const current = () => active && epoch === getSessionEpoch();
  if (!projectId || !mayStart || exists) {setState({kind: 'idle'}); return}
  let pending = attempts.get(key);
  if (!pending) {pending = ensure(projectId, epoch); attempts.set(key, pending)}
  setState({kind: 'preparing'});
  void pending.then(async result => {
   if (!current()) return;
   if (result.kind === 'started') {
    try {await reload()} catch {if (current()) setState({kind: 'failed', reason: 'reload_failed'}); return}
   }
   if (current()) setState(result);
  });
  return () => {active = false};
 }, [projectId, mayStart, exists, retry]);
 return {state, retry: () => {attempts.delete(`${getSessionEpoch()}:${projectId}`); setRetry(value => value + 1)}};
}
