import type {ButtonHTMLAttributes,CSSProperties,ReactNode} from 'react';
import {useDialogFocus} from '../useDialogFocus';
import './primitives.css';

export {ThemeProvider,useAppearance} from './appearance';

export function Page({title,subtitle,actions,children}:{title:string;subtitle?:string;actions?:ReactNode;children:ReactNode}){
 return <div className="ds-page"><header className="ds-page-head"><div><h1>{title}</h1>{subtitle&&<p>{subtitle}</p>}</div>{actions&&<div className="ds-actions">{actions}</div>}</header>{children}</div>;
}

/** Inset grouped list: rows separated by hairlines, no card border. */
export function Section({title,footer,children}:{title?:string;footer?:string;children:ReactNode}){
 return <section className="ds-section">{title&&<h2>{title}</h2>}<div className="ds-group">{children}</div>{footer&&<p className="ds-footer">{footer}</p>}</section>;
}

export function Row({label,detail,value,icon,onClick,href}:{label:ReactNode;detail?:ReactNode;value?:ReactNode;icon?:ReactNode;onClick?:()=>void;href?:string}){
 const body=<>{icon&&<span className="ds-row-icon" aria-hidden="true">{icon}</span>}<span className="ds-row-main"><span>{label}</span>{detail&&<small>{detail}</small>}</span>{value!=null&&<span className="ds-row-value">{value}</span>}</>;
 if(href)return <a className="ds-row" href={href}>{body}</a>;
 if(onClick)return <button type="button" className="ds-row" onClick={onClick}>{body}</button>;
 return <div className="ds-row">{body}</div>;
}

export function Stat({label,value,tone}:{label:string;value:ReactNode;tone?:'warning'|'critical'|'positive'}){
 return <div className="ds-stat" data-tone={tone}><strong>{value}</strong><span>{label}</span></div>;
}

/** Status is always text (plus optional icon), never colour alone. */
export function Badge({children,tone,icon}:{children:ReactNode;tone?:'positive'|'warning'|'critical'|'accent';icon?:ReactNode}){
 return <span className="ds-badge" data-tone={tone}>{icon}{children}</span>;
}

export function Button({variant='secondary',...props}:ButtonHTMLAttributes<HTMLButtonElement>&{variant?:'primary'|'secondary'|'plain'|'destructive'}){
 return <button type="button" {...props} className={`ds-button ${props.className||''}`} data-variant={variant}/>;
}

export function Segmented<T extends string>({label,options,value,onChange}:{label:string;options:[T,string][];value:T;onChange:(v:T)=>void}){
 return <div className="ds-segmented" role="radiogroup" aria-label={label}>{options.map(([k,text])=><button key={k} type="button" role="radio" aria-checked={value===k} onClick={()=>onChange(k)}>{text}</button>)}</div>;
}

/** Modal sheet with focus trap, Escape and focus return. */
export function Sheet({title,onClose,children}:{title:string;onClose:()=>void;children:ReactNode}){
 const ref=useDialogFocus(onClose);
 return <div className="ds-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><section ref={ref} tabIndex={-1} className="ds-sheet" role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><Button variant="plain" onClick={onClose} aria-label="關閉">✕</Button></header>{children}</section></div>;
}

/** Placeholder shaped like the content it stands in for; reuses the .skeleton classes viewData consumers already render. */
export function Skeleton({lines=1,width,height}:{lines?:number;width?:CSSProperties['width'];height?:CSSProperties['height']}){
 return <div aria-hidden="true">{Array.from({length:lines},(_,i)=><div key={i} className="skeleton skeleton-row" style={{width,height}}/>)}</div>;
}

export function Progress({value,max=100,label}:{value:number;max?:number;label:string}){
 return <progress className="ds-progress" value={value} max={max} aria-label={label}/>;
}
