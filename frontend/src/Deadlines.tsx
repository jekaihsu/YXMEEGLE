import {useState,useEffect} from 'react';
import {StatusBadge,Section} from './design';
import './deadlines.css';
import {SopFollowups} from './SopApplicability';
import {ActionForm,Field,who,type Context} from './Operations';
import type {Project} from './types';
type Row=Record<string,any>;
const kinds:Record<string,string>={inquiry_received:'接獲詢價',quote_issued:'報價發出',contract_signed:'合約回簽',dispatch_scheduled:'預定派工',field_stage_completed:'外業階段完成',confirmation_received:'組別收到確認單',work_completed:'組別工作完成',billing_eligible:'達成計價條件',delivery_submitted:'成果繳交'};
const reasons:Record<string,string>={contract_fixed:'契約固定日期',work_started:'工作已開始或完成',existing_manual_date:'已有人工排定日期'};
export function Deadlines({c,p}:{c:Context;p:Project}){
 const [selected,setSelected]=useState('');
 useEffect(()=>setSelected(''),[p.id]);
 const events=(p.sop_events||[]) as Row[];
 const prior=events.find(e=>e.id===selected);
 const conflicts=(p.sop_deadline_conflicts||[]) as Row[];
 const lead=c.s.user?.can_business_override||[p.pm_id,p.admin_id,p.supervisor_id].includes(c.s.user?.id);
 const supervisor=c.s.user?.can_business_override||c.s.user?.id===p.supervisor_id;
 const today=c.w.as_of.slice(0,10);
 const overdue=(t:Row)=>!!t.due_date&&t.due_date<today&&!['completed','superseded'].includes(t.status);
 const tasks=p.nodes.flatMap(n=>n.tasks.filter(t=>t.sop_due_provenance).map(t=>({...t,node:n.name}))) as Row[];
 tasks.sort((a,b)=>Number(overdue(b))-Number(overdue(a))||String(a.due_date||'9999').localeCompare(String(b.due_date||'9999')));
 return <section className="deadline-screen"><h3>SOP 事件與期限</h3><p>以有佐證的業務日期，依公司工作日計算期限。既有人工日期、契約日期與已開工作業保留核對紀錄。</p>
 <Section title="期限依據">{!tasks.length?<p>尚無由 SOP 事件計算的有效期限。</p>:<div className="table-scroll"><table className="data-table"><thead><tr><th>工作</th><th>有效期限</th><th>依據</th></tr></thead><tbody>{tasks.map(t=><tr key={t.id} data-overdue={overdue(t)}><td>{t.title}<small>{t.node} · {who(c,t.owner_id)}</small></td><td>{t.due_date}{overdue(t)&&<StatusBadge kind="attention" state="overdue">逾期</StatusBadge>}</td><td>{kinds[events.find(e=>e.id===t.sop_due_provenance.event_id)?.event_type]||'業務事件'}<small>事件 v{t.sop_due_provenance.event_version} · {t.sop_due_provenance.anchor_date} 起 {t.sop_due_provenance.workday_offset} 工作日</small></td></tr>)}</tbody></table></div>}</Section>
 {lead&&<Section><label>登錄方式<select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">新增業務事件</option>{events.filter(e=>!e.superseded_by).map(e=><option key={e.id} value={e.id}>更正：{kinds[e.event_type]} · {e.scope_key} · v{e.version}</option>)}</select></label>
 <ActionForm key={`${p.id}:${selected}`} draftId={`sop-event:${p.id}:${selected||'new'}:v${prior?.version??0}`} title={prior?'更正事件並保留原版本':'登錄有佐證的業務事件'} busy={c.busy} onSubmit={d=>c.run('sop_event_record',{...d,replaces_id:prior?.id},{project_id:p.id})}>
 <Field title="事件" name="event_type"><select name="event_type" defaultValue={prior?.event_type}>{Object.entries(kinds).map(([key,title])=><option key={key} value={key}>{title}</option>)}</select></Field>
 <Field title="範圍識別（報價版本或工作批次）" name="scope_key" value={prior?.scope_key}/><Field title="事件日期" name="date" type="date" value={prior?.date}/>
 <Field title="收到確認單／工作完成的組別" name="node_key"><select name="node_key" defaultValue={prior?.node_key||''}><option value="">本事件不分組別</option>{p.nodes.filter(n=>['field','control','mapping','report'].includes(n.key)).map(n=><option key={n.id} value={n.key}>{n.name}</option>)}</select></Field>
 <Field title="佐證來源連結" name="evidence_url" type="url" value={prior?.evidence?.evidence_url} required={false}/>
 <Field title="或引用已核實文件" name="file_id"><select name="file_id" defaultValue={prior?.evidence?.file_id||''}><option value="">不引用</option>{p.files.filter(f=>!f.withdrawn).map(f=><option key={f.id} value={f.id}>{f.name}</option>)}</select></Field>
 <Field title="備註" name="note" value={prior?.note} required={false}/>{prior&&<Field title="更正原因" name="reason"/>}
 <p>佐證來源或文件至少填一項；兩個組別事件必須指定組別。尚無負責人的工作，請至任務指派。</p>
 </ActionForm></Section>}
 {!!conflicts.length&&<Section title="期限核對">{conflicts.map(item=><section className="deadline-conflict" key={item.id}><p><strong>{p.nodes.flatMap(n=>n.tasks).find(t=>t.id===item.task_id)?.title||'待核對任務'}</strong> · {item.status==='pending'?'待主管核對':item.status==='resolved'?'已核對':'已有新版本'}</p><p>目前 {item.current_due||'未排定'} → 計算 {item.proposed_due} · {reasons[item.reason]||item.reason}</p>{item.status==='pending'&&supervisor&&<ActionForm title="記錄期限核對結果" draftId={`deadline-resolve:${p.id}:${item.id}`} busy={c.busy} onSubmit={d=>c.run('sop_deadline_resolve',{...d,id:item.id},{project_id:p.id})}><Field title="處理方式" name="resolution"><select name="resolution"><option value="keep_existing">保留現有日期</option>{item.reason==='existing_manual_date'&&<option value="apply_proposed">採用計算日期</option>}</select></Field><Field title="核對原因" name="reason"/></ActionForm>}{item.reason==='work_started'&&<p>已開工作業如需改期，請至「變更與展延」申請。</p>}</section>)}</Section>}
 <Section title="已登錄事件">{!events.length?<p>尚無具佐證的事件；未以同步時間代替業務日期。</p>:<div className="table-scroll"><table className="data-table"><thead><tr><th>事件／範圍</th><th>日期</th><th>版本與紀錄者</th></tr></thead><tbody>{events.map(e=><tr key={e.id}><td>{kinds[e.event_type]}<small>{e.scope_key}{e.node_key&&` · ${p.nodes.find(n=>n.key===e.node_key)?.name||e.node_key}`}</small>{e.evidence?.evidence_url&&<a className="text-button" href={e.evidence.evidence_url} target="_blank" rel="noreferrer">查看佐證</a>}</td><td>{e.date}</td><td>v{e.version} · {e.superseded_by?'舊版留存':'目前版本'}<small>{who(c,e.recorded_by)}</small></td></tr>)}</tbody></table></div>}
</Section>
 <SopFollowups key={p.id} c={c} p={p}/>
 </section>;
}
