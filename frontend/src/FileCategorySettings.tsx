import {useState} from 'react';
import type {Context} from './Operations';

export function FileCategorySettings({c}:{c:Context}){
 const[id,setId]=useState('');const[name,setName]=useState('');const[active,setActive]=useState(true);const[message,setMessage]=useState('');
 if(c.s.user?.role!=='manager')return null;
 return <section className="file-category-settings"><h2>文件類別管理</h2><p>分類用於檔案整理；停用類別會保留原檔案與歷史，不刪除檔案。</p><div className="file-category-list">{(c.w.file_categories||[]).map((category:any)=><button className="button" key={category.id} onClick={()=>{setId(category.id);setName(category.name);setActive(category.active!==false);setMessage('')}}>{category.name}{category.active===false?'（已停用）':''}</button>)}</div><form onSubmit={async e=>{e.preventDefault();const result=await c.run('file_category_save',{id,name,active});if(result){setMessage('文件類別已儲存');setId('');setName('');setActive(true)}}}><div className="daily-filters"><label>類別識別<input value={id} onChange={e=>setId(e.target.value)} pattern="[a-z][a-z0-9_\-]*" required placeholder="例如 survey_note"/></label><label>類別名稱<input value={name} onChange={e=>setName(e.target.value)} required/></label></div><label><input type="checkbox" checked={active} onChange={e=>setActive(e.target.checked)}/>啟用此類別</label><button className="button primary" disabled={c.busy}>儲存類別</button><button className="button" type="button" onClick={()=>{setId('');setName('');setActive(true)}}>新增類別</button><p role="status">{message}</p></form></section>;
}
