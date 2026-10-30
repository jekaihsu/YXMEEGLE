import {Badge} from './design';
import {defaultChecklistState, DEFAULT_CHECKLIST_NEXT_STEP} from './sopTaskModel';
import {useSopTasks} from './useSopTasks';
import type {useNodeAssignments} from './useNodeAssignments';
import type {Ctx} from './appCommon';
import type {Project} from './types';

export function EnsureSopStatus({c, p, sop}: {c: Ctx; p: Project; sop: ReturnType<typeof useSopTasks>; assignments: ReturnType<typeof useNodeAssignments>}) {
 const fallback = useSopTasks(p.id, c.s.workspace_id || '', sop.state.kind === 'forbidden');
 const local = sop.state.kind === 'forbidden' ? fallback : sop;
 const data = local.state.kind === 'ready' ? local.state.data : undefined;
 const state = defaultChecklistState(data);
 if (state === 'applied') return <Badge>SOP 已啟動</Badge>;
 if (state === 'not-applied') return <div role="status"><Badge>預設清單尚未套用</Badge><p>{DEFAULT_CHECKLIST_NEXT_STEP}</p></div>;
 return <p role="status">預設清單狀態待確認</p>;
}
