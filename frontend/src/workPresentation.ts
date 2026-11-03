/** Display only: unknown backend reasons never become user-facing system codes. */
export function plainReason(reason:string|null|undefined):string {
 if(!reason)return '待核對';
 const labels:Record<string,string>={'G-AMT':'合約金額尚未核准顯示',forbidden:'目前沒有檢視權限',unlocated:'尚未找到可檢視的資料',unknown:'資料待核對',header_carries_summary:'摘要由來源表頭帶入，資料待更新',receipt_missing:'缺少來源回條，關係完整性待核對',no_authorized_parent_edge:'找不到可檢視的上層關聯，對應尚未驗證',not_in_authorized_view:'此區段不在目前可檢視的範圍內',no_authorized_edge_target:'尚無可檢視的關聯項目',edge_not_located:'尚未找到可檢視的關聯',missing_parent:'上層關聯尚待核對',pending:'未開始',source_time_unknown:'來源同步時間待核對'};
 return labels[reason] ?? (/[a-z]+_[a-z_]+/i.test(reason)?'來源或作業條件待核對，請聯絡管理者':reason);
}
