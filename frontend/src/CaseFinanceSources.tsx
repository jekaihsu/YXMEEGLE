import {amountWithheld} from './appCommon';
import type {Project} from './types';
import {financeSources} from './caseRetainedFacts';
import {taipeiTime} from './taipeiTime';
export function CaseFinanceSources({p}:{p:Project}){
 const {basic,contract,conflict}=financeSources(amountWithheld(p)?{...p,contract_amount:null}:p);
 const amount=(v:number|null)=>v===null?'來源未提供':`NT$${v.toLocaleString('zh-TW')}`;
 return <section aria-label="金額來源核對"><h3>金額來源核對</h3>{conflict&&<p role="status">金額來源不一致 · 待核對，尚未選定權威總額</p>}<dl><dt>基本資料金額</dt><dd>{amount(basic)} · 來源時間 {taipeiTime(p.contract_amount_as_of,'來源未提供')}</dd><dt>合約來源金額</dt><dd>{amount(contract)} · 來源時間 {taipeiTime(p.source_projection?.finance?.as_of??p.source_finance?.as_of,'來源未提供')}</dd></dl><p>各來源時間分別列示；成本、點數與營收不併入合約金額。</p></section>;
}
