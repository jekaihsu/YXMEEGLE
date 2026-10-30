import type {useSopTasks} from './useSopTasks';
import {defaultChecklistState, DEFAULT_CHECKLIST_NEXT_STEP} from './sopTaskModel';
export function CaseSopStart({sop}:{projectId:string;sop:ReturnType<typeof useSopTasks>}) {
 const data=sop.state.kind==='ready'?sop.state.data:undefined;
 return defaultChecklistState(data)==='not-applied' ? <p role="status">預設清單尚未套用。{DEFAULT_CHECKLIST_NEXT_STEP}</p> : null;
}
