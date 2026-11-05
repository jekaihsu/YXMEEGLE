// Local fictional portfolio CPU probe: node benchmark-projects-list.mjs
import {build} from 'esbuild';
import {performance} from 'node:perf_hooks';
const {outputFiles:[bundle]}=await build({stdin:{contents:"export {filterRows,caseRow,DEFAULT_FILTERS} from './src/projectsListModel';",resolveDir:process.cwd(),loader:'ts'},bundle:true,write:false,platform:'node',format:'esm'});
const {filterRows,caseRow,DEFAULT_FILTERS}=await import('data:text/javascript;base64,'+Buffer.from(bundle.text).toString('base64'));
const users=Array.from({length:65},(_,i)=>({id:`u${i}`,name:`員工 ${i}`}));
const keys=['sales','pm','confirmation','field','control','mapping','report','pricing','settlement'];
const projects=Array.from({length:319},(_,i)=>({id:`p${i}`,code:`C${115000+i}`,name:`案件 ${i}`,client:`客戶 ${i%40}`,pm_id:`u${i%65}`,status:'in_progress',due_date:`2026-${10+i%3}-${String(1+i%28).padStart(2,'0')}`,overdue_tasks:i%3,portfolio_nodes:keys.map((key,j)=>({key,status:j<i%9?'completed':'pending',owner_id:`u${(i+j)%65}`,collaborator_ids:[]}))}));
const samples=[];
for(let run=0;run<12;run++){
 const start=performance.now();
 const rows=projects.map(p=>caseRow(p,users,'u3','2026-10-25'));
 const modeled=performance.now();
 const result=filterRows(rows,DEFAULT_FILTERS,'2026-10-25');
 samples.push({model_ms:modeled-start,filter_sort_ms:performance.now()-modeled,total:result.length});
}
const warm=samples.slice(2),median=key=>warm.map(row=>row[key]).sort((a,b)=>a-b)[Math.floor(warm.length/2)];
console.log(JSON.stringify({fixture_projects:319,model_median_ms:median('model_ms'),filter_sort_median_ms:median('filter_sort_ms'),samples}));
