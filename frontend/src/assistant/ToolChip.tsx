import type {ToolCallMessagePartProps} from '@assistant-ui/react';
export function ToolChip({args,result,isError,status}:ToolCallMessagePartProps){
 const label=typeof args.label==='string'?args.label:'查詢資料';
 const stopped=!result&&status.type!=='running';
 return <span className="assistant-tool" data-error={isError||undefined}>{isError?'!':result?'✓':stopped?'·':'◌'} {label}{isError?'未完成':result?'完成':stopped?'已停止':'…'}</span>;
}
