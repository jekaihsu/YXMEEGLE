import type {ReactNode} from 'react';
import {MoreHorizontal} from 'lucide-react';
import {DetailsMenu} from './design/DetailsMenu';

export type SheetMenuItem={key:string;label:ReactNode;onSelect:()=>void};

/** Footer contract: one stable row — optional ⋯ overflow column, then the single primary action. */
export function SheetActions({primary,menu}:{primary?:ReactNode;menu:SheetMenuItem[]}){
 if(!primary&&!menu.length)return null;
 return <div className="task-drawer-actions" data-has-menu={menu.length>0}>
  {menu.length>0&&<DetailsMenu className="task-drawer-more" label={<MoreHorizontal size={20} aria-hidden="true"/>} ariaLabel="更多操作">{close=><div className="task-drawer-more-list">{menu.map(item=><button key={item.key} type="button" className="button plain" onClick={()=>{close();item.onSelect()}}>{item.label}</button>)}</div>}</DetailsMenu>}
  {primary&&<div className="task-drawer-primary">{primary}</div>}
 </div>;
}

export function SheetPrimary({busy,disabled,describedBy,onClick,children}:{busy?:boolean;disabled?:boolean;describedBy?:string;onClick:()=>void;children:ReactNode}){
 return <button type="button" className="button primary" disabled={busy||disabled} aria-describedby={describedBy} aria-busy={busy||undefined} onClick={onClick}>{children}</button>;
}
