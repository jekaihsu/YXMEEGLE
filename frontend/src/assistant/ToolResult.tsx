import type {ToolCallMessagePartComponent} from '@assistant-ui/react';
import {DataTable} from './elements/DataTable';
import {Chart} from './elements/Chart';
import {isDisplay,type Display} from './elements/types';
export const ToolResult:ToolCallMessagePartComponent=props=>{
 const result:unknown=props.result;
 const displays:Display[]=result&&typeof result==='object'&&'displays' in result&&Array.isArray(result.displays)?result.displays.filter(isDisplay):[];
 return displays.length?<div className="assistant-tool-result">{displays.map((display,index)=>display.kind==='table'?<DataTable key={index} {...display}/>:<Chart key={index} {...display}/>)}</div>:null;
};
export const toolUIs={search_cases:ToolResult,attendance_today:ToolResult,case_progress:ToolResult,case_owners:ToolResult};
