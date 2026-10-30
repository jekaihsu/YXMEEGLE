import {Button} from './design';
import type {FlowNode} from './flowModel';
import {nodeStats,type StageContext} from './stageModel';
export function NodeStats({node,current,onCurrent}:{node:FlowNode;current:StageContext;onCurrent:()=>void}){
 const stats=nodeStats(node);
 const names=current.currentIds.map(key=>current.nodes.find(n=>n.key===key)?.label||key);
 return <div className="nc-stats">
  <p className="nc-progress"><strong>任務完成數：{stats.label}</strong>{stats.percent!==null&&<> · <span>{stats.percent}%</span></>}</p>
  {stats.percent!==null&&<progress value={stats.percent} max={100} aria-label={`${node.label}任務完成度 ${stats.percent}%`}/>}
  {!current.currentSelected&&names.length>0&&<p className="nc-diff" role="status">目前階段：{names.join('、')}。你正在閱讀的是「{node.label}」。<Button variant="plain" onClick={onCurrent}>回到目前階段</Button></p>}
 </div>;
}
