import {useEffect,useRef,useSyncExternalStore,type ReactNode} from 'react';
import {DataState} from './design/DataState';
import {subscribeConnectivity,isOffline} from './api';
import './system-states.css';

export function FocusAlert({children}:{children:ReactNode}){
 const ref=useRef<HTMLDivElement>(null);
 useEffect(()=>{ref.current?.focus()},[]);
 return <div ref={ref} tabIndex={-1} role="alert" className="auth-error-card">{children}</div>;
}
export function OfflineNotice({asOf}:{asOf?:string}){
 const offline=useSyncExternalStore(subscribeConnectivity,isOffline,()=>false);
 return offline?<aside className="system-offline" role="status"><strong>目前離線</strong><p>{asOf?'目前保留已讀取的資料。':'目前沒有網路連線。'}資料時間：{asOf||'來源未提供'}。離線時無法儲存或送出，操作不會排入佇列。恢復連線後，請按「重新讀取」。</p></aside>:null;
}
export function RouteState({kind='unknown',onHome}:{kind?:'denied'|'missing'|'unknown';onHome?:()=>void}){
 const heading=useRef<HTMLHeadingElement>(null);
 const title=kind==='denied'?'403 · 無權查看':kind==='missing'?'404 · 找不到頁面':'無法辨識這個頁面';
 useEffect(()=>{const previous=document.title;document.title=title+'｜詠翔工作台';heading.current?.focus();return()=>{document.title=previous}},[title]);
 return <section className="system-route"><h1 ref={heading} tabIndex={-1}>{title}</h1><DataState kind={kind==='denied'?'Denied':'Error'} title={kind==='denied'?'存取遭拒':'請確認連結'} body={kind==='denied'?'AI 用量儀表板僅限主管查看。請使用主管帳號登入。':kind==='missing'?'這個頁面可能已移除，或連結不完整。':'請確認連結，或返回工作總覽繼續操作。'} actions={onHome?<button className="button primary" onClick={onHome}>返回工作總覽</button>:<a className="ds-button" href="/#view=dashboard">返回工作總覽</a>}/></section>;
}
