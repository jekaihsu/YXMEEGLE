import {taipeiTime} from './taipeiTime';
import type {NodeAssignmentList} from './nodeAssignmentApi';
import type {useNodeAssignments} from './useNodeAssignments';

/** A settled old snapshot is not an in-flight read. Keep its write gate honest. */
export function nodeReadBlock(assignments:Pick<ReturnType<typeof useNodeAssignments>,'state'|'refreshing'|'pending'>,list:NodeAssignmentList|undefined):string {
 if(assignments.pending)return '正在儲存節點資料，請稍候。';
 if(assignments.refreshing||assignments.state.kind==='loading')return '正在讀取節點資料，請稍候。';
 if(assignments.state.kind==='error')return '節點來源讀取失敗，請重新讀取。';
 if(list?.stale)return `節點資料待更新，請重新讀取。資料時間 ${taipeiTime(list.fetched_at,'來源未提供')}`;
 if(assignments.state.kind!=='ready')return '節點資料尚未開放。';
 return '';
}
