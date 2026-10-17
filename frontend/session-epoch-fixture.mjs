// Synthetic workspace for session identity regression tests.
export const a={id:'actor-A',name:'ACTOR_A',role:'manager',department:'demo',capabilities:[]};
export const b={...a,id:'actor-B',name:'ACTOR_B',role:'member'};
const task={id:'tA',title:'TASK_A',owner_id:a.id,status:'pending',required:true,revision:1,can_execute:true,start_date:null,due_date:null,original_due_date:null,started_at:null,completed_at:null,points:null,description:'',input:'',output:'',comments:[]};
const node={id:'nA',name:'Sales',key:'sales',owner_id:a.id,supervisor_id:a.id,collaborator_ids:[],status:'in_progress',tasks:[task],requirements:[],reviewers:[],review_cycles:[],start_date:null,due_date:null};
const project={id:'pA',code:'PRIVATE_CASE_A',name:'PRIVATE_CASE_A',client:'synthetic',pm_id:a.id,supervisor_id:a.id,admin_id:a.id,status:'active',priority:'normal',due_date:'2026-12-31',original_due_date:'2026-12-31',created_at:'2026-10-03',started_at:'2026-10-03',source_kind:'demo',revision:1,nodes:[node],files:[],comments:[],daily_reports:[],execution_allowed:true,execution_system:'workbench'};
export const workspace={version:1,workspace_id:'workspace-A',environment:'production',as_of:'2026-10-03T01:00:00+08:00',users:[a,b],projects:[project],approvals:[],events:[],calendar:{holidays:[],workdays:[]},source_status:{status:'ready',last_sync:'',message:''},settings:{},jobs:[],policy_summary:[],sop_templates:[]};
workspace.projects.push({...project,id:'pB',code:'CASE_B',name:'CASE_B',nodes:[{...node,id:'nB',tasks:[]}]});
