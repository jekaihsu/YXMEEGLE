// P1-INT pages: #work -> MyWorkTable(buildMyWorkView(...)), #sources -> SourceHealth(buildSourceHealthView(...)).
// The legacy MyWork / Sources screens stay reachable through tab=legacy. Transport only; all state text comes
// from the view models. New GETs: /api/my-work and /api/source-health.
import {useCallback, useEffect, useMemo, useState} from 'react';
import {api, ApiError, getSessionEpoch, parseRoute} from './api';
import {MyWorkTable} from './MyWorkTable';
import {SourceHealth} from './SourceHealth';
import {buildMyWorkView} from './myWorkView.ts';
import {buildSourceHealthView} from './sourceHealthView.ts';
import {filtersFromRoute, hashOfRoute, isLegacyTab, myWorkInput, sourceHealthInput, withFilters} from './integrationRoutes.ts';
import {Segmented} from './design';
import type {Ctx} from './appCommon';

type Fetched = {status: 'loading'} | {status: 'ok'; body: unknown} | {status: 'error'; httpStatus?: number};

function useFetched(url: string, version: unknown): Fetched {
 const [fetched, setFetched] = useState<Fetched>({status: 'loading'});
 useEffect(() => {
  const epoch = getSessionEpoch();
  const controller = new AbortController();
  api<unknown>(url, {signal: controller.signal, cache: 'no-store'})
   .then(body => {if (epoch === getSessionEpoch()) setFetched({status: 'ok', body})})
   .catch(error => {
    if (controller.signal.aborted || epoch !== getSessionEpoch()) return;
    setFetched({status: 'error', httpStatus: error instanceof ApiError ? error.status : undefined});
   });
  return () => controller.abort();
 }, [url, version]);
 return fetched;
}

export function LegacyTabs({c, view}: {c: Ctx; view: 'work' | 'sources'}) {
 const legacy = isLegacyTab(c.route, view);
 const labels = view === 'work' ? ['我的工作', '舊版工作清單'] : ['來源健康', '舊版來源與同步'];
 return <Segmented label={view === 'work' ? '我的工作檢視' : '資料來源檢視'} options={[['new', labels[0]], ['legacy', labels[1]]]}
  value={legacy ? 'legacy' : 'new'} onChange={v => c.go(v === 'legacy' ? {view, tab: 'legacy'} : {view})}/>;
}

// Set when a My Work row navigates away; the remounted page restores focus only when browser Back lands on that exact hash.
let pendingReturnHash: string | null = null;

export function WorkPage({c}: {c: Ctx}) {
 const fetched = useFetched('/api/my-work', c.reloadVersion ?? c.w.version);
 const filters = useMemo(() => filtersFromRoute(c.route), [c.route]);
 const view = useMemo(() => buildMyWorkView(myWorkInput(fetched, filters)), [fetched, filters]);
 // Selection pushes a history entry (Back closes the drawer); typing replaces it.
 const update = useCallback((next: Partial<typeof filters>, replace: boolean) => c.go(withFilters(c.route, {...filters, ...next}), replace), [c, filters]);
 const navigate = useCallback((route: string) => {
  const hash = hashOfRoute(route);
  if (!hash) return;
  pendingReturnHash = location.hash;
  c.go(parseRoute(hash) as Ctx['route']);
 }, [c]);
 // Peek on every render (StrictMode safe); cleared once focus has been restored.
 const restoreFocus = pendingReturnHash !== null && pendingReturnHash === location.hash;
 const focusRestored = useCallback(() => {pendingReturnHash = null}, []);
 return <main className="page work-page" aria-label="我的工作">
  <LegacyTabs c={c} view="work"/>
  <MyWorkTable view={view} onSelect={id => update({selectedId: id}, false)} onModeChange={mode => update({mode, selectedId: null}, true)}
   onSearch={search => update({search}, true)} onNavigate={navigate}
   restoreFocus={restoreFocus} onFocusRestored={focusRestored}/>
 </main>;
}

export function SourceHealthPage({c}: {c: Ctx}) {
 const fetched = useFetched('/api/source-health', c.reloadVersion ?? c.w.version);
 // G-DIAG is open: no diagnostic capability exists, so the page shows the page state only.
 const view = useMemo(() => buildSourceHealthView(sourceHealthInput(fetched), {diagnosticCapability: false}), [fetched]);
 return <main className="page sources-page" aria-label="資料來源">
  <LegacyTabs c={c} view="sources"/>
  <SourceHealth view={view}/>
 </main>;
}
