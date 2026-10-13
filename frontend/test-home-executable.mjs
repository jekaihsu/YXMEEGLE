// VCC-119: one executable-task rule drives the sidebar badge, the full Dashboard and the shell Dashboard.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({stdin:{contents:"export {Dashboard,ShellDashboard} from './src/DailyHome';export {homeOverdueCount} from './src/executableTasks';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.home-executable-bundle.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);
let Dashboard,ShellDashboard,homeOverdueCount;try{({Dashboard,ShellDashboard,homeOverdueCount}=await import(path.href))}finally{await fs.unlink(path)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=dashboard'});
for(const key of ['window','document','location','history','sessionStorage','Event'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const ME='viewer',OTHER='other',ASOF='2026-10-07T09:00:00+08:00';
const task=(id,owner,due,status='pending')=>({id,title:id,owner_id:owner,status,required:true,due_date:due,original_due_date:due,start_date:null,started_at:null,completed_at:null,points:null,comments:[],revision:1,can_execute:owner===ME});
const node=(pid,tasks)=>({id:pid+'-sales',key:'sales',name:'報價',owner_id:'',supervisor_id:'',collaborator_ids:[],status:'pending',start_date:null,due_date:null,tasks,requirements:[],reviewers:[],review_cycles:[]});
const project=(id,execution_status,tasks,over={})=>({id,code:id.toUpperCase(),name:'合成案件 '+id,client:'',pm_id:'',status:execution_status,execution_status,case_type:'formal',priority:'medium',due_date:'',original_due_date:'',created_at:'',nodes:[node(id,tasks)],files:[],comments:[],daily_reports:[],...over});
// paused case with the viewer's own dated tasks; enabled case with a mix; a template-shaped paused case (unassigned, dated)
const projects=[
 project('p1','paused',[task('pz-late1',ME,'2026-10-01'),task('pz-late2',ME,'2026-09-20'),task('pz-today',ME,'2026-10-07')]),
 project('p2','in_progress',[task('lv-late1',ME,'2026-10-01'),task('lv-late2',ME,'2026-10-05T09:00:00+08:00'),task('lv-today',ME,'2026-10-07'),task('lv-unassigned','','2026-10-01'),task('lv-other',OTHER,'2026-10-02'),task('lv-done',ME,'2026-10-01','completed')]),
 project('p3','paused',[task('tp-late','','2026-09-10'),task('tp-late2','','2026-09-10')],{case_type:'intake'}),
];
const full={version:1,as_of:ASOF,users:[{id:ME,name:'檢視者',role:'member'},{id:OTHER,name:'他人',role:'member'}],projects,approvals:[],events:[],source_status:{status:'ready'},calendar:{holidays:[],workdays:[]}};
const shell={...full,scope:'shell',projects:projects.map(({nodes,files,comments,daily_reports,...card})=>({...card,overdue_tasks:0,active_tasks:0,progress:{completed_nodes:0,total_nodes:9}})),
 // what backend/shell.py returns for the same fixture (backend/test_home_executable_tasks.py)
 counts:{approvals_pending:0,daily_unmatched:0,my_overdue_tasks:2,my_active_tasks:3,active_tasks:9,overdue_tasks:2,due_today_tasks:1},
 attention:['lv-late1','lv-late2','lv-today'].map(id=>({task_id:id,project_id:'p2',project_code:'P2',node_id:'p2-sales',node_key:'sales',node_name:'報價',assignee_id:ME,status:'pending',due_date:id==='lv-today'?'2026-10-07':'2026-10-01',title:id}))};
const read=async(Component,w)=>{const host=document.getElementById('root');host.innerHTML='';const root=createRoot(host);const c={w,s:{mode:'demo',user:{id:ME,role:'member'}},go(){},route:{view:'dashboard'}};
 await act(async()=>{root.render(React.createElement(Component,{c}))});const inbox=host.querySelector('.work-inbox');const out={count:inbox.querySelector('.heading-count').textContent,caption:inbox.querySelector('h2 small')?.textContent||''};await act(async()=>root.unmount());return out};
let checks=0;const ok=(cond,msg)=>{assert.ok(cond,msg);checks++};
const dash=await read(Dashboard,full),sh=await read(ShellDashboard,shell);
ok(dash.count==='3'&&sh.count==='3',`Dashboard and Shell attention count are both 3 (paused/unassigned/other/closed excluded): ${dash.count} | ${sh.count}`);
ok(dash.caption.includes('本人可執行逾期 2')&&sh.caption.includes('本人可執行逾期 2'),`overdue 2 in both captions: ${dash.caption} | ${sh.caption}`);
ok(dash.caption.includes('當日到期 1')&&sh.caption.includes('當日到期 1'),'due today 1 in both captions');
ok(!dash.caption.includes('非本人')&&!sh.caption.includes('非本人'),'no other-people lateness in Home captions');
ok(homeOverdueCount(full)===2&&homeOverdueCount(shell)===2,'sidebar badge: full rule === shell count === 2');
ok(homeOverdueCount({...full,projects:[projects[0],projects[2]]})===0,'paused and template-only cases give a zero badge');
const app=await fs.readFile('src/App.tsx','utf8');
ok(app.includes('homeOverdueCount(w)'),'App sidebar badge uses the shared helper');
console.log(`home executable rule checks passed: ${checks}`);
