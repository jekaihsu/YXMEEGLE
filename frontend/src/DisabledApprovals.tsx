import {DataState} from './design/DataState';
import './confirmation-calm.css';
export function DisabledApprovals({onHome}:{onHome:()=>void}){
 return <main className="p2-detail-root approvals-disabled">
  <header><h1>變更與展延尚未開放</h1><p>歷史紀錄保留，只供查閱。</p></header>
  <DataState kind="Partial" title="目前暫停申請與審批操作" body="此頁無法新增、核准或套用變更與展延。歷史資料仍保留；待辦狀態尚未取得。"
   actions={<button className="button" onClick={onHome}>回今日工作台</button>}/>
  <details className="p2-card"><summary>歷史紀錄版面示意（非實際申請）</summary>
   <p>實際歷史紀錄請至有權限的案件內查看。此頁尚未取得歷史清單。</p>
   <div className="p2-table-scroll"><table className="p2-table"><caption>示意資料 · 唯讀，非實際申請</caption><thead><tr><th>名稱</th><th>類型</th><th>狀態</th><th>日期</th></tr></thead><tbody><tr><td>展延申請（示意）</td><td>展延</td><td>歷史紀錄</td><td>待核對</td></tr></tbody></table></div>
  </details>
 </main>;
}
