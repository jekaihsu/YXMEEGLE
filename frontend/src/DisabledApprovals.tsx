import './confirmation-calm.css';
export function DisabledApprovals({onHome}:{onHome:()=>void}){
 return <section className="system-state-card approvals-disabled" aria-labelledby="approvals-disabled-title">
  <header><h1 id="approvals-disabled-title">變更與展延尚未開放</h1></header>
  <p>目前保留歷史紀錄，暫停此功能操作。不能新增申請，也不會有待審項目。</p>
  <button className="button primary" onClick={onHome}>回今日工作台</button>
 </section>;
}
