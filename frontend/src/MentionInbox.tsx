import {useState} from 'react';
import type {Workspace,Comment} from './types';

type Target={project:string;node?:string;task?:string;comment:string};
export function MentionInbox({w,userId,onOpen}:{w:Workspace;userId:string;onOpen:(target:Target)=>void}){
 const[expanded,setExpanded]=useState(false);
 const rows:{key:string;comment:Comment;projectName:string;taskName?:string;target:Target}[]=[];
 for(const project of w.projects){
  for(const comment of project.comments||[])if(comment.mentions?.includes(userId))rows.push({key:project.id+':'+comment.id,comment,projectName:project.code+' · '+project.name,target:{project:project.id,comment:comment.id}});
  for(const node of project.nodes)for(const task of node.tasks)for(const comment of task.comments||[])if(comment.mentions?.includes(userId))rows.push({key:project.id+':'+task.id+':'+comment.id,comment,projectName:project.code+' · '+project.name,taskName:task.title,target:{project:project.id,node:node.id,task:task.id,comment:comment.id}});
 }
 rows.sort((a,b)=>b.comment.created_at.localeCompare(a.comment.created_at));
 if(!rows.length)return null;
 return <section className="mention-inbox" aria-label="提及我的留言"><div className="section-heading"><div><h2>提及我的留言 <span>{rows.length}</span></h2><p>工作台內的標註紀錄，可直接前往留言。</p></div></div>
  {(expanded?rows:rows.slice(0,5)).map(row=><button type="button" className="mention-inbox-row" key={row.key} onClick={()=>onOpen(row.target)}><span><strong>{w.users.find(u=>u.id===row.comment.author_id)?.name||'原留言同事'} 標註了你</strong><small>{row.projectName}{row.taskName?' · '+row.taskName:''}</small><span>{row.comment.body.length>160?row.comment.body.slice(0,160)+'…':row.comment.body}</span></span><time dateTime={row.comment.created_at}>{new Date(row.comment.created_at).toLocaleDateString('zh-TW')}</time></button>)}
  {rows.length>5&&<button type="button" className="text-button" onClick={()=>setExpanded(value=>!value)}>{expanded?'收起較早的留言':`查看全部 ${rows.length} 筆標註紀錄`}</button>}
 </section>;
}
