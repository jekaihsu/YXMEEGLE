import type {SopSignals} from './sopTaskApi';
import type {SopWorkItem} from './SopWorkSummary';
import type {SourceLifecycle} from './sourceLifecycle';

export interface CompanyDashboard {
 sop_signals?:SopSignals;sop_items?:SopWorkItem[];
 as_of:string;checked_at:string;date_basis:string;source:{status:string;mapping_status:string;last_success_at:string|null};
 totals:{cases:number;confirmed_cases:number;intake_records:number;workbench_cases:number;deliveries_confirmed:number;source_status_counts:Record<string,number>;lifecycle_counts?:Record<string,number>;execution_status_counts:Record<string,number>;tasks_total:number;tasks_completed:number;tasks_overdue:number;pending_local_reviews:number;pending_native_reviews:number};
 source_deadlines?:{cases:number;tasks:number;buckets:{key:string;cases:number;tasks:number}[]};
 missing:{task_due_date:number;group:number;source_status:number};
 groups:{group:string;cases:number;tasks_total:number;tasks_completed:number;tasks_overdue:number}[];
 cases:{case_type:'formal'|'intake';id:string;code:string;name:string;group:string;source_status:string;source_lifecycle?:SourceLifecycle;execution_status:string;execution_system?:string;execution_system_label?:string;execution_readonly_reason?:string|null;case_visibility?:string|null;workbench_execution_enabled?:boolean;tasks_total:number;tasks_completed:number;tasks_overdue:number;pending_local_reviews:number;pending_native_reviews:number}[];
 complete?:boolean;total_count?:number|null;count_scope?:string;
 pagination:{offset:number;limit:number;total:number;has_more:boolean};
}
