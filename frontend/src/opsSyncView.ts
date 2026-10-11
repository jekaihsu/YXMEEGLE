// Wording for the local/mock ops-sync delivery states. Pure so it can be tested without a browser.
export type OpsState='waiting_approval'|'pending'|'confirmed'|'conflict'|'failed'|'unknown';
export type OpsValue={kind:'set'|'clear'|'unknown';value:string|null};
export const MOCK_NOTICE='本機模擬（mock）垂直切片：未連線 Lark，不會讀寫任何 Lark 資料；以下狀態僅代表本機模擬的處理結果。';
export const STATE_ORDER:OpsState[]=['waiting_approval','pending','confirmed','conflict','failed','unknown'];
export const STATES:Record<OpsState,{label:string;tone?:'positive'|'warning'|'critical'|'accent';detail:string}>={
 waiting_approval:{label:'等待核准',tone:'warning',detail:'已記錄申請，尚未送出；核准前不會寫入，生效值維持不變。'},
 pending:{label:'排隊處理中',tone:'accent',detail:'申請已被接受，等待模擬寫入與讀回核實；此時尚未成功。'},
 confirmed:{label:'本機模擬已確認',tone:'positive',detail:'僅代表本機模擬讀回與預期一致，並非 Lark 同步。'},
 conflict:{label:'衝突待處理',tone:'critical',detail:'送出時的基準值與目前值不同，未寫入。請核對後明確選擇處理方式。'},
 failed:{label:'失敗',tone:'critical',detail:'確定未寫入。如仍需變更，請以新的申請重新送出。'},
 unknown:{label:'結果未確認（核對中）',tone:'warning',detail:'無法確認是否已寫入，系統正在讀回核對；核對完成前不視為成功，也不視為失敗。'},
};
const REASONS:Record<string,string>={awaiting_approval:'等待核准',baseline_changed:'基準值已被他人更動',cas_mismatch:'寫入時發現欄位已被他人更動',timeout:'模擬連線逾時',permission_denied:'沒有權限',
 schema_binding_mismatch:'欄位綁定版本不符',retry_exhausted:'重試次數已用完',approval_missing:'缺少核准',approval_not_consumed:'核准尚未生效或不存在',approval_mismatch:'核准內容與申請不符',approval_already_bound:'此核准已用於另一筆申請',approval_not_bound:'核准尚未綁定此申請',withdrawn:'已撤回',resolved_keep_current:'已決定保留目前值',
 malformed_response:'回應內容不完整',partial_read:'讀回內容不完整',proven_noncommit_retry:'確認未寫入，已重新排隊'};
export const reasonText=(code?:string|null)=>code?(REASONS[code]||`原因代碼：${code}`):'';
export const valueText=(v:OpsValue)=>v.kind==='set'?String(v.value):v.kind==='clear'?'（空白）':'無法讀取';
export const FIELDS:Record<string,string>={'case.pm':'案件 PM','case.deadline':'案件期限','node.responsible':'節點負責人','node.deadline':'節點期限'};
