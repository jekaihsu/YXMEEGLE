// Single place that turns backend ISO strings into display text. The backend emits offset-aware Asia/Taipei
// stamps; naive stamps mean Taipei too (backend/live_read/status.py timestamp()). Never use browser-local time.
const zone=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Taipei',hourCycle:'h23',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
export const TAIPEI_SUFFIX='(台北時間)';
const pattern=/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?\s*(Z|[+-]\d{2}:?\d{2})?$/i;
export function parseInstant(value?:string|null):number{
 if(!value)return NaN;
 // Parsed by hand: Date.parse treats naive/space-separated stamps as browser-local and accepts nothing consistently across engines.
 const m=pattern.exec(value.trim());
 if(!m)return NaN;
 const [year,month,day,hour,minute,second]=m.slice(1,7).map(x=>Number(x||0));
 if(month<1||month>12||day<1||day>new Date(Date.UTC(year,month,0)).getUTCDate()||hour>23||minute>59||second>59)return NaN;
 let offset=480;
 const zoneText=m[8];
 if(zoneText){
  if(zoneText.toUpperCase()==='Z')offset=0;
  else{const digits=zoneText.replace(':','');const h=Number(digits.slice(1,3)),mm=Number(digits.slice(3,5));if(h>23||mm>59)return NaN;offset=(digits[0]==='-'?-1:1)*(h*60+mm)}
 }
 return Date.UTC(year,month-1,day,hour,minute,second,Number((m[7]||'').slice(0,3).padEnd(3,'0')))-offset*60000;
}
export function taipeiTime(value?:string|null,empty='—'):string{
 if(!value)return empty;
 if(/^\d{4}-\d{2}-\d{2}$/.test(value.trim()))return Number.isFinite(parseInstant(value))?value.trim().replaceAll('-','/'):empty;
 const ms=parseInstant(value);
 if(!Number.isFinite(ms))return empty;
 const p=Object.fromEntries(zone.formatToParts(new Date(ms)).map(x=>[x.type,x.value]));
 return `${p.year}/${p.month}/${p.day} ${p.hour}:${p.minute}:${p.second} ${TAIPEI_SUFFIX}`;
}
export function taipeiDate(value?:string|null,empty='—'):string{const text=taipeiTime(value,'');return text?text.slice(0,10):empty}
