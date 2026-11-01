import type {ReactNode} from 'react';
export function SopTools({open,children}:{open:boolean;children:ReactNode}){
 return <details className="pf-secondary st-sop-tools" open={open||undefined}><summary>SOP 匯入與建議</summary>{children}</details>;
}
