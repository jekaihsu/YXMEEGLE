export type Cell=string|number|null;
export type TableDisplay={kind:'table';title:string;caption?:string;columns:{key:string;label:string}[];rows:Record<string,Cell>[];rowKey?:string;truncated?:boolean;note?:string};
export type ChartDisplay={kind:'chart';title:string;variant:'bars';unit?:string;headline?:{label:string;value:string};points:{label:string;value:number}[]};
export type Display=TableDisplay|ChartDisplay;
const record=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value);
const optionalText=(value:unknown)=>value===undefined||typeof value==='string';
export function isDisplay(value:unknown):value is Display {
 if(!record(value)||typeof value.title!=='string')return false;
 if(value.kind==='table')return Array.isArray(value.columns)&&value.columns.length>0&&value.columns.length<=8
  &&value.columns.every(c=>record(c)&&typeof c.key==='string'&&typeof c.label==='string')
  &&new Set(value.columns.map(c=>c.key)).size===value.columns.length
  &&Array.isArray(value.rows)&&value.rows.length<=50&&value.rows.every(row=>record(row)&&Object.values(row).every(v=>v===null||typeof v==='string'||typeof v==='number'&&Number.isFinite(v)))
  &&optionalText(value.caption)&&optionalText(value.rowKey)&&optionalText(value.note)&&(value.truncated===undefined||typeof value.truncated==='boolean');
 if(value.kind==='chart')return value.variant==='bars'&&optionalText(value.unit)
  &&(value.headline===undefined||record(value.headline)&&typeof value.headline.label==='string'&&typeof value.headline.value==='string')
  &&Array.isArray(value.points)&&value.points.length<=12&&value.points.every(p=>record(p)&&typeof p.label==='string'&&typeof p.value==='number'&&Number.isFinite(p.value));
 return false;
}
