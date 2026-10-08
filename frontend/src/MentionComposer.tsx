import {Badge,Button,Row} from './design';
import {useId, useRef, useState} from 'react';
import type {User} from './types';
import {useDraft} from './drafts';
import './mentions.css';

const personLabel=(person:User|undefined,users:User[])=>{if(!person)return '原標註同事';const duplicate=users.filter(u=>u.name===person.name);return person.name+(duplicate.length>1?` · ${person.department||'部門待核對'} · ${person.id.slice(-6)}`:'')};

export function MentionTags({ids,users}:{ids?:string[];users:User[]}){
 if(!ids?.length)return null;
 return <div className="mention-tags" aria-label="標註同事">{ids.map(id=>{const person=users.find(u=>u.id===id);return <span className="mention-chip" key={id} title={person?.department||''}><Badge>@{personLabel(person,users)}{person?.active===false&&'（已停用）'}</Badge></span>})}</div>;
}

export function MentionComposer({users,busy,onSubmit,storageKey}:{users:User[];busy:boolean;storageKey:string;onSubmit:(body:string,mentions:string[])=>Promise<boolean>}){
 const[body,setBody]=useDraft(storageKey+':body','');const[selected,setSelected]=useDraft<string[]>(storageKey+':mentions',[]);const[open,setOpen]=useState(false);const[query,setQuery]=useState('');
 const textarea=useRef<HTMLTextAreaElement>(null);const search=useRef<HTMLInputElement>(null);const pickerId=useId();
 const candidates=users.filter(u=>u.active!==false&&u.can_mention===true&&!selected.includes(u.id)&&`${u.name} ${u.department}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
 const openPicker=()=>{setOpen(true);setQuery('');requestAnimationFrame(()=>search.current?.focus())};
 const select=(id:string)=>{setSelected(value=>value.includes(id)?value:[...value,id]);setOpen(false);setQuery('');textarea.current?.focus()};
 return <form onSubmit={async e=>{
  e.preventDefault();if(busy||!body.trim())return;
  const form=e.currentTarget;const hadFocus=form.contains(document.activeElement);
  try{if(await onSubmit(body,selected)){setBody('');setSelected([]);setOpen(false)}}
  finally{requestAnimationFrame(()=>{
   if(form.isConnected&&hadFocus&&(document.activeElement===document.body||form.contains(document.activeElement)))textarea.current?.focus();
  })}
 }} className="mention-composer">
  <textarea ref={textarea} value={body} onChange={e=>{const text=e.target.value;setBody(text);const before=text.slice(0,e.target.selectionStart);if(/(?:^|\s)@$/.test(before)&&!(e.nativeEvent as InputEvent).isComposing)openPicker()}} rows={2} placeholder="留下進度或交接事項，輸入 @ 標註同事…" aria-label="新增評論" disabled={busy}/>
  {selected.length>0&&<div className="mention-tags" aria-label="將標註的同事">{selected.map(id=>{const person=users.find(u=>u.id===id);return <span className="mention-chip" key={id}><Badge>@{personLabel(person,users)}<button type="button" disabled={busy} aria-label={`移除標註 ${personLabel(person,users)}`} onClick={()=>setSelected(value=>value.filter(v=>v!==id))}>×</button></Badge></span>})}</div>}
  {selected.some(id=>!users.some(u=>u.id===id&&u.can_mention===true&&u.active!==false))&&<p role="alert" className="form-error">部分標註對象已停用或尚未核實 Lark 帳號；請移除後重新選擇，留言草稿仍保留。</p>}
  <div className="mention-actions"><Button variant="plain" disabled={busy} aria-expanded={open} aria-controls={pickerId} onClick={()=>{if(open)setOpen(false);else openPicker()}}>＠ 標註同事</Button><small>留言儲存後通知同事；測試區僅模擬，送達狀態另行顯示。</small><Button type="submit" variant="primary" disabled={busy||!body.trim()||selected.some(id=>!users.some(u=>u.id===id&&u.can_mention===true&&u.active!==false))}>{busy?'儲存中…':'送出'}</Button></div>
  {open&&<section id={pickerId} data-local-escape className="mention-picker glass--flat" aria-label="選擇標註同事" onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();setOpen(false);textarea.current?.focus()}}}>
   <label>搜尋同事<input data-reload-safe ref={search} value={query} onChange={e=>setQuery(e.target.value)} placeholder="姓名或部門" onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();if(candidates.length===1)select(candidates[0].id)}}}/></label>
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
