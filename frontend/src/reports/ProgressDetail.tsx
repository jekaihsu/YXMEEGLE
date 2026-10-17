import {Sheet} from '../design';
import {money,number,rate,safeLink,statusLabel} from './reportsView';
import {MetaNotice,ReportState} from './shared';
import {useReport} from './useReport';
import {caseStatus} from './progressView';
import type {ProgressDetail as Detail} from './types';
export function CaseStatus({status}:{status:string}){const s=caseStatus(status);return <span className={`reports-case-status status-${s.tone}`}>{s.label}</span>}
export default function ProgressDetail({caseKey,dept,week,onClose}:{caseKey:string;dept:string;week:string;onClose:()=>void}){
 const result=useReport<Detail>('progress/case',{key:caseKey,dept,week});const d=result.data;
 return <div className="reports-case-drawer"><Sheet title="案件詳情" onClose={onClose}>{!d?<>{result.error==='case_not_found'?<div role="alert"><h3>找不到這個案件</h3><p>案件可能已移除，請關閉面板並重新整理資料。</p><button onClick={result.retry}>重試</button></div>:<ReportState loading={result.loading} error={result.error} warming={result.warming} retry={result.retry}/>}</>:<>
  <p className="reports-caption">{d.case.code}</p><h3>{d.case.name||'案件名稱未填'}</h3><CaseStatus status={d.case.status}/>
  <dl className="reports-case-facts">{[
   ['業主',d.case.client||'未填'],['PM',d.case.pm||'未填'],['預期合約',money(d.case.contract.expected)],['實際合約',money(d.case.contract.actual)],
   ['累計已請款',money(d.case.billing.billed)],['應收未收',money(d.case.billing.receivable)],['計價進度',rate(d.case.billing.progress)],['營業額進度',rate(d.case.revenue_progress)],['成本進度',rate(d.case.cost_progress)],
   ['預期總點數',`${number(d.case.expected_points)} 點`],['外業累計完成',`${number(d.case.cumulative_points_by_dept.field)} 點`],['內業累計完成',`${number(d.case.cumulative_points_by_dept.office)} 點`]
  ].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
  <h3>{d.week.week} 當週{d.week.dept==='office'?'內業':'外業'}</h3><p>對應出工 {d.week.matched} 天 · 未預排出工 {d.week.unplanned} 天</p>
  <h4>工作預排</h4>{d.week.plan_rows.length?<div className="reports-detail-table"><table><thead><tr>{['日期','組別','人員','工項','點數'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{d.week.plan_rows.map((r,i)=><tr key={i}><td>{r.date}</td><td>{r.group}</td><td>{r.people||'未填'}</td><td>{r.items||'未填'}</td><td>{number(r.points)}</td></tr>)}</tbody></table></div>:<p className="reports-empty">本週沒有工作預排。</p>}
  <h4>實際工作單</h4>{d.week.work_rows.length?<div className="reports-detail-table"><table><thead><tr>{['日期','組別','人員','工項','點數','檢核與提醒','備註'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{d.week.work_rows.map((r,i)=><tr key={i}><td>{r.date}</td><td>{r.group}</td><td>{r.person||'未填'}</td><td>{r.item||'未填'}</td><td>{number(r.points)}</td><td>{statusLabel[r.checks.status]}{r.checks.control_checked!=null&&` · 控制組${r.checks.control_checked?'已':'未'}檢核`}{r.flags.length>0&&` · ${r.flags.join('、')}`}</td><td>{r.note||'無'}</td></tr>)}</tbody></table></div>:<p className="reports-empty">本週沒有出工紀錄。</p>}
  {d.week.truncated&&<p role="note">資料較多，預排與工作單各顯示前 200 筆。</p>}
  {!d.week.plan_rows.length&&<p>未排計畫，因此無法計算預排達成率；出工仍列於實際工作單。</p>}
  {d.week.plan_rows.some(r=>!r.people||!r.items)&&<p className="reports-caption">部分預排未提供人員或工項，顯示「未填」；不影響日期與點數統計。</p>}
  <p className="reports-caption">空白數字表示來源未填，不代表零。預期點數是全案目標，累計點數是各部門至今完成量。</p><MetaNotice meta={d.meta}/>
  {d.link&&safeLink(d.link)&&<p><a className="reports-source-secondary" href={d.link} target="_blank" rel="noreferrer">在 Lark 開啟原始紀錄</a></p>}
 </>}</Sheet></div>
}
