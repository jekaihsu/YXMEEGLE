import type {DataStateName} from './dataState';
import type {MyWorkView} from './myWorkView.ts';
import type {ManagerOverviewView} from './managerOverviewView';
import type {SourceHealthView} from './sourceHealthView';
import type {ConfirmationListView} from './confirmationListView';
import {encodeReturnContext} from './myWorkView.ts';

// Replace '*' with ['pm'] when the owner enables PM-only access.
export const PM_GLANCE_ROLES: readonly string[] = ['*'];
export const pmGlanceVisible = (role: string | undefined, roles = PM_GLANCE_ROLES): boolean =>
 !!role && (roles.includes('*') || roles.includes(role));
export type TileState = 'ok' | 'stale' | 'failed' | 'needs-permission' | 'unknown';
export type TileReader = 'work' | 'overview' | 'sources' | 'confirmations';
export type GlanceTile = {
 id: string; title: string; value: string; asOf: string; state: TileState; reason: string;
 href: string; reader: TileReader | null;
};
export const TILE_STATE_LABELS: Record<TileState, string> = {
 ok: '已讀取', stale: '資料待更新', failed: '讀取失敗', 'needs-permission': '需要權限', unknown: '未知',
};
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
export function buildPmGlanceView(input: {
 work: MyWorkView; awaiting: MyWorkView; overview: ManagerOverviewView;
 sources: SourceHealthView; confirmations: ConfirmationListView;
}): GlanceTile[] {
 const {work, awaiting, overview, sources, confirmations} = input;
 const workTile = (view: MyWorkView, id: string, title: string): GlanceTile => {
  const state = tileState(view.pageState?.states);
  return {id, title, state, value: countText(view.count, state), asOf: view.dataAsOfLabel === '資料日期 unknown' ? '資料日期 —' : view.dataAsOfLabel,
   reason: view.pageStateLabel ?? (view.count === 0 ? '目前沒有待辦工作' : '完整讀取'), href: workHref(view.mode), reader: 'work'};
 };
 const overdue = overview.snapshot.cards.find(card => card.id === 'overdue_cases');
 const overviewState = tileState(overview.snapshot.state.states);
 const overdueState = overdue?.known ? overviewState : overviewState === 'ok' ? 'unknown' : overviewState;
 const sourceState = tileState(sources.page.states);
 const listState = tileState(confirmations.pageState?.states);
 const unavailable = (id: string, title: string, href: string, reason: string): GlanceTile =>
  ({id, title, href, reason, value: '—', asOf: '資料日期 —', state: 'unknown', reader: null});
 return [
  awaiting.mode === 'awaiting_my_confirmation' ? workTile(awaiting, 'awaiting', '等待我確認') :
   {...unavailable('awaiting', '等待我確認', '#view=work', '現有我的工作未開放待確認佇列，待確認數量未知'),
    state: tileState(awaiting.pageState?.states) === 'ok' ? 'unknown' : tileState(awaiting.pageState?.states), reader: 'work'},
  {id: 'overdue', title: '逾期／風險案件', state: overdueState, value: countText(overdue?.known ? Number(overdue.valueText) : null, overdueState),
   asOf: overdue?.asOfLabel ?? overview.header.asOfLabel, reason: '核准期限尚未可驗證，逾期與風險數量未知。', href: '#view=overview', reader: 'overview'},
  workTile(work, 'work', '我的工作'),
  {id: 'sources', title: '來源新鮮度', state: sourceState, value: '—', asOf: '資料日期 —', reason: sources.page.statusLabel + '。' + sources.page.explanation,
   href: '#view=sources', reader: 'sources'},
  unavailable('leave', '本週請假', '#view=schedule', '人員與出勤資料尚未提供（not available yet）。'),
  unavailable('trips', '本週出差', '#view=schedule', '人員與出勤資料尚未提供（not available yet）。'),
  unavailable('workload', '各組工作量', '#view=overview', '各組工作量尚未可確認。'),
  {id: 'confirmations', title: '工程確認單', state: listState,
   value: (listState === 'ok' || listState === 'stale') && confirmations.footer.matching.reason === null ? confirmations.footer.matching.label : '—',
   asOf: `資料日期 ${confirmations.header.asOf.label}`, reason: confirmations.pageStateLabel ?? (confirmations.footer.matching.reason === null ? '目前篩選符合的確認單版本數；不是待確認工作數。' : '確認單母體尚未完整確認，總數未知。'),
   href: '#view=confirmations', reader: 'confirmations'},
 ];
}
export const staleReaders = (tiles: readonly GlanceTile[]): TileReader[] =>
 [...new Set(tiles.flatMap(tile => tile.state === 'stale' && tile.reader ? [tile.reader] : []))];
