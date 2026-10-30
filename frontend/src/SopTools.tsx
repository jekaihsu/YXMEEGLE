import type {ReactNode} from 'react';
export function SopTools({open,children}:{open:boolean;children:ReactNode}){
 return <details className="pf-secondary st-sop-tools" open={open||undefined}><summary>SOP 匯入、批次與建議（任務清單已併入上方）</summary>{children}</details>;
}
