import {Badge} from './design';
import type {SopTask} from './sopTaskApi';

export function SopLarkSync({task, link = false}: {task: SopTask; link?: boolean}) {
 const sync = task.larkSync;
 const url = sync.recordId && sync.baseId && sync.tableId
  ? `https://yong-xiang-survey.jp.larksuite.com/base/${encodeURIComponent(sync.baseId)}?table=${encodeURIComponent(sync.tableId)}&record=${encodeURIComponent(sync.recordId)}` : null;
 return <><Badge>{sync.state}</Badge>{link && url && <a href={url} target="_blank" rel="noreferrer">開啟 Lark 列</a>}</>;
}
