import {Button,Row} from './design';
import {useEffect, useId, useRef, useState} from 'react';
import type {User} from './types';
import {useDraft} from './drafts';
import './mentions.css';

const personLabel=(person:User|undefined,users:User[])=>{if(!person)return '原標註同事';const duplicate=users.filter(u=>u.name===person.name);return person.name+(duplicate.length>1?` · ${person.department||'部門待核對'} · ${person.id.slice(-6)}`:'')};

const escapeRegExp=(value:string)=>value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');

export function MentionText({body,ids,users}:{body:string;ids?:string[];users:User[]}){
 const labels=[...new Set((ids||[]).map(id=>personLabel(users.find(u=>u.id===id),users)))];
 const tokens=labels.map(label=>`@${label}`);
 const tokenSet=new Set(tokens);
 const parts=tokens.length?body.split(new RegExp(`(${tokens.slice().sort((a,b)=>b.length-a.length).map(escapeRegExp).join('|')})`,'g')):[body];
 const inline=parts.map((part,index)=>tokenSet.has(part)?<span className="mention-inline" key={index}>{part}</span>:part);
 const missing=tokens.filter(token=>!body.includes(token));
 return <>{inline}{missing.length>0&&<>{body.trim()?' ':''}{missing.map((token,index)=><span className="mention-inline" key={`missing-${index}`}>{token}</span>)}</>}</>;
}

export function MentionComposer({users,busy,onSubmit,storageKey}:{users:User[];busy:boolean;storageKey:string;onSubmit:(body:string,mentions:string[])=>Promise<boolean>}){
 const[body,setBody]=useDraft(storageKey+':body','');const[selected,setSelected]=useDraft<string[]>(storageKey+':mentions',[]);const[open,setOpen]=useState(false);const[query,setQuery]=useState('');
 const textarea=useRef<HTMLTextAreaElement>(null);const search=useRef<HTMLInputElement>(null);const pickerId=useId();const mentionRange=useRef<{start:number;end:number}|null>(null);const cursorRange=useRef({start:body.length,end:body.length});
 useEffect(()=>{const retained=selected.filter(id=>body.includes(`@${personLabel(users.find(u=>u.id===id),users)}`));if(retained.length!==selected.length)setSelected(retained)},[body,selected,users,setSelected]);
 const candidates=users.filter(u=>u.active!==false&&u.can_mention===true&&!selected.includes(u.id)&&`${u.name} ${u.department}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
 const openPicker=()=>{setOpen(true);setQuery('');requestAnimationFrame(()=>search.current?.focus())};
 const select=(id:string)=>{const area=textarea.current;const range=mentionRange.current||cursorRange.current;const start=Math.min(range.start,body.length),end=Math.min(Math.max(range.end,start),body.length);const before=body.slice(0,start),after=body.slice(end);const token=`@${personLabel(users.find(u=>u.id===id),users)}`;const leading=before&&!/\s$/.test(before)?' ':'';const trailing=after&&/^\s/.test(after)?'':' ';const insertion=leading+token+trailing;const next=before+insertion+after;const cursor=before.length+insertion.length;setBody(next);setSelected(value=>value.includes(id)?value:[...value,id]);setOpen(false);setQuery('');mentionRange.current=null;cursorRange.current={start:cursor,end:cursor};requestAnimationFrame(()=>{if(area){area.focus();area.setSelectionRange(cursor,cursor)}})};
 return <form onSubmit={async e=>{
  e.preventDefault();if(busy||!body.trim())return;
  const form=e.currentTarget;const hadFocus=form.contains(document.activeElement);
  try{if(await onSubmit(body,selected)){setBody('');setSelected([]);setOpen(false)}}
  finally{requestAnimationFrame(()=>{
   if(form.isConnected&&hadFocus&&(document.activeElement===document.body||form.contains(document.activeElement)))textarea.current?.focus();
  })}
 }} className="mention-composer">
  <textarea ref={textarea} value={body} onChange={e=>{const text=e.target.value,cursor=e.target.selectionStart;cursorRange.current={start:cursor,end:cursor};setBody(text);setSelected(ids=>ids.filter(id=>text.includes(`@${personLabel(users.find(u=>u.id===id),users)}`)));if(text.slice(0,cursor).endsWith('@')&&!(e.nativeEvent as InputEvent).isComposing){mentionRange.current={start:cursor-1,end:cursor};openPicker()}}} onSelect={e=>{const area=e.currentTarget;cursorRange.current={start:area.selectionStart,end:area.selectionEnd}}} rows={2} placeholder="留下進度或交接事項，輸入 @ 標註同事…" aria-label="新增評論" disabled={busy}/>
  {selected.some(id=>!users.some(u=>u.id===id&&u.can_mention===true&&u.active!==false))&&<p role="alert" className="form-error">部分標註對象已停用或尚未核實 Lark 帳號；請移除後重新選擇，留言草稿仍保留。</p>}
  <div className="mention-actions"><Button variant="plain" disabled={busy} aria-expanded={open} aria-controls={pickerId} onClick={()=>{if(open)setOpen(false);else{mentionRange.current=cursorRange.current;openPicker()}}}>＠ 插入標註</Button><small>可在訊息中輸入 @ 搜尋並標註同事；測試區僅模擬通知。</small><Button type="submit" variant="primary" disabled={busy||!body.trim()||selected.some(id=>!users.some(u=>u.id===id&&u.can_mention===true&&u.active!==false))}>{busy?'儲存中…':'送出'}</Button></div>
  {open&&<section id={pickerId} data-local-escape className="mention-picker glass--flat" aria-label="選擇標註同事" onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();setOpen(false);textarea.current?.focus()}}}>
   <label>搜尋同事<input ref={search} value={query} onChange={e=>setQuery(e.target.value)} placeholder="姓名或部門" onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();if(candidates.length===1)select(candidates[0].id)}}}/></label>
   <div className="mention-options">{candidates.map(person=><Row key={person.id} onClick={()=>select(person.id)} label={<strong>{personLabel(person,users)}</strong>} detail={person.department||'部門待核對'}/>)}{!candidates.length&&<p>沒有符合的在職同事；可到人員設定核對名冊同步狀態。</p>}</div>
   <Button variant="plain" onClick={()=>{setOpen(false);textarea.current?.focus()}}>取消選人</Button>
  </section>}
 </form>;
}

export function MentionDelivery({notifications,users}:{notifications?:{recipient_id:string;status:string;error?:string;simulated?:boolean}[];users:User[]}){
 if(!notifications?.length)return null;
 const labels:Record<string,string>={queued:'通知排隊中',running:'通知處理中',succeeded:'通知已送出',simulated:'測試通知（模擬）',blocked:'通知受阻',failed:'通知失敗',outcome_unknown:'通知結果待核實'};
 return <div className="mention-delivery" aria-label="標註通知狀態">{notifications.map((item,index)=><p key={`${item.recipient_id}:${index}`}>{users.find(u=>u.id===item.recipient_id)?.name||'標註同事'} · {item.simulated?'測試通知（模擬）':item.status==='succeeded'&&item.simulated!==false?'通知回執待核實':labels[item.status]||'通知狀態待核對'}{item.error&&<small>{item.error}</small>}</p>)}</div>;
}
