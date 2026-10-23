import {useEffect,useState} from 'react';
import {Button,Skeleton} from './design';
import {Card} from './homeCards';
import {boardDisplay,dispatchWeek,snapshotAge} from './dispatchBoardModel';
import {useDispatchBoardRead,type DispatchRead} from './DispatchBoard';
import './HomeDispatchCard.css';

export function HomeDispatchFrame({from,read}:{from:string;read:DispatchRead}) {
 const [now,setNow]=useState(Date.now);
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),60000);return()=>clearInterval(timer)},[]);
 const display=boardDisplay(read.data,read.error),loading=display.kind==='loading';
 const board=display.kind==='forbidden'?undefined:read.data;
 const failed=display.kind==='failed'||display.kind==='retained';
 const stale=board?.source.quality.states.includes('stale')||display.kind==='retained';

 return <Card id="dispatch" subtitle={`本週 ${from.replaceAll('-','/')} 起 · 工作預排來源`} href="#view=dispatch" action="開啟派工看板">
  <a className="home-dispatch-link" href="#view=dispatch&tab=work">查看工作進度與需要我處理</a>
  <div className="home-dispatch-summary" data-dispatch-state={display.kind} aria-busy={loading}>
   <dl>{(['unassigned','unknown_overlap','conflict'] as const).map((key,index)=><div key={key}><dt>{['待派','同日重疊待確認','已核實時段衝突'][index]}</dt><dd>{loading?<Skeleton width="3rem" height="2rem"/>:<strong className="home-dispatch-count">{display.counts?display.counts[key]:'—'}</strong>}</dd></div>)}</dl>
   <div className="home-dispatch-source" role={failed?'alert':'status'}>{loading?<Skeleton lines={3}/>:<>
    <p>{failed?'派工資料讀取失敗。'+(display.counts?'已保留上次成功資料，數字為上次快照。':'目前無法核實預排，未以零代替。'):display.kind==='forbidden'?'沒有派工資料的檢視權限。':display.kind==='empty'?display.message:stale?'上次成功快照，資料待更新。':'依本週已載入預排，資格與出勤仍待核對。'}</p>
    {board&&<><p>最後預排日期 · {board.source.latest_booking_date??'來源未提供'}{stale&&` · ${board.source.quality.age_seconds!==null?`${Math.floor(board.source.quality.age_seconds/60)} 分鐘前`:snapshotAge(board.source.fetched_at,now)}`}</p>{board.gaps.filter(g=>g.code!=='no_capability_source').map((gap,index)=><p key={index}>{gap.message}</p>)}</>}
   </>}</div>
   <Button disabled={read.loading} onClick={read.reload}>{read.loading?'讀取中…':failed?'重試':'重新讀取'}</Button>
  </div>
 </Card>;
}

export function HomeDispatchCard({today,reloadVersion}:{today:string;reloadVersion?:number}) {
 const from=dispatchWeek(today),read=useDispatchBoardRead(from,reloadVersion);
 return <HomeDispatchFrame from={from} read={read}/>;
}
