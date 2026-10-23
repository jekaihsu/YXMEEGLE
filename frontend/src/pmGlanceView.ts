import type {DataStateName} from './dataState';
import type {MyWorkView} from './myWorkView.ts';
import type {ManagerOverviewView} from './managerOverviewView';
import type {SourceHealthView} from './sourceHealthView';
import type {ConfirmationListView} from './confirmationListView';
import {attendanceValue, attendanceStatusLabel} from './peopleAttendance.ts';
import type {PeopleAttendance} from './peopleAttendance.ts';
import {taipeiTime} from './taipeiTime.ts';
import {encodeReturnContext} from './myWorkView.ts';

export type TileState = 'ok' | 'stale' | 'partial' | 'failed' | 'needs-permission' | 'unknown';
export type TileReader = 'work' | 'overview' | 'sources' | 'confirmations' | 'attendance';
export type CaseRead = {kind: 'loading'} | {kind: 'failed'} | {kind: 'needs-permission'} | {kind: 'ready'; count: number; asOf: string | null};
export function parseCaseCount(body: unknown): number | null {
 const count = body && typeof body === 'object' ? Reflect.get(body, 'total') : undefined;
 return typeof count === 'number' && Number.isSafeInteger(count) && count >= 0 ? count : null;
}
export type AttendanceRead = {kind: 'loading'} | {kind: 'ready'; view: PeopleAttendance} | {kind: 'failed'};
export type GlanceTile = {
 id: string; title: string; value: string; asOf: string; state: TileState; reason: string;
 href: string; reader: TileReader | null;
};
export const TILE_STATE_LABELS: Record<TileState, string> = {
 ok: '已讀取', stale: '資料待更新', partial: '已讀取部分', failed: '讀取失敗', 'needs-permission': '需要權限', unknown: '未知',
};
export const SOURCE_TILE_IDS = new Set(['confirmations', 'source-cases', 'source-people', 'source-trips']);
export function tileState(states: readonly DataStateName[] | undefined): TileState {
 if (states?.includes('forbidden')) return 'needs-permission';
 if (states?.includes('read_failed')) return 'failed';
 if (states?.includes('loading') || states?.includes('unknown') || states?.includes('unlocated')) return 'unknown';
 if (states?.includes('stale')) return 'stale';
 if (states?.includes('partial')) return 'unknown';
 return 'ok';
}
const workHref = (mode: MyWorkView['mode']) => `#view=work&ctx=${encodeURIComponent(encodeReturnContext({mode}))}`;
const countText = (count: number | null, state: TileState): string =>
 (state === 'ok' || state === 'stale') && count !== null ? String(count) : '—';
const ATTENDANCE_TILE_STATES: Record<PeopleAttendance['status'], TileState> = {
 loading: 'unknown', ok: 'ok', incomplete: 'unknown', stale: 'stale', 'needs-permission': 'needs-permission', 'not-connected': 'unknown', 'read-failed': 'failed',
};
export function attendanceTiles(read: AttendanceRead): GlanceTile[] {
 const view = read.kind === 'ready' ? read.view : undefined;
 const state = read.kind === 'failed' ? 'failed' : view ? ATTENDANCE_TILE_STATES[view.status] : 'unknown';
 const reason = read.kind === 'failed' ? '讀取失敗，請開啟人員與出勤明細。' : view ?
  [attendanceStatusLabel[view.status], view.week_start && view.week_end ? `${view.week_start} 至 ${view.week_end}` : '', view.incomplete ? '資料不完整，空白不代表沒有請假或出差。' : '',
   view.refreshing ? '正在更新' : '', view.missing_scopes.length ? `缺少唯讀權限：${view.missing_scopes.join('、')}` : ''].filter(Boolean).join(' · ') : '讀取中';
 const metrics: [string, string, number | null | undefined][] = [['leave', '本週請假', view?.summary.on_leave], ['trips', '本週出差', view?.summary.on_trip]];
 return metrics.map(([id, title, value]) => ({
  id, title, state, value: state === 'ok' || state === 'stale' ? attendanceValue(value) : '—',
  asOf: `資料日期 ${taipeiTime(view?.as_of)}`, reason, href: '#view=people', reader: 'attendance',
 }));
}
export function buildPmGlanceView(input: {
 work: MyWorkView; awaiting: MyWorkView; overview: ManagerOverviewView;
 sources: SourceHealthView; confirmations: ConfirmationListView; attendance: AttendanceRead; cases: CaseRead;
}): GlanceTile[] {
 const {work, awaiting, overview, sources, confirmations} = input;
 const workTile = (view: MyWorkView, id: string, title: string): GlanceTile => {
  const state = tileState(view.pageState?.states);
  return {id, title, state, value: countText(state === 'stale' && view.rows.length === 0 ? null : view.count, state), asOf: view.dataAsOfLabel === '資料日期 unknown' ? '資料日期 —' : view.dataAsOfLabel,
   reason: view.pageStateLabel ?? (view.count === 0 ? '目前沒有待辦工作' : '完整讀取'), href: workHref(view.mode), reader: 'work'};
 };
 const overdue = overview.snapshot.cards.find(card => card.id === 'overdue_cases');
 const overviewState = tileState(overview.snapshot.state.states);
 const overdueState = overdue?.known ? overviewState : overviewState === 'ok' ? 'unknown' : overviewState;
 const sourceState = tileState(sources.page.states);
 const listState = tileState(confirmations.pageState?.states);
 const cases = input.cases;
 const attendanceView = input.attendance.kind === 'ready' ? input.attendance.view : undefined;
 const recordsRead = attendanceView?.as_of && ['ok', 'incomplete', 'stale'].includes(attendanceView.status) ? attendanceView : undefined;
 const recordTiles = ([['source-people', '已讀取名冊', recordsRead?.people.length],
  ['source-trips', '本週出差／外出', recordsRead?.trips.length]] satisfies [string, string, number | undefined][])
  .map(([id, title, count]): GlanceTile => ({
   id, title, value: count !== undefined && (count > 0 || recordsRead?.status === 'ok') ? String(count) : '—',
   state: input.attendance.kind === 'failed' ? 'failed' : !recordsRead ? attendanceView ? ATTENDANCE_TILE_STATES[attendanceView.status] : 'unknown' : recordsRead.status === 'stale' ? 'stale' : recordsRead.incomplete ? 'partial' : 'ok',
   asOf: `資料日期 ${taipeiTime(recordsRead?.as_of)}`, href: '#view=people', reader: 'attendance',
   reason: (id === 'source-people' ? '已載入名冊紀錄，非全公司在職人數。' : '本週已載入紀錄，非出差人數。') + (recordsRead?.incomplete ? '部分資料待核對。' : ''),
  }));
 const unavailable = (id: string, title: string, href: string, reason: string): GlanceTile =>
  ({id, title, href, reason, value: '—', asOf: '資料日期 —', state: 'unknown', reader: null});
 return [
  {id: 'source-cases', title: '案件與報價紀錄', state: cases.kind === 'ready' ? sourceState === 'stale' ? 'stale' : 'ok' : cases.kind === 'loading' ? 'unknown' : cases.kind,
   value: cases.kind === 'ready' ? String(cases.count) : '—', asOf: `資料日期 ${taipeiTime(cases.kind === 'ready' ? cases.asOf : null)}`,
   reason: '已載入案件與報價紀錄，非已啟用工作台案件數。', href: '#view=projects', reader: 'overview'},
  ...recordTiles,
  awaiting.mode === 'awaiting_my_confirmation' ? workTile(awaiting, 'awaiting', '等待我確認') :
   {...unavailable('awaiting', '等待我確認', '#view=work', '現有我的工作未開放待確認佇列，待確認數量未知'),
    state: tileState(awaiting.pageState?.states) === 'ok' ? 'unknown' : tileState(awaiting.pageState?.states), reader: 'work'},
  {id: 'overdue', title: '逾期／風險案件', state: overdueState, value: countText(overdue?.known ? Number(overdue.valueText) : null, overdueState),
   asOf: overdue?.asOfLabel ?? overview.header.asOfLabel, reason: '核准期限尚未可驗證，逾期與風險數量未知。', href: '#view=overview', reader: 'overview'},
  workTile(work, 'work', '我的工作'),
  {id: 'sources', title: '來源新鮮度', state: sourceState, value: '—', asOf: '資料日期 —', reason: sources.page.statusLabel + '。' + sources.page.explanation,
   href: '#view=sources', reader: 'sources'},
  ...attendanceTiles(input.attendance),
  unavailable('workload', '各組工作量', '#view=overview', '各組工作量尚未可確認。'),
  {id: 'confirmations', title: '工程確認單', state: listState,
   value: (listState === 'ok' || listState === 'stale') && confirmations.footer.matching.reason === null ? confirmations.footer.matching.label : '—',
   asOf: `資料日期 ${taipeiTime(confirmations.header.asOf.label)}`, reason: confirmations.pageStateLabel ?? (confirmations.footer.matching.reason === null ? '已讀取確認單版本，非待確認工作數。' : '確認單母體尚未完整確認，總數未知。'),
   href: '#view=confirmations', reader: 'confirmations'},
 ];
}
export const staleReaders = (tiles: readonly GlanceTile[]): TileReader[] =>
 [...new Set(tiles.flatMap(tile => tile.state === 'stale' && tile.reader ? [tile.reader] : []))];
