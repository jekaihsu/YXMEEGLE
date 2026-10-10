import {Section,Button} from './design';
import './owned-screens.css';
import {useState} from 'react';
import {api} from './api';
import {RuntimeHealthPanel} from './RuntimeHealthPanel';
import type {Session} from './types';
export function RecoveryPage({s,refresh,logout}:{s:Session;refresh:()=>Promise<void>;logout:()=>Promise<void>}){
 const[busy,setBusy]=useState(false);const[error,setError]=useState('');
 const sync=async()=>{setBusy(true);setError('');try{await api('/api/people/sync',{method:'POST'});await refresh()}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 return <main className="owned-view owned-state"><Section><h1>公司名冊需要重新核實</h1><p>目前僅開放管理員復原操作；案件資料與業務操作暫不載入。請同步公司名冊，核實在職資格後再進入工作台。</p>{error&&<p role="alert" className="owned-alert">{error}</p>}<div className="inline-actions"><Button variant="primary" disabled={busy} onClick={()=>void sync()}>{busy?'核實中…':'重新同步公司名冊'}</Button><Button disabled={busy} onClick={()=>void refresh()}>重新檢查資格</Button><Button disabled={busy} onClick={()=>void logout()}>登出</Button></div></Section><RuntimeHealthPanel s={s} w={{environment:'production',workspace_id:s.workspace_id}}/></main>;
}

