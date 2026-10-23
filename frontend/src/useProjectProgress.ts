import {useCallback, useEffect, useState} from 'react';
import {ApiError,getSessionEpoch} from './api';
import {fetchProjectProgress, type ProjectProgress} from './projectProgressApi';
type State = {kind: 'loading'}|{kind: 'ready'; data: ProjectProgress}|{kind: 'error'; message: string; status?:number};
let epoch = getSessionEpoch();
const cache = new Map<string, {data: ProjectProgress; at: number}>();
const pending = new Map<string, Promise<ProjectProgress>>();
export function prefetchProjectProgress(id: string, force = false) {
 if (epoch !== getSessionEpoch()) {cache.clear(); pending.clear(); epoch = getSessionEpoch()}
 const currentEpoch = epoch;
 if (pending.has(id)) return pending.get(id)!;
 const stored = cache.get(id);
 if (!force && stored && Date.now() - stored.at < 60000) return Promise.resolve(stored.data);
 const request = fetchProjectProgress(id, () => currentEpoch === getSessionEpoch()).then(data => {if (currentEpoch === getSessionEpoch()) cache.set(id, {data, at: Date.now()}); return data}).finally(() => {if (pending.get(id) === request) pending.delete(id)});
 pending.set(id, request);
 return request;
}
export function useProjectProgress(id: string, enabled = true) {
 const [state, setState] = useState<State>({kind: 'loading'});
 const [version, setVersion] = useState(0);
 const retry = useCallback(() => setVersion(v => v + 1), []);
 useEffect(() => {
  if (!enabled) return;
  let active = true;
  const currentEpoch = getSessionEpoch();
  setState({kind: 'loading'});
  void prefetchProjectProgress(id, version > 0).then(data => {if (active && currentEpoch === getSessionEpoch()) setState({kind: 'ready', data})}).catch(error => {if (active && currentEpoch === getSessionEpoch()) setState({kind: 'error', message: error instanceof Error ? error.message : '工程進度暫不可用。',...(error instanceof ApiError ? {status:error.status} : {})})});
  return () => {active = false};
 }, [id, enabled, version]);
 return {state, retry};
}
