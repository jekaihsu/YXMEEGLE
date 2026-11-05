// Dependency-free P2 route names for App.tsx (eager). Must list the same routes as P2_ROUTES in drilldownContext.ts.
import type {P2Route} from './drilldownContext.ts';

const P2_ROUTE_NAMES: readonly P2Route[] = ['overview', 'confirmations', 'confirmation', 'contract', 'workitem'];
export const isP2View = (view: unknown): view is P2Route => typeof view === 'string' && (P2_ROUTE_NAMES as readonly string[]).includes(view);
// The three detail routes have no own left-navigation entry; they highlight the list they were opened from.
export const p2ActiveNav = (view: string): string => view === 'confirmation' || view === 'contract' || view === 'workitem' ? 'confirmations' : view;

