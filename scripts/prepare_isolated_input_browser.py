"""Create private browser-step code only; this generator makes no API requests."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
private=ROOT/'.runtime/lark-input-cli'
subject=json.loads((ROOT/'.runtime/company-admin-approved-subject.json').read_text(encoding='utf-8'))
test=json.loads((private/'test-input-config.json').read_text(encoding='utf-8'))
formal=json.loads((private/'formal-input-config.json').read_text(encoding='utf-8'))
drive=json.loads((private/'test-drive-checkpoint.json').read_text(encoding='utf-8'))
config={'origin':'https://yongxiang-projects-20260925.zeabur.app','user_id':subject['open_id'],
    'test_base':test['workspace_settings']['test_base'],'test_table':test['workspace_settings']['test_input_table'],
    'formal_base':formal['workspace_settings']['input_base'],'formal_table':formal['workspace_settings']['input_table'],
    'test_drive_root':drive['folder_token']}
code=r'''async page=>{
 const EXECUTE=false; // root sets true only after env deployment and normal OAuth verified.
 const expected=__CONFIG__;
 if(!EXECUTE)return {preparedOnly:true,requires:'normal authorized company-admin session; dedicated browser session',willWrite:'test workspace settings + optional isolated pilot copy + one test Input registration',noFormalBaseWrite:true};
 if(new URL(page.url()).origin!==expected.origin)throw Error('Wrong browser origin');
 return await page.evaluate(async cfg=>{
  const request=async(path,body)=>{const response=await fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(`HTTP ${response.status} at ${path}: ${typeof data.detail==='string'?data.detail:'request rejected'}`);return data};
  const session=await request('/api/session');
  if(session.mode!=='lark'||session.access_mode!=='normal'||session.user?.role!=='manager'||session.user.id!==cfg.user_id)throw Error('Requires exact authorized normal company-admin session');
  const key=`yx:isolated-input-acceptance:20260929:${cfg.user_id}:${cfg.test_base}`;
  let checkpoint=JSON.parse(localStorage.getItem(key)||'null');
  const save=()=>localStorage.setItem(key,JSON.stringify(checkpoint));
  let w=await request('/api/workspace');
  let sourceProject=w.environment==='production'?w.projects.find(p=>p.source_kind==='lark'&&!p.archived_at&&!p.migrated_to&&!p.source_missing&&!['completed','paused'].includes(p.execution_status)&&!['已結案','中止'].includes(p.source_status)):null;
  if(w.environment!=='test'){await request('/api/workspace/switch',{environment:'test'});w=await request('/api/workspace')}
  if(w.environment!=='test'||!String(w.workspace_id).startsWith('test-lark-'))throw Error('Test namespace required');
  if(cfg.test_base===cfg.formal_base||cfg.test_table===cfg.formal_table)throw Error('Cross-target configuration');
  if(checkpoint){const prior=(w.input_revisions||[]).find(r=>r.request_id===checkpoint.request_id);if(prior){checkpoint.revision_id=prior.id;save()}}
  const activeJobs=(w.jobs||[]).filter(j=>['queued','retry','running','outcome_unknown'].includes(j.status)&&!(checkpoint?.revision_id&&j.key===`input:${checkpoint.revision_id}`));
  if(activeJobs.length)throw Error('Existing test jobs require review before enabling external connection');
  const desired={test_base:cfg.test_base,test_input_table:cfg.test_table,test_drive_root:cfg.test_drive_root,test_connection_mode:'isolated_live',external_enabled:true};
  if(Object.entries(desired).some(([k,v])=>w.settings[k]!==v)){
   w=await request('/api/actions',{action:'admin_settings',version:w.version,request_id:crypto.randomUUID(),payload:desired});
  }
  w=await request('/api/workspace');
  if(Object.entries(desired).some(([k,v])=>w.settings[k]!==v))throw Error('Settings readback mismatch');
  let project=checkpoint?w.projects.find(p=>p.id===checkpoint.project_id):w.projects.find(p=>p.pilot===true&&!p.archived_at&&!p.migrated_to&&!p.source_missing);
  if(!project){
   if(checkpoint)throw Error('Pinned test project missing; do not create another');
   if(!sourceProject)throw Error('Choose one existing formal source case for normal pilot-copy before retrying; no automatic new company case');
   await request('/api/pilot/copy',{project_id:sourceProject.id});w=await request('/api/workspace');project=w.projects.find(p=>p.pilot_source_id===sourceProject.id);
  }
  if(!project||!project.pilot)throw Error('Dedicated pilot case required');
  const node=checkpoint?project.nodes.find(n=>n.id===checkpoint.node_id):project.nodes.find(n=>n.key==='pm'&&!['completed','approved_skipped','archived','superseded'].includes(n.status));
  if(!node)throw Error('An active test PM node is required');
  if(!checkpoint){checkpoint={request_id:crypto.randomUUID(),project_id:project.id,node_id:node.id,label:'[隔離驗收] 工作台 Input 串接',value:`僅供隔離測試 Base 的連線驗收；不屬正式交付。建立時間 ${new Date().toISOString()}`,phase:'prepared'};save()}
  let revision=(w.input_revisions||[]).find(r=>r.request_id===checkpoint.request_id||r.id===checkpoint.revision_id);
  if(!revision){
   if(checkpoint.phase==='submit_outcome_unknown')throw Error('Prior API outcome unknown; inspect test workspace with same request_id before any retry');
   checkpoint.phase='submit_outcome_unknown';save();
   w=await request(`/api/projects/${encodeURIComponent(project.id)}/nodes/${encodeURIComponent(node.id)}/inputs`,{version:w.version,request_id:checkpoint.request_id,key:'work_input',label:checkpoint.label,value:checkpoint.value});
   revision=(w.input_revisions||[]).find(r=>r.request_id===checkpoint.request_id);
   if(!revision)throw Error('Queued registration missing from readback; do not resend');
   checkpoint.revision_id=revision.id;checkpoint.phase='queued';save();
  }
  checkpoint.revision_id=revision.id;save();
  if(['queued','running'].includes(revision.status)&&!checkpoint.worker_attempted){checkpoint.worker_attempted=true;save();await request('/api/admin/worker/run',{})}
  for(let i=0;i<10;i++){w=await request('/api/workspace');revision=(w.input_revisions||[]).find(r=>r.id===checkpoint.revision_id);if(!revision||!['queued','running'].includes(revision.status))break;await new Promise(resolve=>setTimeout(resolve,1000))}
  const result={environment:w.environment,settingsReadback:true,project_id:project.id,node_id:node.id,revision_id:revision?.id,status:revision?.status,receipt:revision?.receipt||null,request_id:checkpoint.request_id,formalBaseWritten:false};
  if(revision?.status==='succeeded'){
   const receipt=revision.receipt;if(!receipt?.verified||receipt.simulated||receipt.remote_mode!=='isolated_live'||receipt.base_token!==cfg.test_base)throw Error('Receipt is not verified isolated Input');
   checkpoint.phase='verified';save();result.verified=true;
  }else{checkpoint.phase=revision?.status||'readback_missing';save();result.verified=false;result.next='Do not resend. Inspect job; outcome_unknown may only use POST /api/input-revisions/{id}/reconcile with current version.'}
  return result;
 },expected);
}
'''
target=ROOT/'.runtime/isolated-input-acceptance-browser-step.js'
target.write_text(code.replace('__CONFIG__',json.dumps(config,ensure_ascii=False)),encoding='utf-8')
print(json.dumps({'prepared':True,'executed':False,'file':str(target.relative_to(ROOT)),'default_execute':False}))
