import {useState} from 'react';
import {api} from './api';
import type {Workspace} from './types';

const names:Record<string,string>={node_skip:'跳過節點',financial:'財務交付',change:'設計變更',extension:'期限展延'};

export function NativeDefinitionPanel({w,refresh}:{w:Workspace;refresh:()=>Promise<void>}){
 const[busy,setBusy]=useState(false);const[message,setMessage]=useState('');const[error,setError]=useState('');
 const verify=async()=>{setBusy(true);setMessage('');setError('');try{
  const result=await api<Workspace>('/api/native-approvals/definitions/verify',{method:'POST',body:JSON.stringify({version:w.version})});
  await refresh();setMessage(result.approval_connection?.definition_mapping_verified?'四種審批單的欄位與核准流程已核對。':'核對已完成，仍有設定需要處理。');
 }catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 return <section aria-label="Lark 審批設定核對" className="ops-input"><div className="section-heading"><div><h2>Lark 審批設定</h2><p>核對目前的表單欄位與共同核准流程。送審及核准回傳須另行驗收。</p></div><button className="button" disabled={busy} onClick={()=>void verify()}>{busy?'核對中…':'核對 Lark 審批設定'}</button></div>
  {error&&<p role="alert" className="error-banner">{error}</p>}{message&&<p role="status">{message}</p>}
  <div className="delivery-checks">{Object.entries(names).map(([kind,name])=>{const status=w.approval_connection?.native_submit?.by_type?.[kind];return <article key={kind}><header><strong>{name}</strong><span>{status?.definition_mapping_verified?'流程已核對':'待核對'}</span></header>{status?.blockers?.map((b:{code:string;label:string})=><p key={b.code}>{b.label}</p>)}</article>})}</div>
 </section>;
}
