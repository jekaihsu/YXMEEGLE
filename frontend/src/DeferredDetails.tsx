import {useState,type ReactNode} from 'react';
export function DeferredDetails({title,children}:{title:string;children:ReactNode}){
 const [opened,setOpened]=useState(false);
 return <details className="pf-secondary" onToggle={e=>setOpened(e.currentTarget.open)}><summary>{title}</summary>{opened&&children}</details>;
}
