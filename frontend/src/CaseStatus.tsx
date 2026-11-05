import './CaseStatus.css';
import {caseStatusLabel,sourceStatusPending,type CaseStatusSource} from './stageModel';
export function CaseStatus({project}:{project:CaseStatusSource}){
 return <>{caseStatusLabel(project)}{sourceStatusPending(project)&&<small className="case-source-status">來源狀態待核對</small>}</>;
}
