import {useCallback, useEffect, useRef, useState} from 'react';
import {getSessionEpoch} from './api';
import {assignmentErrorMessage, assignmentsDisabled, fetchNodeAssignments, mutateNodeAssignment, NodeAssignmentError, type AssignmentMutation, type NodeAssignmentList} from './nodeAssignmentApi';

export type AssignmentListState = {kind: 'loading'} | {kind: 'disabled'} | {kind: 'ready'; data: NodeAssignmentList} | {kind: 'error'; message: string; data?: NodeAssignmentList};
export function useNodeAssignments(projectId: string) {
  const [state, setState] = useState<AssignmentListState>({kind: 'loading'});
  const [refreshing, setRefreshing] = useState(false);
  const [revision, setRevision] = useState(0);
  const [pending, setPending] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState<NodeAssignmentError | null>(null);
  const lifecycle = useRef({controller: new AbortController(), epoch: getSessionEpoch()});
  const listRequest = useRef(0), mutating = useRef(false);
  const current = useCallback(() => !lifecycle.current.controller.signal.aborted && lifecycle.current.epoch === getSessionEpoch(), []);
  const reload = useCallback(async () => {
    const sequence = ++listRequest.current;
    setRefreshing(true);
    try {
      const data = await fetchNodeAssignments(projectId, lifecycle.current.controller.signal, current);
      if (current() && sequence === listRequest.current) {setState({kind: 'ready', data}); setRevision(r => r + 1)}
    } catch (failure) {
      if (current() && sequence === listRequest.current) setState(previous => assignmentsDisabled(failure) ? {kind: 'disabled'} : {
        kind: 'error', message: assignmentErrorMessage(failure), data: 'data' in previous ? previous.data : undefined,
      });
    } finally {if (current() && sequence === listRequest.current) setRefreshing(false)}
  }, [projectId, current]);
  useEffect(() => {
    lifecycle.current = {controller: new AbortController(), epoch: getSessionEpoch()};
    void reload();
    const controller = lifecycle.current.controller;
    return () => {controller.abort(); listRequest.current++};
  }, [reload]);
  const mutate = async (mutation: AssignmentMutation): Promise<boolean> => {
    if (mutating.current || !current()) return false;
    const scope = lifecycle.current;
    const mutationCurrent = () => !scope.controller.signal.aborted && scope.epoch === getSessionEpoch();
    mutating.current = true; setPending(mutation.action); setError(null); setNotice('');
    try {
      await mutateNodeAssignment(projectId, mutation, scope.controller.signal, mutationCurrent);
      if (!mutationCurrent()) return false;
      setNotice('已儲存變更。'); await reload(); return true;
    } catch (failure) {
      if (!mutationCurrent()) return false;
      if (assignmentsDisabled(failure)) {setState({kind: 'disabled'}); return false}
      if (failure instanceof NodeAssignmentError && failure.status === 409) {
        setNotice('有人已更新此節點，已重新讀取最新資料，請確認後再試。'); await reload();
      } else setError(failure instanceof NodeAssignmentError ? failure : new NodeAssignmentError(0, assignmentErrorMessage(failure)));
      return false;
    } finally {mutating.current = false; if (mutationCurrent()) setPending('')}
  };
  return {state, refreshing, revision, pending, notice, error, reload, mutate, clearFeedback: () => {setError(null); setNotice('')}};
}
