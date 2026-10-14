// Task rows as imported from 合約填報工項 (對應營業額 has 4 decimals); no private source data.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const k of ['window','document','HTMLElement','location','history','sessionStorage','localStorage'])try{globalThis[k]=dom.window[k]}catch{}
const React=await import('react');
const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {TaskTable,points} from './src/appCommon';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.task-points-bundle.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let ui;try{ui=await import(path.href)}finally{await fs.unlink(path)}
globalThis.IS_REACT_ACT_ENVIRONMENT=true;

assert.equal(ui.points(0.125),'0.125');
assert.equal(ui.points(0.0025),'0.0025');
assert.equal(ui.points(1.6667),'1.6667');
assert.equal(ui.points(4.625),'4.625');
assert.equal(ui.points(0),'0');
assert.equal(ui.points(null),'—');

const task=(id,title,points,extra={})=>({id,title,owner_id:'',status:'pending',required:true,revision:1,start_date:null,due_date:null,points,...extra});
const rows=[
 task('t1','點誌記(三支距)',1.57),
 task('t2','服務建議書(有公版)',0.0025),
 task('t3','地形檢查',0.125,{}),
 task('t4','水準計算',4.625,{}),
 task('t5','JSA 範本任務',null),
].map(t=>({p:{id:'P',code:'C115264'},n:{key:'control',name:'控制'},t}));
const c={w:{users:[],as_of:'2026-10-14'},go:()=>{},s:{user:null}};
const root=createRoot(document.getElementById('root'));
await React.act(async()=>root.render(React.createElement(ui.TaskTable,{rows,c,showProject:false,showOwner:false})));
const cells=Object.fromEntries([...document.querySelectorAll('tbody tr')].map(tr=>[tr.querySelector('.task-title button').textContent,{points:tr.querySelector('.col-points').textContent,note:tr.querySelector('.task-title small')?.textContent??null}]));
assert.deepEqual(cells,{
 '點誌記(三支距)':{points:'1.57 點',note:null},
 '服務建議書(有公版)':{points:'0.0025 點',note:null},
 '地形檢查':{points:'0.125 點',note:null},
 '水準計算':{points:'4.625 點',note:null},
 'JSA 範本任務':{points:'— 點',note:null},
});
await React.act(async()=>root.unmount());
console.log('Task points keep source precision');
