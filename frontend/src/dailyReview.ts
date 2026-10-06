// The API enum from backend/v4_sources.daily_review, preserved end-to-end. Anything else is unverified.
export const DAILY_REVIEW_LABELS:Record<string,string>={approved:'原日報已核准',returned:'原日報已退回',pending:'原日報待檢核',unverified:'原日報檢核待查證'};
export function dailyReviewLabel(review?:{status?:unknown}|null):string{
 const status=review?.status;
 return typeof status==='string'&&Object.prototype.hasOwnProperty.call(DAILY_REVIEW_LABELS,status)?DAILY_REVIEW_LABELS[status]:DAILY_REVIEW_LABELS.unverified;
}
