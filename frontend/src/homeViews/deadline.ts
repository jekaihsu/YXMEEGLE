/** Calendar days in Taipei, using the date frozen by Home at page open. */
export function overdueDays(deadline:string|null|undefined,today:string,completed=false):number|null{
 if(!deadline||completed||!Number.isFinite(Date.parse(deadline)))return null;
 const day=/^\d{4}-\d{2}-\d{2}$/.test(deadline)?deadline:new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(deadline));
 const due=Date.parse(`${day}T00:00:00Z`),open=Date.parse(`${today}T00:00:00Z`);
 if(!Number.isFinite(due)||!Number.isFinite(open))return null;
 const days=Math.floor((open-due)/86400000);return days>0?days:null;
}
export function dataTime(value:string|null|undefined):string{
 if(!value||!Number.isFinite(Date.parse(value)))return '尚未取得';
 return new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(value))+'（臺北時間）';
}
