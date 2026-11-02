import type {ReactNode} from 'react';
import {Loader2,Inbox,Clock3,TriangleAlert,CircleAlert,ShieldAlert,GitCompareArrows,CircleHelp} from 'lucide-react';
import './data-state.css';
export type DataStateKind='Loading'|'Empty'|'Stale'|'Partial'|'Error'|'Denied'|'Conflict'|'UnknownOutcome';
/** Region-local feedback. Supply truthful title/body and optional explicit actions.
 * No implicit retry or refresh is performed. Omitted actions create no action row.
 * Loading/Empty/Stale/Partial are polite status; errors and write uncertainty alert.
 * Render once per shared source; retained content belongs outside this component. */
export type DataStateProps={kind:DataStateKind;title:string;body:ReactNode;actions?:ReactNode};
const icons={Loading:Loader2,Empty:Inbox,Stale:Clock3,Partial:CircleAlert,Error:TriangleAlert,Denied:ShieldAlert,Conflict:GitCompareArrows,UnknownOutcome:CircleHelp};
export function DataState({kind,title,body,actions}:DataStateProps){
 const Icon=icons[kind];
 return <div className="ds-data-state" data-kind={kind} role={['Error','Denied','Conflict','UnknownOutcome'].includes(kind)?'alert':'status'}><Icon aria-hidden="true" size={24}/><div className="ds-data-state-copy"><strong>{title}</strong><div>{body}</div>{actions!=null&&actions!==false&&<div className="ds-data-state-actions">{actions}</div>}</div></div>;
}
