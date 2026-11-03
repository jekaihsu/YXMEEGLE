export function dispatchGapLabel(code:string):string {
 const labels:Record<string,string>={no_leave_source:'尚無完整請假可用時段來源',invalid_schedule_interval:'缺少有效起訖時間的班表未納入',unresolved_case_links:'案件關聯尚未對應確認單',no_latest_booking_date:'最近派工日期未知'};
 const match=/^no_bookings_after_(\d{4}-\d{2}-\d{2})$/.exec(code);
 return match?`${match[1].replaceAll('-','/')} 之後尚無派工紀錄`:labels[code]||'來源資料待核對';
}
export function jobReasonLabel(reason:string):string {
 return ({blocked_feature:'功能尚未開放'} as Record<string,string>)[reason]||(/[\u3400-\u9fff]/.test(reason)?reason:'工作條件待核對');
}
