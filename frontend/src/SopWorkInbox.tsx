import {useState} from 'react';
import type {Ctx} from './appCommon';
import {useSopWork} from './useSopTasks';
import {SopWorkSummary,sopTaskHref,type SopWorkProjection} from './SopWorkSummary';

export function SopWorkInbox({c}:{c:Ctx}) {
 const read=useSopWork(c.reloadVersion??c.w.version,c.s?.workspace_id||'',c.s?.user?.id||'');
 if(read.kind==='loading')return <p role="status">正在載入 SOP 工作…</p>;
 if(read.kind==='error')return <p role="alert">SOP 工作讀取失敗，請重新載入。</p>;
 return <SopWorkList data={read.data}/>;
}

export function SopWorkList({data}:{data:SopWorkProjection|null}) {
 const [reviewing,setReviewing]=useState(false),[showTasks,setShowTasks]=useState(false);
 if(!data)return null;
 const reviewers=data.reviewer_items||[];
 return <section className="work-inbox" aria-label="我的 SOP 工作"><h2>我的 SOP 工作</h2><SopWorkSummary signals={data.signals} items={data.items}/>
  <button type="button" className="button" aria-expanded={showTasks} onClick={()=>setShowTasks(!showTasks)}>指派給我的 SOP 任務 {data.items.filter(t=>!['done','archived'].includes(t.state)).length}</button>
  {showTasks&&<ul>{data.items.filter(t=>!['done','archived'].includes(t.state)).map(t=><li key={t.id}><a href={sopTaskHref(t)}>{t.title}</a> · {t.completion_policy==='formal_external'?'正式審批處理':t.completion_policy==='reviewer_required'?'重要任務 · 提交審核':'一般任務 · 完成'}{t.review_status==='submitted'&&' · 已提交／待審核'}{t.review_status==='returned'&&t.return_reason&&<p>退回原因：{t.return_reason}。請修正後重新提交。</p>}</li>)}</ul>}
  {reviewers.length>0&&<><button type="button" className="button" aria-expanded={reviewing} onClick={()=>setReviewing(!reviewing)}>待我審核 {reviewers.length}</button>{reviewing&&<ul>{reviewers.map(t=><li key={t.id}><a href={sopTaskHref(t)}>{t.title}</a> · 已提交／待審核</li>)}</ul>}</>}
 </section>;
}
