import {build,preview} from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {embeddedAssignmentFixture,projectFixture} from '../fixtures/node-assignments.mjs';
import {createPublishMock} from './dispatch-publish-mock.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
const sourceProgress=JSON.parse(await fs.readFile(new URL('../fixtures/project-progress.json',import.meta.url),'utf8'));
let state='ready',role='manager',delay=0,calls=[];
let base,assignments,progress;
function reset(){
 base=projectFixture();base.project.name='合成驗證 · 港區測量與成果交付';base.project.source_kind='lark';base.project.execution_allowed=true;
 Object.assign(base.workspace,{environment:'test',workspace_id:'project-flow-fixture',as_of:'2026-10-18T08:00:00+08:00',source_status:{status:'ready',last_sync:'2026-10-18T08:00:00+08:00'}});
 assignments=embeddedAssignmentFixture();assignments.list.fetched_at='2026-10-18T08:00:00+08:00';assignments.list.summary.current_node='field';
 for(const n of assignments.list.nodes){
  n.departments=n.key==='field'?['外業組']:['控制'];n.owners=[{open_id:base.user.id,name:'合成 林專案經理'}];n.assigned_by={open_id:base.user.id,name:'合成 林主管'};
  const payload=assignments.list.node_details[n.key];payload.assignable_people=[{open_id:'ou_anna',name:'合成 林安娜',departments:n.departments},{open_id:'ou_wei',name:'合成 陳威廷',departments:n.departments}];
  payload.tasks=['field','control'].includes(n.key)?[
   {id:`rec${n.key}Task1`,revision:'task-r1',record_id:`rec${n.key}Task1`,title:n.key==='field'?'外業控制點複測':'控制點成果核對',detail:'合成驗證資料，核對現場紀錄與座標。',assignee:{open_id:'ou_wei',name:'合成 陳威廷'},assigned_by:n.assigned_by,department:n.departments[0],deadline:'2026-10-20',status:'進行中',done_at:null,created_at:'2026-10-14',can:{assign:true,edit_status:true,cancel:true,edit_details:true}},
   {id:`rec${n.key}Task2`,revision:'task-r2',record_id:`rec${n.key}Task2`,title:'待指派 · 現場紀錄核對',detail:'合成驗證任務，尚無負責人。',assignee:null,assigned_by:n.assigned_by,department:n.departments[0],deadline:'2026-10-10',status:'待處理',done_at:null,created_at:'2026-10-14',can:{assign:true,edit_status:true,cancel:true,edit_details:true}},
   {id:`rec${n.key}Task3`,revision:'task-r3',record_id:`rec${n.key}Task3`,title:'已完成 · 前期資料整理',detail:'合成驗證。',assignee:{open_id:base.user.id,name:'合成 林專案經理'},assigned_by:n.assigned_by,department:n.departments[0],deadline:'2026-10-12',status:'已完成',done_at:'2026-10-12',created_at:'2026-10-10',can:{assign:true,edit_status:true,cancel:true,edit_details:true}}
  ]:[];
  n.tasks={done:payload.tasks.filter(t=>t.status==='已完成').length,total:payload.tasks.length};n.derived_status=['sales','pm','confirmation'].includes(n.key)?'已完成':n.key==='field'?'進行中':'未開始';n.next_due=payload.tasks.length?'2026-10-10':null;n.deadline=payload.tasks.length?'2026-10-20':null;
 }
 if(state==='completed'){assignments.list.nodes.find(n=>n.key==='control').derived_status='已完成';assignments.list.nodes.find(n=>n.key==='mapping').derived_status='略過'}
 for(const key of ['field','control'])assignments.list.nodes.find(n=>n.key===key).evidence={planned_qty:'12',lines:1,items:1,work_orders:0,latest_date:null,actual_known:false,actual_value:null,actual_source:null,reason:'實際完成量來源未連結',drives_status:false,progress:null,items_total:1,items_truncated:false,work_items:[{code:'X1',name:'現場控制點',planned_qty:'12',planned_points:null,remaining_points:null,status:'no_signal',link_basis:'native'}]};
 for(const n of base.project.nodes)n.tasks=n.key==='field'?[{id:'legacyTask',title:'合成本地核對任務',owner_id:base.user.id,status:'pending',required:true,start_date:null,due_date:'2026-10-23',original_due_date:null,started_at:null,completed_at:null,points:null,work_item_id:'',description:'合成本地流程',input:'',output:'',comments:[],revision:1}]:[];
 progress=structuredClone(sourceProgress);progress.project_id='p1';progress.production.field.planned.qty='187';progress.production.control.planned.qty='348';progress.production.field.actual={known:false,value:null,unit_note:null,source:null,reason:'實際完成量來源未連結。日報尚未指定所屬案件與合約工項。'};
}
reset();
const publish=createPublishMock();
const outDir=process.env.PROJECT_FLOW_DIST||fileURLToPath(new URL('../.runtime-flow-dist/',import.meta.url));
await build({root,configFile:false,plugins:[react()],logLevel:'warn',build:{outDir,emptyOutDir:true}});
const server=await preview({root,configFile:false,plugins:[{name:'project-flow-fixtures',configurePreviewServer(server){server.middlewares.use(async(req,res,next)=>{
 const url=new URL(req.url,'http://localhost');const send=(body,status=200)=>{res.statusCode=status;res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control','no-store');res.end(JSON.stringify(body))};
 const body=async()=>{let raw='';for await(const chunk of req)raw+=chunk;return JSON.parse(raw||'{}')};
 if(url.pathname==='/__flow-test/state'){if(req.method==='POST'){const update=await body();state=update.state||'ready';delay=update.delay||0;role=update.role||'manager';calls=[];reset()}return send({state,delay,role,calls,label:'合成驗證資料，無外部 Lark 連線'})}
 if(url.pathname.startsWith('/api/'))calls.push({url:req.url,method:req.method});
 const user={...base.user,name:'合成 林專案經理',role};
 if(url.pathname==='/api/session')return send({workspace_id:'project-flow-fixture',user,users:[user],mode:'lark',environment:'test',auth_configured:false,features:{workspace_shell:false,node_assignment:state!=='legacy',dispatch_write:true,dispatch_board:true}});
 if(url.pathname==='/api/workspace')return send({...base.workspace,users:[user],projects:[base.project]});
 if(url.pathname==='/api/projects/p1')return send({...base.workspace,scope:'project',project:base.project});
 if(url.pathname==='/api/projects/p1/progress'){if(delay)await new Promise(r=>setTimeout(r,delay));return send(state==='evidence-error'?{detail:'合成證據來源讀取失敗'}:progress,state==='evidence-error'?500:200)}
 if(url.pathname==='/api/projects/p1/node-assignments'){if(state==='loading')await new Promise(r=>setTimeout(r,delay||8000));return send(assignments.list)}
 if(url.pathname.startsWith('/api/projects/p1/node-assignments/nodes/')){
  const parts=url.pathname.split('/'),key=parts[6],node=assignments.list.nodes.find(n=>n.key===key),payload=assignments.list.node_details[key];if(!node)return send({detail:'找不到節點'},404);
  if(req.method==='PATCH'){const patch=await body(),task=payload.tasks.find(t=>t.id===parts.at(-1));if(patch.assignee_open_id)task.assignee=payload.assignable_people.find(p=>p.open_id===patch.assignee_open_id);if(patch.status)task.status=patch.status;task.revision+='x'}
  if(req.method==='POST'&&parts.at(-1)==='tasks'){const draft=await body();payload.tasks.push({...assignments.list.node_details.field.tasks[0],...draft,id:`recCreated${payload.tasks.length}`,record_id:`recCreated${payload.tasks.length}`,status:'待處理',assignee:payload.assignable_people.find(p=>p.open_id===draft.assignee_open_id)||null,revision:'created-r1'})}
  node.tasks={done:payload.tasks.filter(t=>t.status==='已完成').length,total:payload.tasks.filter(t=>t.status!=='取消').length};
  return send({...assignments.list,node,can:assignments.list.can[key],...payload});
 }
 if(url.pathname==='/api/v2/dispatch/work')return send({source:{quality:{states:['complete']}},rows:[{task_id:'recParentObligation',title:'合成 外業交付義務',project_id:'p1',kind:'obligation',phase:'正式',status:'待處理',department:'外業組',case:{ref:'synthetic-case',code:'合成 C001',name:'港區測量'},node_position:'外業',source:'v4_task'}]});
 if(await publish({req,url,send,state:'loaded',user:{id:'synthetic-dispatcher',name:user.name,role},delay:0}))return;
 if(url.pathname==='/api/company-dashboard')return send({source:{status:'ready'},complete:true,totals:{execution_status_counts:{}},groups:[],cases:[]});
 if(url.pathname==='/api/home-panels')return send({readState:'ready',items:[],counts:{node_assignments:0,tasks:0,complete:true},complete:true,has_more:false});
 if(url.pathname.startsWith('/api/'))return send({detail:'此合成驗證未提供此來源'},404);
 next();
})}}],build:{outDir},preview:{host:'127.0.0.1',port:Number(process.env.PROJECT_FLOW_TEST_PORT||5208),strictPort:true}});
server.printUrls();
