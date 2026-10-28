import {Badge, Skeleton} from './design';
import {localCase} from './nodeWorkbenchModel';
import {useStartSop} from './useStartSop';
import {useEnsureSop} from './useEnsureSop';
import {useSopTasks} from './useSopTasks';
import type {useNodeAssignments} from './useNodeAssignments';
import type {Ctx} from './appCommon';
import type {Project} from './types';

export function EnsureSopStatus({c, p, sop, assignments}: {c: Ctx; p: Project; sop: ReturnType<typeof useSopTasks>; assignments: ReturnType<typeof useNodeAssignments>}) {
 const remote = !localCase(p) && c.s.features?.node_assignment === true;
 const start = useStartSop(p.id, remote, assignments.reload);
 const preview = start.state.kind === 'ready' ? start.state.data : undefined;
 const fallback = useSopTasks(p.id, c.s.workspace_id || '', !remote && sop.state.kind === 'forbidden');
 const local = sop.state.kind === 'forbidden' ? fallback : sop;
 const data = local.state.kind === 'ready' ? local.state.data : undefined;
 const exists = remote ? !!preview?.already_started : !!data?.tasks.some(task => !task.manual);
 const mayStart = remote ? !!preview?.can_start : !!data?.allowed.import;
 const flow = useEnsureSop(p.id, mayStart, exists, async () => {await Promise.all([local.reload(), assignments.reload()])});
 if (exists || flow.state.kind === 'started') return <Badge>SOP 已啟動</Badge>;
 if (flow.state.kind === 'preparing') return <div role="status">SOP 準備中<Skeleton lines={2}/></div>;
 if (flow.state.kind === 'failed' && !localCase(p) && !remote && ['writes_disabled', 'not_ready'].includes(flow.state.reason)) return null;
 if (flow.state.kind === 'failed') return <p role="status">SOP 尚未就緒<button className="text-button" onClick={flow.retry}>重試</button></p>;
 if (flow.state.kind === 'not_permitted' || (remote ? start.state.kind === 'forbidden' || !!preview && !preview.can_start : local.state.kind === 'forbidden' || !!data && !data.allowed.import)) return <p role="status">需由有權限的人員準備 SOP</p>;
 return null;
}
