import {ArrowUpRight} from 'lucide-react';
import {Row} from './design';

/** The same business counts appear in both overview pages, with their existing navigation. */
export function CaseSummary({formal,intakes,index}:{formal:number;intakes:number;index?:{selected:string;select:(value:string)=>void}}){
 if(!index)return <><Row href="#view=projects&tab=formal" label="正式案件" detail="依工程確認單建立" value={formal}/><Row href="#view=projects&tab=intake" label="待確認接案" detail="尚未列入正式案件" value={intakes}/></>;
 return <div className="portfolio-index"><button className={index.selected==='formal'?'selected':''} onClick={()=>index.select('formal')}><span>正式案件<small>已確認的工程案件</small></span><strong>{formal}</strong><ArrowUpRight size={20}/></button><button className={index.selected==='intake'?'selected':''} onClick={()=>index.select('intake')}><span>待確認接案<small>報價與尚待確認資料</small></span><strong>{intakes}</strong><ArrowUpRight size={20}/></button></div>;
}
