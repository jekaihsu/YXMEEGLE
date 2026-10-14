import {useEffect, useState} from 'react';
import {useFetched} from './IntegratedPages';
import {buildMyWorkView} from './myWorkView';
import {buildManagerOverviewView} from './managerOverviewView';
import {buildSourceHealthView} from './sourceHealthView';
import {buildConfirmationListView} from './confirmationListView';
import {myWorkInput, sourceHealthInput} from './integrationRoutes';
import {buildPmGlanceView, staleReaders, TILE_STATE_LABELS} from './pmGlanceView';
import type {TileReader} from './pmGlanceView';
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
function GlanceReads({c}: {c: Ctx}) {
 const [retries, setRetries] = useState<Record<TileReader, number>>({work: 0, overview: 0, sources: 0, confirmations: 0, attendance: 0});
 const version = c.reloadVersion ?? c.w.version;
 const user = c.s.user?.id;
 const work = useFetched('/api/my-work', `${version}|${retries.work}`, user);
 const overview = useFetched('/api/manager-overview', `${version}|${retries.overview}`, user);
 const sources = useFetched('/api/source-health', `${version}|${retries.sources}`, user);
 const confirmations = useFetched('/api/confirmations', `${version}|${retries.confirmations}`, user);
 const week = taipeiWeek();
 const attendance = useViewData(`people-attendance:${user}:${week}`, async (signal, current) => {
  try {return await fetchPeopleAttendance({week, signal, current})}
  catch (error) {
   if (error instanceof ApiError && error.status === 403) return parsePeopleAttendance({status: 'needs-permission'});
   throw error;
  }
 }, [version, retries.attendance]);
 useEffect(() => {
  if (attendance.loading || attendance.error || !attendance.data || !(attendance.data.refreshing || attendance.data.status === 'loading')) return;
  const timer = setTimeout(attendance.reload, 2000);
  return () => clearTimeout(timer);
 }, [attendance.data, attendance.loading, attendance.error, attendance.reload]);
 const manager = buildManagerOverviewView({body: bodyOf(overview)});
 if (overview.status !== 'ok') {
  // The existing model owns unknown counts; transport supplies only its failure state.
  manager.snapshot.state = overview.status === 'error' && overview.httpStatus === 403 ? {states: ['forbidden']} :
   overview.status === 'error' ? {states: ['read_failed'], count: null} : {states: ['loading'], count: null};
 }
 const tiles = buildPmGlanceView({
  attendance: attendance.error ? {kind: 'failed'} : attendance.data ? {kind: 'ready', view: attendance.data} : {kind: 'loading'},
  work: buildMyWorkView(myWorkInput(work, {mode: 'todo', search: '', selectedId: null})),
  awaiting: buildMyWorkView(myWorkInput(work, {mode: 'awaiting_my_confirmation', search: '', selectedId: null})),
  overview: manager,
  sources: buildSourceHealthView(sourceHealthInput(sources), {diagnosticCapability: false}),
  confirmations: buildConfirmationListView(confirmations.status === 'ok' ? confirmations.body :
   confirmations.status === 'error' && confirmations.httpStatus === 403 ? {status: 403} : undefined),
 });
 if (confirmations.status !== 'ok') {
  const tile = tiles.find(item => item.id === 'confirmations');
  if (tile) tile.state = confirmations.status === 'error' ? confirmations.httpStatus === 403 ? 'needs-permission' : 'failed' : 'unknown';
 }
 const stale = staleReaders(tiles);
 const refresh = () => setRetries(previous => {
  const next = {...previous};
  for (const reader of stale) next[reader]++;
  return next;
 });
 return <section className="page pm-glance" aria-label="PM 一覽">
  <header className="pm-glance-head"><div><span className="eyebrow">專案經理工作台</span><h1>PM 一覽</h1>
   <p>先看待確認、案件風險與資料狀態，再開啟明細。未知資料以 — 顯示。</p></div>
   <button className="button" type="button" disabled={!stale.length} onClick={refresh}>更新過期資料{stale.length ? `（${stale.length}）` : ''}</button>
  </header>
  <p className="pm-glance-note" role="status">{stale.length ? '只重新讀取標示「資料待更新」的區塊。' : '目前沒有可更新的過期區塊。'} 讀取失敗或權限問題請開啟明細查看。</p>
  <div className="pm-glance-grid">{tiles.map(tile => <article key={tile.id} className={`pm-glance-tile state-${tile.state}`} data-tile={tile.id} data-state={tile.state}>
   <div className="pm-glance-tile-head"><h2>{tile.title}</h2><span className="pm-glance-state">{TILE_STATE_LABELS[tile.state]}</span></div>
   <strong className="pm-glance-value">{tile.value}</strong><small>{tile.asOf}</small><p>{tile.reason}</p>
   <a href={tile.href}>開啟明細 <span aria-hidden="true">↗</span></a>
  </article>)}</div>
 </section>;
}
