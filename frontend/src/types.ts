import type {SourceLifecycle} from './sourceLifecycle';
export type LiveDataset = 'sources'|'roster'|'attendance';
export interface DatasetFreshness {
  as_of:string|null; fetched_at:string|null; age_seconds:number|null; ttl_seconds:number;
  status:'fresh'|'stale'|'refreshing'|'error'|'blocked'|'unconfigured'|'never';
  fingerprint:string|null; changed_at:string|null; last_error:string|null;
  lark:{calls:number;retries:number;duration_ms:number}; hard_max_age_seconds?:number;
}
export interface Freshness {server_time:string;enabled:boolean;datasets:Record<LiveDataset,DatasetFreshness>}
export type Status = 'pending'|'in_progress'|'completed'|'paused'|'superseded'|'rework'|string;
export interface User {can_business_override?:boolean;can_mention?:boolean;id:string;name:string;role:string;department:string;avatar:string;active?:boolean;capabilities?:string[];default_workspace?:string}
export interface Comment {id:string;author_id:string;body:string;created_at:string;mentions?:string[];notifications?:{recipient_id:string;status:string;error?:string;simulated?:boolean}[]}
export interface Task {can_execute?:boolean;id:string;title:string;owner_id:string;status:Status;required:boolean;start_date:string|null;due_date:string|null;original_due_date:string|null;started_at:string|null;completed_at:string|null;points:number|null;work_item_id:string;description:string;input:string;output:string;comments:Comment[];revision:number;[key:string]:unknown}
export interface Node {id:string;name:string;key:string;owner_id:string;collaborator_ids:string[];status:Status;start_date:string|null;due_date:string|null;original_due_date:string|null;started_at:string|null;completed_at:string|null;tasks:Task[];[key:string]:any}
export interface ProjectFile {id:string;name:string;node_id:string;direction:string;version:number|string;uploaded_by:string;created_at:string;size:number;url:string;storage:string;[key:string]:any}
export interface DailyReview {status:string;checks?:Record<string,unknown>|{name?:string;label?:string;value?:unknown}[];source_url?:string}
export interface Quote {id:string;quote_code:string;engineering_code?:string;source_url:string;amount:number|null;fields?:Record<string,unknown>}
export interface DailyReport {id:string;date:string;department:string;case_code:string;person:string;description:string;points:number|null;source_url:string;source_case_code?:string;match_basis?:string;mapping_status?:string;review?:DailyReview;source_actor_ids?:string[]}
export interface Project {source_lifecycle?:SourceLifecycle|null;case_type?:'formal'|'intake';parent_code?:string|null;quotes?:Quote[];sales_id?:string;id:string;code:string;name:string;client:string;pm_id:string;status:Status;priority:string;due_date:string;original_due_date:string;created_at:string;started_at:string;description:string;contract_amount:number|null;estimated_points:number|null;source_url:string;source_kind:string;revision:number;nodes:Node[];files:ProjectFile[];comments:Comment[];daily_reports:DailyReport[];[key:string]:any}
export interface Approval {id:string;project_id:string;type:'change'|'extension';title:string;status:string;reason:string;node_id:string;task_ids:string[];dates:{task_id:string;due_date:string}[];owner_confirmed:boolean;client_confirmed:boolean;lark_status:string;created_by:string;created_at:string;executed_at:string;reference_url:string;attachments:unknown[];history:unknown[]}
export interface Event {id:string;project_id:string;node_id?:string;task_id?:string;actor_id:string;action:string;message:string;created_at:string}
export interface SourceMapping {daily_total?:number;daily_imported:number;daily_unmatched:number;daily_unmatched_missing_reference?:number;daily_unmatched_unresolved_reference?:number;daily_unmatched_ambiguous_reference?:number;confirmations_missing_code?:number;daily_missing_date?:number;daily_conflicting_dates?:number;daily_missing_department?:number;daily_provisional?:number;projects?:number;intakes?:number}
export interface Workspace {freshness?:Freshness;environment?:string;workspace_id?:string;version:number;as_of:string;users:User[];projects:Project[];approvals:Approval[];events:Event[];calendar:{holidays:string[];workdays:string[]};source_status:{status:string;last_sync:string;message:string;mapping?:SourceMapping};[key:string]:any}
export interface Session {access_mode?:string;user:User|null;users:User[];mode:string;auth_configured:boolean;environment?:string;workspace_id?:string}
export interface SourceData {freshness?:Freshness;as_of?:string|null;configured:boolean;last_sync:string;status:string;message:string;tables:unknown[];records:unknown[];mapping?:SourceMapping}
export type View = 'company'|'dashboard'|'projects'|'work'|'schedule'|'approvals'|'sources'|'project'|'admin'|'routines';
export interface Route {view:View;project?:string;node?:string;task?:string;tab?:string;section?:string;completion?:string;focus?:string;comment?:string;approval?:string}

export interface WorkSchedule {id:string;user_id:string;day:string;end_time:string;version:number;active?:boolean;source_url?:string;basis?:string}
export interface CapabilitySkill {id:string;name:string;department?:string;category?:string;level?:string|number;source_url?:string;source_record_id?:string;active?:boolean}
export interface TrainingPlan {id:string;title:string;trainee_id:string;trainer_id:string;planned_date:string;skill_ids:string[];status:'planned'|'submitted'|'recognition_pending'|'approved'|'recognized';version:number;summary?:string;evidence_urls?:string[];remote_status?:string}
export interface LearningStandard {id:string;kind:'survival'|'capability_target'|'assessment';title:string;value:string;effective_from:string;approved_by:string;status:string}

