import {taipeiTime} from '../taipeiTime';

/** Saved-answer provenance only; source timestamps are not part of the history contract. */
export function SavedAnswerDate({at}:{at?:string|null}) {
 const label=taipeiTime(at,'回答時間未提供');
 return <p className="assistant-saved-date" role="note"><strong>歷史回答</strong> · 回答時間：{label} · 來源時間未提供</p>;
}
