import type {FeatureContract} from './types';
type DispatchSession = {features?:FeatureContract;user?:{role?:string}|null;mode?:string;workspace_id?:string}|null|undefined;
export function canReadDispatch(session:DispatchSession):boolean {
 return session?.features?.dispatch_board===true&&(session.user?.role==='pm'||session.user?.role==='manager')&&session.mode==='lark'&&!!session.workspace_id&&!session.workspace_id.startsWith('test-')&&!session.workspace_id.startsWith('demo-');
}
