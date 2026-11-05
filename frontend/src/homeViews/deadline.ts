import {parseInstant,taipeiDate,taipeiTime} from '../taipeiTime';
/** Calendar days in Taipei, using the date frozen by Home at page open. */
export function overdueDays(deadline:string|null|undefined,today:string,completed=false):number|null{
 if(!deadline||completed||!Number.isFinite(parseInstant(deadline)))return null;
 const due=parseInstant(taipeiDate(deadline).replaceAll('/','-')),open=parseInstant(today);
 if(!Number.isFinite(due)||!Number.isFinite(open))return null;
 const days=Math.floor((open-due)/86400000);return days>0?days:null;
}
export function dataTime(value:string|null|undefined):string{return taipeiTime(value,'尚未取得')}
