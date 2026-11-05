import type {Route} from './types';
import './design/skeleton.css';
import './RouteSkeleton.css';

export function RouteSkeleton({route,title}:{route:Route;title:string}){
 const detail=['project','confirmation','contract','workitem'].includes(route.view);
 const table=['quotes','reports','sources'].includes(route.view);
 const cards=['dashboard','overview','admin','people'].includes(route.view);
 return <section className={`route-skeleton ${table?'route-skeleton-table':detail?'route-skeleton-detail':cards?'route-skeleton-cards':'route-skeleton-list'}`} aria-label={title}>
  <p className="sr-only" role="status" aria-live="polite">正在載入{title}…</p>
  <div aria-hidden="true">
   <header className="page-heading"><div><h1>{title}</h1><div className="skeleton route-skeleton-subtitle"/></div></header>
   <div className="route-skeleton-toolbar"><div className="skeleton"/><div className="skeleton"/><div className="skeleton"/></div>
   <div className="route-skeleton-content">{table?<div className="route-skeleton-table-body">{Array.from({length:6},(_,row)=><div className="skeleton-table-row" key={row}>{Array.from({length:4},(_,col)=><div className="skeleton" key={col}/>)}</div>)}</div>:Array.from({length:cards?4:detail?2:5},(_,key)=><div className="route-skeleton-block" key={key}><div className="skeleton"/><div className="skeleton"/><div className="skeleton"/></div>)}</div>
  </div>
 </section>;
}
