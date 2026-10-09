import {useEffect,useState} from 'react';
import type {Project,Session,Workspace} from './types';
import {Button,Row} from './design';
import './ProjectPanels.css';
export function executionAllowed(p:Project,w:Workspace){return ['demo','test'].includes(w.environment||'')||p.execution_allowed===true}
export function executionReason(p:Project){return p.execution_readonly_reason|| (p.execution_system==='meegle'?'本案留在 Meegle 執行至完成，工作台僅供參考。':'本案執行歸屬尚未核定，暫不在工作台派工或交付。')}
type Props={p:Project;w:Workspace;s:Session;busy:boolean;run:(action:string,payload:Record<string,unknown>,scope:{project_id:string})=>Promise<Workspace|undefined>};
export function ProjectExecutionNotice(props:Props){return <ExecutionNoticeForm key={`${props.s.user?.id}:${props.w.workspace_id}:${props.p.id}`} {...props}/>}
function ExecutionNoticeForm({p,w,s,run,busy}:Props){
 const signature=JSON.stringify([p.execution_system||'pending',p.execution_assignment||null]);
 const[value,setValue]=useState(p.execution_system||'pending');const[reason,setReason]=useState('');const[baseline,setBaseline]=useState(signature);
 const dirty=!!reason||value!==JSON.parse(baseline)[0];const conflict=baseline!==signature;
 const reset=()=>{setValue(p.execution_system||'pending');setReason('');setBaseline(signature)};
 useEffect(()=>{if(conflict&&!dirty)reset()},[signature,conflict,dirty]);
 if(['demo','test'].includes(w.environment||''))return null;
 return <section className="ds-section pe-notice" aria-label="案件執行歸屬"><div className="ds-group glass--flat"><Row label={<strong>{p.execution_system_label||({workbench:'本工作台執行',meegle:'Meegle 執行',pending:'歸屬待核定'} as Record<string,string>)[p.execution_system||'pending']}</strong>} detail={executionAllowed(p,w)?'本案由工作台執行；來源資料持續同步。':executionReason(p)}/>{s.user?.role==='manager'&&<details className="pe-assign"><summary>核定案件執行歸屬</summary><form onSubmit={e=>{e.preventDefault();if(conflict||busy)return;void run('case_execution_assign',{execution_system:value,reason},{project_id:p.id}).then(result=>{const saved=result?.projects.find(project=>project.id===p.id);if(saved){setValue(saved.execution_system||'pending');setBaseline(JSON.stringify([saved.execution_system||'pending',saved.execution_assignment||null]));setReason('')}})}}>{conflict&&<p role="alert">案件歸屬已由其他更新變更，舊草稿不能套用。<Button onClick={reset}>捨棄草稿並載入最新歸屬</Button></p>}<label className="form-field">執行系統<select disabled={conflict||busy} value={value} onChange={e=>setValue(e.target.value)}><option value="pending">待核定</option><option value="meegle">Meegle 執行至完成</option><option value="workbench">本工作台執行</option></select></label><label className="form-field">核定依據<textarea required maxLength={1000} disabled={conflict||busy} value={reason} onChange={e=>setReason(e.target.value)}/></label><Button variant="primary" type="submit" disabled={busy||conflict||!reason.trim()}>保存歸屬核定</Button></form></details>}</div></section>;
}
