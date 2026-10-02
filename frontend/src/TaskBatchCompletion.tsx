import {executionAllowed} from './ProjectExecution';
import {useState} from 'react';
import {draftKey,useDraft} from './drafts';
import type {Node,Project,Session,Task,Workspace} from './types';

type Row={p:Project;n:Node;t:Task};
export function TaskBatchCompletion({w,s,rows,busy,run}:{w:Workspace;s:Session;rows:Row[];busy:boolean;run:(action:string,payload:Record<string,unknown>)=>Promise<Workspace|undefined>}){
 const[open,setOpen]=useState(false);const[selected,setSelected]=useState<string[]>([]);
 const[drafts,setDrafts]=useDraft<Record<string,string>>(draftKey(s,w,'batch-outputs'),{});
 const[message,setMessage]=useState('');
 const eligible=rows.filter(({p,t})=>executionAllowed(p,w)&&t.owner_id===s.user?.id&&t.can_execute===true&&['in_progress','rework'].includes(t.status)&&typeof t.confirmation_hash==='string');
 const chosen=eligible.filter(r=>selected.includes(r.t.id));
 const submit=async()=>{
  setMessage('');
  const result=await run('task_batch_complete',{items:chosen.map(({p,n,t})=>({project_id:p.id,node_id:n.id,task_id:t.id,revision:t.revision,confirmation_hash:t.confirmation_hash,output:(drafts[t.id]??t.output??'').trim()}))});
  if(result){setMessage(`已確認 ${chosen.length} 項本人工作。節點依 SOP 繼續確認。`);setDrafts(previous=>Object.fromEntries(Object.entries(previous).filter(([id])=>!selected.includes(id))));setSelected([])}
  else setMessage('這批尚未確認成功，成果文字已保留。請核對上方錯誤及最新狀態後再試。');
 };
 return <section className="batch-completion" aria-label="本人多項成果確認"><button className="button" onClick={()=>setOpen(!open)} aria-expanded={open}>一次確認我的成果（{eligible.length}）</button>{open&&<div className="batch-editor"><h3>確認本人已完成的工作</h3><p>逐項填寫成果後一次送出；只包含你本人負責且已啟用的項目，任何一項不符合條件，整批都不會完成。</p>{!eligible.length&&<p>目前沒有可一次確認的本人項目。未開始或缺前置成果的工作，請先查看流程。</p>}{eligible.map(({p,n,t})=><div className="batch-item" key={t.id}><label><input type="checkbox" checked={selected.includes(t.id)} disabled={busy||(!selected.includes(t.id)&&selected.length>=50)} onChange={e=>setSelected(ids=>e.target.checked?[...ids,t.id]:ids.filter(id=>id!==t.id))}/><strong>{t.title}</strong><small>{p.code} · {n.name}</small></label>{selected.includes(t.id)&&<label>成果說明<textarea value={drafts[t.id]??t.output??''} onChange={e=>setDrafts(d=>({...d,[t.id]:e.target.value}))} rows={3}/></label>}</div>)}<button className="button primary" disabled={busy||!chosen.length||chosen.some(({t})=>!(drafts[t.id]??t.output??'').trim())} onClick={()=>void submit()}>確認這 {chosen.length} 項成果</button><p role="status">{message}</p><small>文字草稿暫存於此分頁，24 小時後失效；登出會清除。尚未送出不算交付。</small></div>}</section>;
}
