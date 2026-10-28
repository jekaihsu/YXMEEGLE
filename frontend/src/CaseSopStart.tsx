import type {useSopTasks} from './useSopTasks';
export function CaseSopStart({sop}:{projectId:string;sop:ReturnType<typeof useSopTasks>}) {
 const data='data' in sop.state?sop.state.data:undefined;
 return data && !data.allowed.import && !data.tasks.some(task=>!task.manual) ? <p role="status">需由有權限的人員準備 SOP</p> : null;
}
