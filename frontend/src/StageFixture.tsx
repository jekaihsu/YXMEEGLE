import {useEffect,useRef,useState} from 'react';
import {Button} from './design';
import {AssignDrawer} from './AssignDrawer';
import './StageWorkspace.css';
import './ProjectFlow.css';
import {NodeAssignmentError,type AssignablePerson,type AssignmentMutation,type AssignmentTask} from './nodeAssignmentApi';

export const FIXTURE_SCENARIOS=[
 ['normal','成功儲存'],['validation','欄位驗證（候選失效）'],['conflict','版本衝突'],['forbidden','伺服器 403'],
 ['timeout','逾時／結果不明'],['partial','部分儲存'],['revoked','儲存前能力被撤回'],
] as const;
export type FixtureScenario=typeof FIXTURE_SCENARIOS[number][0];
const people:AssignablePerson[]=[{open_id:'ou_syn_a',name:'合成 王小明',departments:['外業組']},{open_id:'ou_syn_b',name:'合成 李小華',departments:['外業組']},{open_id:'ou_syn_c',name:'合成 張大同',departments:['外業組']}];
const base:AssignmentTask={id:'syn-task-1',title:'合成驗證任務：現場紀錄核對',detail:'',assignee:null,assigned_by:null,department:'外業組',deadline:'2026-11-05',status:'待處理',revision:'syn-rev-1',record_id:'syn-task-1',done_at:null,created_at:null,can:{assign:true,edit_status:true,cancel:true,claim:false,edit_details:true}};
const fail=(status:number,message:string,code?:string,fields:Record<string,string>={})=>new NodeAssignmentError(status,message,code,fields);

export function StageFixture({scenario}:{scenario:string}){
 const active=(FIXTURE_SCENARIOS.find(([id])=>id===scenario)?.[0]||'normal') as FixtureScenario;
 const [task,setTask]=useState<AssignmentTask>(base);
 const [open,setOpen]=useState(false);
 const [log,setLog]=useState<string[]>([]);
 const attempts=useRef(0),latest=useRef(task);latest.current=task;
 const note=(line:string)=>setLog(l=>[...l,`${new Date().toLocaleTimeString('zh-TW',{hour12:false})} ${line}`]);
 useEffect(()=>{if(!open||active!=='revoked')return;const timer=setTimeout(()=>{note('模擬伺服器：你的指派權限已被撤回');setTask(t=>({...t,can:{...t.can,assign:false}}))},2500);return()=>clearTimeout(timer)},[open,active]);
 const person=(id?:string|null)=>id?people.find(p=>p.open_id===id)||null:null;
 const apply=(patch:Extract<AssignmentMutation,{action:'update_task'}>['patch'],revision:string)=>setTask(t=>({...t,...('assignee_open_id' in patch?{assignee:person(patch.assignee_open_id)}:{}),...('deadline' in patch?{deadline:patch.deadline??null}:{}),revision}));
 const mutate=async(m:AssignmentMutation,onFailure?:(message:string,failure:unknown)=>void)=>{
  if(m.action!=='update_task')return false;
  attempts.current++;note(`模擬 PATCH expected_revision=${m.expected_revision} 內容=${JSON.stringify(m.patch)}（未送出任何網路請求）`);
  await new Promise(r=>setTimeout(r,350));
  const error=(e:NodeAssignmentError)=>{onFailure?.(e.message,e);return false};
  if(active==='validation')return error(fail(422,'請檢查欄位內容後再試。',undefined,{assignee_open_id:'此人員已停用或不可指派，請改選其他人。'}));
  if(active==='conflict'&&attempts.current===1){setTask(t=>({...t,assignee:people[2],revision:'syn-rev-2'}));return error(fail(409,'已被他人更新','revision_conflict'))}
  if(active==='forbidden'){setTask(t=>({...t,can:{...t.can,assign:false}}));return error(fail(403,'沒有指派權限','forbidden'))}
  if(active==='timeout'&&attempts.current===1)return error(fail(408,'連線逾時','client_timeout'));
  if(active==='partial'){setTask(t=>({...t,assignee:person(m.patch.assignee_open_id)||t.assignee,revision:'syn-rev-partial'}));return error(fail(502,'結果未知','outcome_unknown'))}
  apply(m.patch,`syn-rev-${attempts.current+2}`);note('模擬伺服器：已儲存');return true;
 };
 const retry=async()=>{note('以同一個 request_id 重試（模擬）');attempts.current++;await new Promise(r=>setTimeout(r,250));setTask(t=>({...t,assignee:people[0],revision:'syn-rev-retry'}));return true};
 const verify=async()=>{await new Promise(r=>setTimeout(r,250));note('模擬重新讀取最新任務');return latest.current};
 return <div className="project-detail project-detail-calm stage-fixture">
  <h1>合成驗證環境：任務指派流程</h1>
  <p role="note" className="cs-note"><strong>這是合成資料。</strong>此頁不讀取也不寫入任何真實案件、任務或 Lark，操作只在瀏覽器記憶體中模擬，不會送出任何寫入請求。</p>
  <nav aria-label="情境" className="pf-filters">{FIXTURE_SCENARIOS.map(([id,label])=><a key={id} className="button" aria-current={id===active?'page':undefined} href={`#view=stage-fixture&tab=${id}`} onClick={()=>{setTask(base);setLog([]);attempts.current=0;setOpen(false)}}>{label}</a>)}</nav>
  <section className="po-card" aria-label="合成任務">
   <h2>節點任務（合成）</h2>
   <ul className="pf-task-list"><li data-assignment-task={task.id}><div className="pf-task-line"><span><strong>{task.title}</strong><span className="st-meta"><span>任務狀態：{task.status}</span><span>執行人：{task.assignee?.name||'尚未指派'}</span><span>{task.deadline||'未排期限'}</span></span></span><Button disabled={!task.can.assign} disabledReason="你可查看此任務，但目前無指派權限。" onClick={()=>setOpen(true)}>{task.assignee?'改派':'指派'}</Button></div></li></ul>
   <p role="status">目前情境：{FIXTURE_SCENARIOS.find(([id])=>id===active)![1]}。{active==='partial'&&'請同時修改執行人與期限後儲存。'}{active==='revoked'&&'開啟抽屜後約 2.5 秒，模擬伺服器撤回你的指派權限。'}</p>
  </section>
  <section className="po-card" aria-label="模擬請求紀錄"><h2>模擬請求紀錄</h2><p>真實網路寫入：0（本頁沒有呼叫 fetch）</p><ol>{log.map((l,i)=><li key={i}>{l}</li>)}</ol></section>
  {open&&<AssignDrawer task={task} nodeKey="field" nodeLabel="外業（合成）" caseLabel="SYN-0001 合成案件" people={people} unavailableReason="" mutate={mutate} retry={retry} verify={verify} refresh={()=>note('重新讀取能力（模擬）')} onClose={()=>setOpen(false)}/>}
 </div>;
}
