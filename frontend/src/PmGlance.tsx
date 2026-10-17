import {readPanel} from './companyDashboardCache';
import {Skeleton} from './design';
import {buildMyWorkView} from './myWorkView';
import {buildManagerOverviewView} from './managerOverviewView';
import {buildSourceHealthView} from './sourceHealthView';
import {buildConfirmationListView} from './confirmationListView';
import {myWorkInput, sourceHealthInput} from './integrationRoutes';
import {buildPmGlanceView, SOURCE_TILE_IDS, parseCaseCount, TILE_STATE_LABELS} from './pmGlanceView';
import type {CaseRead} from './pmGlanceView';
import type {Fetched} from './IntegratedPages';
import type {Ctx} from './appCommon';
import {pmGlanceVisible} from './pmGlanceConfig';
import {useViewData} from './viewData';
import {fetchPeopleAttendance, parsePeopleAttendance, taipeiWeek} from './peopleAttendance';
import {ApiError} from './api';
import './pm-glance.css';

const bodyOf = (read: Fetched): unknown => read.status === 'ok' ? read.body : undefined;

export function PmGlancePage({c}: {c: Ctx}) {
 return pmGlanceVisible(c.s.user?.role) ? <GlanceReads c={c}/> : <p role="status">此角色尚未開放 PM 一覽。</p>;
}

function useGlanceRead(url: string, user: unknown) {
 return useViewData<Fetched>(`pm:${user}:${url}`, async (signal) => {
  try {return {status: 'ok', body: await readPanel(url,signal,String(user))}}
  catch (error) {return {status: 'error', httpStatus: error instanceof ApiError ? error.status : undefined}}
 });
}

function GlanceReads({c}: {c: Ctx}) {
 const user = JSON.stringify([c.s.user?.id,c.s.user?.role,c.s.workspace_id,c.w.workspace_id]);
 const workRead = useGlanceRead('/api/my-work', user);
 const overviewRead = useGlanceRead('/api/projects?limit=1', user);
 const sourcesRead = useGlanceRead('/api/source-health', user);
 const confirmationsRead = useGlanceRead('/api/confirmations', user);
 const work: Fetched = workRead.data ?? {status: 'loading'};
 const overview: Fetched = overviewRead.data ?? {status: 'loading'};
 const sources: Fetched = sourcesRead.data ?? {status: 'loading'};
 const confirmations: Fetched = confirmationsRead.data ?? {status: 'loading'};
 const week = taipeiWeek();
 const attendance = useViewData(`people-attendance:${user}:${week}`, async (signal, current) => {
  try {return await fetchPeopleAttendance({week, signal, current})}
  catch (error) {
   if (error instanceof ApiError && error.status === 403) return parsePeopleAttendance({status: 'needs-permission'});
   throw error;
  }
 });
 const reads = {work: workRead, overview: overviewRead, sources: sourcesRead, confirmations: confirmationsRead, attendance};
 const loading = Object.values(reads).some(read => read.loading);

 const manager = buildManagerOverviewView({});
 const caseCount = overview.status === 'ok' ? parseCaseCount(overview.body) : null;
 const cases: CaseRead = overview.status === 'loading' ? {kind: 'loading'} : overview.status === 'error' && overview.httpStatus === 403 ? {kind: 'needs-permission'} :
  caseCount === null ? {kind: 'failed'} : {kind: 'ready', count: caseCount, asOf: null};
 const tiles = buildPmGlanceView({
  attendance: attendance.error ? {kind: 'failed'} : attendance.data ? {kind: 'ready', view: attendance.data} : {kind: 'loading'},
  work: buildMyWorkView(myWorkInput(work, {mode: 'todo', search: '', selectedId: null})),
  awaiting: buildMyWorkView(myWorkInput(work, {mode: 'awaiting_my_confirmation', search: '', selectedId: null})),
  overview: manager, cases,
  sources: buildSourceHealthView(sourceHealthInput(sources), {diagnosticCapability: false}),
  confirmations: buildConfirmationListView(confirmations.status === 'ok' ? confirmations.body :
   confirmations.status === 'error' && confirmations.httpStatus === 403 ? {status: 403} : undefined),
 });
 if (confirmations.status !== 'ok') {
  const tile = tiles.find(item => item.id === 'confirmations');
  if (tile) tile.state = confirmations.status === 'error' ? confirmations.httpStatus === 403 ? 'needs-permission' : 'failed' : 'unknown';
 }
 const refresh = () => Object.values(reads).forEach(read => read.reload());
 const groups = [
  {title: '來源與資料缺口', note: '依目前快照顯示已讀取紀錄；待核對資料不當作零，也不推算完成率。', tiles: tiles.filter(tile => SOURCE_TILE_IDS.has(tile.id)&&['source-cases','confirmations'].includes(tile.id)), className: 'pm-glance-source-grid'},
  {title: '我的工作與風險', note: '待確認、逾期與各組工作量需要各自的核實依據，不由來源筆數推算。', tiles: ['work','awaiting','overdue','sources'].flatMap(id=>tiles.filter(tile=>tile.id===id)), className: ''},
 ].reverse();
 groups.push({title:'其他來源資訊',note:'名冊、出勤與組別工作量另列，不佔主要工作區。',tiles:tiles.filter(tile=>!groups.some(group=>group.tiles.some(shown=>shown.id===tile.id))),className:''});
 return <section className="page pm-glance" aria-label="PM 一覽" aria-busy={loading}>
  <header className="pm-glance-head"><div><span className="eyebrow">專案經理工作台</span><h1>PM 一覽</h1>
   <p>先看本人工作、待確認與風險，再查案件與確認單版本。</p></div>
   <button className="button" type="button" disabled={loading} onClick={refresh}>重新讀取資料</button>
  </header>
  {groups.map(group => {const content=<section className="pm-glance-section" key={group.title} aria-label={group.title}>
   <h2>{group.title}</h2><p className="pm-glance-section-note">{group.note}</p>
   <div className={`pm-glance-grid ${group.className}`}>{group.tiles.map(tile => {
    const initialLoading = tile.reader && reads[tile.reader].loading && !reads[tile.reader].data;
    return <article key={tile.id} className={`pm-glance-tile state-${tile.state}`} data-tile={tile.id} data-state={tile.state}>
     <div className="pm-glance-tile-head"><h3>{tile.title}</h3><span className="pm-glance-state">{initialLoading ? '讀取中' : TILE_STATE_LABELS[tile.state]}</span></div>
     <strong className={`pm-glance-value${initialLoading ? ' pm-glance-value-loading' : ''}`} aria-label={initialLoading ? '讀取中' : undefined}>{initialLoading ? <span aria-hidden="true"><Skeleton width="4rem"/></span> : tile.value}</strong><small>{tile.asOf}</small><p>{tile.reason}</p>
     <a href={tile.href}>開啟明細 <span aria-hidden="true">↗</span></a>
    </article>;
   })}</div>
  </section>;return group.title==='其他來源資訊'?<details key={group.title}><summary>{group.title}</summary>{content}</details>:content;})}
 </section>;
}
