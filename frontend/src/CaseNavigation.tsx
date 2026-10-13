import {useEffect,useState} from 'react';
import {Row} from './design';
import {fetchCaseNavigation} from './api';
import './ProjectPanels.css';

export type Navigation={confirmations:{id:string;code?:string;source_url?:string;contracts:{id:string;item_number?:string;title?:string;unresolved:boolean;work_items:{id:string;category:string;source_url?:string}[]}[];edge_states:{contracts:string;work_items:string;daily:string;files:string}}[]};
const sourceLink=(url:string|undefined,label:string)=>/^https?:\/\//i.test(url||'')?<a href={url} target="_blank" rel="noreferrer" aria-label={label}>開啟 Lark 來源</a>:null;
export function CaseNavigation({projectId}:{projectId:string}){
 const [state,setState]=useState<{id:string;data?:Navigation;error?:string}>({id:projectId});
 useEffect(()=>{
  const controller=new AbortController();let current=true;setState({id:projectId});
  fetchCaseNavigation(projectId,controller.signal).then(data=>{if(current)setState({id:projectId,data})}).catch(error=>{if(current)setState({id:projectId,error:error.message||'讀取失敗，請稍後再試。'})});
  return ()=>{current=false;controller.abort()};
 },[projectId]);
 const data=state.id===projectId?state.data:undefined,error=state.id===projectId?state.error:undefined;
 return <section className="ds-section" aria-label="合約明細與工作項"><h2>合約明細與工作項</h2><div className="ds-group glass--flat" aria-live="polite">
  {error?<p role="alert">{error}</p>:!data?<Row label="載入合約明細與工作項…"/>:!data.confirmations.length?<Row label="尚無工程確認單（來源待核對）"/>:data.confirmations.map(caseRow=><div key={caseRow.id}>
   <Row label={<strong>{caseRow.code||'確認單案號待核對'}</strong>} value={sourceLink(caseRow.source_url,'開啟工程確認單來源')}/>
   {caseRow.edge_states.contracts!=='linked'&&<Row label="合約明細未建立關聯（來源待核對）"/>}
   {caseRow.contracts.map(contract=><div key={contract.id} className="sc-item" aria-label={`合約項次 ${contract.item_number||'待核對'}`}>
    <Row label={`項次 ${contract.item_number||'待核對'} · ${contract.title||'合約工項'} · …${contract.id.slice(-4)}`} detail={contract.unresolved?<span role="status">合約關聯待核對（來源關聯未解析）</span>:undefined}/>
    {contract.work_items.map(item=><Row key={item.id} label={`工作項 · ${item.category}`} value={sourceLink(item.source_url,`開啟${item.category}工作項來源`)}/>)}
    {!contract.work_items.length&&<Row label="工作項尚未建立關聯（來源待核對）"/>}
   </div>)}
   {caseRow.edge_states.work_items.startsWith('partial')&&<Row label="外業工作項尚未匯入"/>}
   {caseRow.edge_states.daily!=='linked'&&<Row label="尚無關聯日報"/>}
   {caseRow.edge_states.files!=='linked'&&<Row label="尚無文件（來源未建立關聯）"/>}
  </div>)}
 </div><p className="ds-footer">來源唯讀；僅顯示已建立的來源關聯。</p></section>;
}
