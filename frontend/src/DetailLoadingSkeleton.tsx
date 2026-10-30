import {Skeleton} from './design';
import './DetailLoadingSkeleton.css';

export function TableLoadingSkeleton({label}:{label:string}) {
 return <div className="detail-table-loading"><p className="my-work-loading" role="status">{label}</p><div aria-hidden="true" className="detail-table-placeholder">{Array.from({length:5},(_,row)=><div className="detail-table-placeholder-row" key={row}>{Array.from({length:4},(_,col)=><Skeleton key={col} width={col===0?'85%':'65%'} height={row===0?'1rem':'.875rem'}/>)}</div>)}</div></div>;
}

export function CaseDetailSkeleton() {
 return <div className="case-detail-loading"><p role="status">正在載入案件詳細內容…</p><div aria-hidden="true"><div className="p2-card"><Skeleton width="25%"/><Skeleton width="60%" height="2rem"/><div className="case-detail-placeholder-fields">{Array.from({length:8},(_,i)=><Skeleton key={i} lines={2}/>)}</div></div><div className="case-detail-placeholder-layout"><div>{['總覽','確認單版本','合約明細','工項','流程節點／SOP','報告與文件','歷程'].map(title=><section className="p2-card" key={title}><h2>{title}</h2><div className="detail-table-placeholder">{Array.from({length:3},(_,i)=><div className="detail-table-placeholder-row" key={i}><Skeleton/><Skeleton/><Skeleton/><Skeleton/></div>)}</div></section>)}</div><aside className="p2-card"><Skeleton lines={4}/></aside></div></div></div>;
}
