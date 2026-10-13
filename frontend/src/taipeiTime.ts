// Single place that turns backend ISO strings into display text. The backend emits offset-aware Asia/Taipei
// stamps; naive stamps mean Taipei too (backend/live_read/status.py timestamp()). Never use browser-local time.
const zone=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Taipei',hourCycle:'h23',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
export const TAIPEI_SUFFIX='(台北時間)';
export function parseInstant(value?:string|null):number{
 if(!value)return NaN;
 // JS Date parsing varies for >3 fractional digits and treats naive date-times as local time.
 const text=value.trim().replace(/(\.\d{3})\d+/,'$1');
 return Date.parse(/T.*(Z|[+-]\d{2}:?\d{2})$/i.test(text)||!text.includes('T')?text:text+'+08:00');
}
export function taipeiTime(value?:string|null,empty='—'):string{
 if(!value)return empty;
 if(/^\d{4}-\d{2}-\d{2}$/.test(value.trim()))return value.trim().replaceAll('-','/');
 const ms=parseInstant(value);
 if(!Number.isFinite(ms))return empty;
 const p=Object.fromEntries(zone.formatToParts(new Date(ms)).map(x=>[x.type,x.value]));
 return `${p.year}/${p.month}/${p.day} ${p.hour}:${p.minute}:${p.second} ${TAIPEI_SUFFIX}`;
}
export function taipeiDate(value?:string|null,empty='—'):string{const text=taipeiTime(value,'');return text?text.slice(0,10):empty}
