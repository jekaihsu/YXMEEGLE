import {useReport} from './useReport';
import {MetaNotice,Metrics,ReportState} from './shared';
import type {HomeReport} from './types';
export default function HomeTab(){const r=useReport<HomeReport>('home',{});if(!r.data)return <ReportState {...r}/>;const d=r.data;return <><MetaNotice meta={d.meta}/><h2>週報首頁</h2><Metrics items={[{label:'檢查筆數',value:d.quality?.kpi.total??'—'},{label:'案件數',value:d.sales?.kpi.cases??'—'},{label:'進行案件',value:d.progress?.kpi.open_cases??'—'}]}/></>}
