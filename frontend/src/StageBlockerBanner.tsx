import {ChevronDown} from 'lucide-react';
import {primaryBlockerReasons} from './stageModel';
export function StageBlockerBanner({reasons}:{reasons:string[]}){
 const [primary,...rest]=primaryBlockerReasons(reasons);
 if(!primary)return null;
 return <div className="pg-callout st-blocker-banner" role="status"><p>{primary}</p>{rest.length>0&&<details><summary>詳細原因<ChevronDown size={16} aria-hidden="true"/></summary>{rest.map(reason=><p key={reason}>{reason}</p>)}</details>}</div>;
}
