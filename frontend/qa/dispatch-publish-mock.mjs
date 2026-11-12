import {createHash} from 'node:crypto';
export const syntheticLabel='合成資料（synthetic），不連線、不寫入 Lark';
const people=[{person_ref:'synthetic-dispatcher',name:'合成 林派工'},{person_ref:'synthetic-leader',name:'合成 陳組長'},{person_ref:'synthetic-pm',name:'合成 王專案經理'}];
const base={task_id:'synthetic-task-1',title:'合成 港區水深測量',content:'完成測區量測並核對儀器紀錄。',case:{ref:'synthetic-case',code:'合成 C001',name:'港區測量'},project_id:'synthetic-project',package_id:'PKG-SYNTHETIC',kind:'execution',phase:'正式',status:'進行中',planning_status:'pending_approval',acceptance_status:'審核中',acceptance_summary:'尚待成果核對',owner:people[0],crew:people.slice(0,2),interval:{start:'2026-10-19T08:00:00+08:00',end:'2026-10-19T12:00:00+08:00',precision:'datetime'},instruments:[{ref:'synthetic-instrument',label:'合成 測深儀'}],vehicles:[{ref:'synthetic-vehicle',label:'合成 工務車'}],deadline:'2026-10-23',est_person_hours:8,revision:2,command:null,source:'v4_task',needs_me:['approve_seat:manager_review'],allowed_actions:['reassign','edit_detail','approve','return'],parent_task_ref:'synthetic-obligation',department:'外業組',scope_version:'1',rule_version:'R1',evidence_version:'E1',read_back_at:'2026-10-18T02:00:00Z',node_position:'外業（4 / 9）',preview_id:''};
export function syntheticWork(state,from){
 const rows=[base,{...base,task_id:'synthetic-task-2',title:'合成 待指派控制工作',planning_status:'unassigned',status:'待處理',crew:[],needs_me:['confirm_assignment'],allowed_actions:['assign','edit_detail'],node_position:'控制（5 / 9）'},{...base,task_id:'synthetic-task-3',title:'合成 回應不明待對帳',planning_status:'publishing',command:{command_id:'synthetic-command-unknown',state:'outcome_unknown',revision:2,next_action:'reconcile'},needs_me:['reconcile_command'],allowed_actions:['reconcile']},{...base,task_id:'synthetic-task-4',title:'合成 成果退回待核實',planning_status:'draft',acceptance_status:'已退回',acceptance_summary:'請補充量測紀錄',needs_me:['review_returned','verify_unknown:synthetic-leader'],allowed_actions:['edit_detail','cancel_draft']}].map(r=>({...structuredClone(r),interval:{...r.interval,start:from+'T08:00:00+08:00',end:from+'T12:00:00+08:00'}}));
 const counts=key=>rows.reduce((a,r)=>({...a,[r[key]]:(a[r[key]]??0)+1}),{});
 return {source:{fetched_at:state==='stale'?'2026-10-18T01:00:00Z':new Date().toISOString(),quality:{states:[state==='stale'?'stale':state==='read_failed'?'read_failed':'complete']}},progress:{status:counts('status'),planning_status:counts('planning_status')},needs_me:rows.filter(r=>r.needs_me.length),rows};
}
export function createPublishMock(){
 const drafts=new Map(),previews=new Map(),hashes=new Map(),commands=new Map();
 let serial=0;
 const stamp=()=>new Date().toISOString();
 const command=(id,state)=>({command_id:id,state,revision:3,task_record_id:state==='committed'?'synthetic-task-1':'',created_at:stamp(),updated_at:stamp(),next_action:['outcome_unknown','reconciliation_required'].includes(state)?'reconcile':'none',receipt:state==='committed'?'合成讀回一致':null});
 commands.set('synthetic-command-unknown',command('synthetic-command-unknown','outcome_unknown'));
 return async({req,url,send,state,user,delay})=>{
  if(!url.pathname.startsWith('/api/v2/dispatch/')&&!url.pathname.startsWith('/api/v2/commands/'))return false;
  if(url.pathname.endsWith('/board'))return false;
  if(delay)await new Promise(r=>setTimeout(r,delay));
  if(state==='flag_off'){send({detail:'未開放'},404);return true}
  if(['forbidden','http_forbidden'].includes(state)){send({detail:'合成權限不足'},403);return true}
  if(state==='http_failed'){send({detail:'合成讀取失敗'},500);return true}
  let body={};if(['POST','PUT'].includes(req.method)){let raw='';for await(const chunk of req)raw+=chunk;body=JSON.parse(raw||'{}')}
  const path=url.pathname;
  if(path==='/api/v2/dispatch/work'){
   const work=syntheticWork(state,url.searchParams.get('from'));
   const row=work.rows[0],id='synthetic-work-preview';
   if(!previews.has(id))previews.set(id,{preview_id:id,preview_hash:'synthetic-existing-work-hash',expires_at:new Date(Date.now()+900000).toISOString(),proposal:{task_id:row.task_id,title:row.title,content:row.content,project_ref:row.project_id,case_ref:row.case.ref,phase:row.phase,kind:row.kind,package_id:row.package_id,parent_task_ref:row.parent_task_ref,primary_owner:row.owner.person_ref,crew:row.crew.map(p=>p.person_ref),start:row.interval.start,end:row.interval.end,est_person_hours:row.est_person_hours,instruments:row.instruments.map(r=>r.ref),vehicles:row.vehicles.map(r=>r.ref),department:row.department,deadline:row.deadline},source_vector:{schedule:{fetched_at:stamp()},tasks:{fetched_at:stamp()},schema_version:1},feasibility:[{kind:'person',ref:user.id,label:user.name,state:'feasible',reasons:[]}],required_seats:[{seat:'group_leader_confirmed',holder:people[1],status:'accepted',actor:people[1].person_ref,reason:''},{seat:'manager_review',holder:people[0],status:'pending',actor:'',reason:''},{seat:'pm_final',holder:people[2],status:'pending',actor:'',reason:''}],can_commit:false,conflicts:[],warnings:[],blockers:['approvals_required']});
   work.rows[0].preview_id=id;send(work);return true;
  }
  if(path==='/api/v2/dispatch/options'){send({people:people.map(p=>({...p,active:true,has_lark_account:true})),instruments:[{ref:'synthetic-instrument',label:'合成 測深儀',feasibility:'feasible'}],vehicles:[{ref:'synthetic-vehicle',label:'合成 工務車',feasibility:'feasible'}],cases:[base.case],departments:['外業組'],seats:[],joins:{people:'ok',accounts:'ok',instruments:'ok',vehicles:'ok',cases:'ok'}});return true}
  if(path.startsWith('/api/v2/dispatch/tasks/')){send({row:base,proposal:{...base,task_id:path.split('/').at(-1),project_ref:base.project_id,case_ref:base.case.ref,primary_owner:base.owner.person_ref,crew:base.crew.map(p=>p.person_ref),start:base.interval.start,end:base.interval.end,instruments:base.instruments.map(r=>r.ref),vehicles:base.vehicles.map(r=>r.ref)},system:{revision:base.revision,scope_version:base.scope_version},unmapped_people:[]});return true}
  if(path==='/api/v2/dispatch/drafts'){send({drafts:[...drafts.values()]});return true}
  if(path.startsWith('/api/v2/dispatch/drafts/')){
   const id=path.split('/').at(-1);
   if(req.method==='PUT'){const old=drafts.get(id);if(old&&body.version!==old.version){send({detail:'草稿已更新',code:'version_conflict'},409);return true}drafts.set(id,{id,proposal:body.proposal,version:(old?.version??0)+1,updated_at:Date.now()/1000});send(drafts.get(id))}
   else if(req.method==='DELETE'){drafts.delete(id);send({deleted:id})}else send(drafts.get(id)??{detail:'草稿不存在'},drafts.has(id)?200:404);return true;
  }
  if(path==='/api/v2/dispatch/previews'){
   const hash=createHash('sha256').update(JSON.stringify(body)).digest('hex');
   if(hashes.has(hash)){send(previews.get(hashes.get(hash)));return true}
   const id=`synthetic-preview-${++serial}`,blocked=state==='blocked_unknown';
   const checks=[...body.crew.map(ref=>({kind:'person',ref,label:people.find(p=>p.person_ref===ref)?.name||'合成人員'})),...body.instruments.map(ref=>({kind:'instrument',ref,label:'合成 測深儀'})),...body.vehicles.map(ref=>({kind:'vehicle',ref,label:'合成 工務車'}))];
   const hours=(Date.parse(body.end)-Date.parse(body.start))/3600000;
   const preview={hours,booked_person_hours:hours*new Set(body.crew).size,preview_id:id,preview_hash:hash,expires_at:new Date(Date.now()+900000).toISOString(),proposal:body,source_vector:{schedule:{fetched_at:stamp()},tasks:{fetched_at:stamp()},schema_version:1},feasibility:checks.map(c=>({...c,state:blocked?'unknown':'feasible',reasons:blocked?['no_capability_source','no_leave_source']:[]})),conflicts:[],warnings:[],required_seats:[{seat:'group_leader_confirmed',holder:people[1],status:'accepted',actor:people[1].person_ref,reason:''},{seat:'manager_review',holder:people[2],status:'accepted',actor:people[2].person_ref,reason:''},{seat:'pm_final',holder:people[0],status:'pending',actor:'',reason:''}],can_commit:false,blockers:blocked?['unknown_feasibility']:['approvals_required']};
   previews.set(id,preview);hashes.set(hash,id);send(preview);return true;
  }
  if(path.includes('/previews/')){
   const id=path.split('/')[5],preview=previews.get(id);if(!preview){send({detail:'預覽不存在'},404);return true}
   if(path.endsWith('/decisions')){
    const seat=preview.required_seats.find(s=>s.seat===body.seat);
    if(seat?.holder.person_ref!==user.id||preview.required_seats.some(s=>s.actor===user.id&&s.seat!==body.seat)){send({detail:'不能代簽或兼任席位'},403);return true}
    Object.assign(seat,{status:body.decision,actor:user.id,reason:body.reason||''});
    preview.can_commit=state!=='blocked_unknown'&&preview.required_seats.every(s=>s.status==='accepted');preview.blockers=preview.can_commit?[]:[body.decision==='returned'?'returned':preview.feasibility.some(f=>f.state==='unknown')?'unknown_feasibility':'approvals_required'];
   }send(preview);return true;
  }
  if(path==='/api/v2/dispatch/commits'){
   if(commands.has(body.command_id)){send({command:commands.get(body.command_id)},commands.get(body.command_id).state==='committed'?200:202);return true}
   if(state==='conflict_409'){send({detail:'合成 港外量測 · 08:00 ～ 12:00 已占用同一人員',code:'conflict'},409);return true}
   const preview=previews.get(body.preview_id);if(!preview?.can_commit){send({detail:'預覽尚有阻擋',blockers:['approvals_required']},422);return true}
   const c=command(body.command_id,state==='pending_202'?'pending':state==='outcome_unknown'?'outcome_unknown':state==='reconciliation_required'?'reconciliation_required':state==='failed'?'failed':'committed');commands.set(body.command_id,c);send({command:c},c.state==='committed'?200:202);return true;
  }
  if(path.startsWith('/api/v2/commands/')){
   const id=path.split('/')[4];if(!commands.has(id)){send({detail:'命令尚未找到，請用原編號重試'},404);return true}
   if(path.endsWith('/reconcile')){if(user.role!=='manager'){send({detail:'僅經理可對帳'},403);return true}commands.set(id,command(id,'committed'))}
   send({command:commands.get(id),next_action:commands.get(id).next_action});return true;
  }
  return false;
 };
}
