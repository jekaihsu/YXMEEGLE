import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import App from '../../../../frontend/src/App';
import {DraftForm,DraftNamespace} from '../../../../frontend/src/FormDraft';
import {AuditTrail} from '../../../../frontend/src/AuditTrail';
import {DailyRecords} from '../../../../frontend/src/DailyRecords';
import dailyData from './daily-data.json';
const a:any={id:'actor-A',name:'ACTOR_A',role:'manager',department:'demo',capabilities:[]};
const b:any={...a,id:'actor-B',name:'ACTOR_B',role:'member'};
const task:any={id:'tA',title:'TASK_A',owner_id:a.id,status:'pending',required:true,revision:1,can_execute:true,start_date:null,due_date:null,original_due_date:null,started_at:null,completed_at:null,points:null,description:'',input:'',output:'',comments:[]};
const node:any={id:'nA',name:'Sales',key:'sales',owner_id:a.id,supervisor_id:a.id,collaborator_ids:[],status:'in_progress',tasks:[task],requirements:[],reviewers:[],review_cycles:[],start_date:null,due_date:null};
const project:any={id:'pA',code:'PRIVATE_CASE_A',name:'PRIVATE_CASE_A',client:'synthetic',pm_id:a.id,supervisor_id:a.id,admin_id:a.id,status:'active',priority:'normal',due_date:'2026-12-31',original_due_date:'2026-12-31',created_at:'2026-10-03',started_at:'2026-10-03',source_kind:'demo',revision:1,nodes:[node],files:[],comments:[],daily_reports:[],execution_allowed:true,execution_system:'workbench'};
const workspace:any={version:1,workspace_id:'workspace-A',environment:'production',as_of:'2026-10-03T01:00:00+08:00',users:[a,b],projects:[project],approvals:[],events:[],calendar:{holidays:[],workdays:[]},source_status:{status:'ready',last_sync:'',message:''},settings:{},jobs:[],policy_summary:[],sop_templates:[]};
workspace.projects.push({...project,id:'pB',code:'CASE_B',name:'CASE_B',nodes:[{...node,id:'nB',tasks:[]}]});
let actor=a;let resolveAction:any;
(window as any).review3={switchActor:()=>{actor=b},releaseAction:()=>resolveAction(new Response(JSON.stringify({...workspace,version:2}),{status:200,headers:{'content-type':'application/json'}}))};
const json=(data:any,status=200)=>Promise.resolve(new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json'}}));
window.fetch=async(input:any,init:any)=>{const url=String(input);if(url.startsWith('/api/daily-reports')){if(mode==='daily-status')return json(dailyData);const params=new URLSearchParams(url.split('?')[1]);const total=params.get('project_id')==='pA'?61:1;const offset=Number(params.get('offset'));return json({items:offset<total?[{...dailyData.items[0],description:'VISIBLE_DAILY_'+params.get('project_id')}]:[],total,summary:{unmatched:0}})}if(url==='/api/session')return json({user:actor,users:[a,b],mode:'lark',auth_configured:true,environment:'production',workspace_id:actor===a?'workspace-A':'workspace-B'});if(url==='/api/workspace')return json(actor===a?workspace:{...workspace,workspace_id:'workspace-B',projects:[]});if(url==='/api/actions')return new Promise(resolve=>{resolveAction=resolve;(window as any).review3.actionPending=true});if(url.startsWith('/api/audit'))return url.includes('pA')?json({items:[{id:'audit-A',message:'PRIVATE_AUDIT_A',actor_name:'ACTOR_A',created_at:'2026-10-03'}],total:1}):json({detail:'synthetic B failed'},503);return json({detail:'mock endpoint not configured: '+url},404)};
function DraftProof(){const[mount,setMount]=useState(true);return <DraftNamespace.Provider value="synthetic"><button onClick={()=>setMount(!mount)}>Toggle forms</button>{mount&&['RECORD_A','RECORD_B'].map(record=><section key={record} data-record={record}><h2>{record}</h2><DraftForm title="記錄本次執行" busy={false} onSubmit={values=>(window as any).review3.submitted={record,...values}}><label>Result<input name="evidence"/></label></DraftForm></section>)}</DraftNamespace.Provider>}
function AuditProof(){const[id,setId]=useState('pA');return <><button onClick={()=>setId('pB')}>Switch to B audit</button><h1>{id}</h1><AuditTrail w={workspace} p={{...project,id}}/></>}
function DailyProof(){const[id,setId]=useState('pA');return <><button onClick={()=>setId('pB')}>Switch to B daily</button><h1>{id}</h1><DailyRecords w={workspace} p={{...project,id}} go={()=>{}}/></>}
const mode=new URLSearchParams(location.search).get('mode');
if(mode==='comment'){const priorFetch=window.fetch;window.fetch=async(input:any,init:any)=>{if(String(input)==='/api/actions'){(window as any).review3.commentSubmitted=JSON.parse(init.body);return json({...workspace,version:2})}return priorFetch(input,init)}}
createRoot(document.getElementById('root')!).render(mode==='draft'?<DraftProof/>:mode==='audit'?<AuditProof/>:mode?.startsWith('daily')?<DailyProof/>:<App/>);
