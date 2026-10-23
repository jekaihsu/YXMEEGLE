import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {JSDOM} from 'jsdom';
import {homeReportFixture} from './home-reports-fixture.mjs';
const bundle=await build({stdin:{contents:"export {UnifiedHome} from './src/UnifiedHome';export {ReportCard,CopyReportSummary} from './src/homeViews/ReportCard';export {copySummary} from './src/homeReportInsights';export {invalidateSessionEpoch} from './src/api';export {DEFAULT_LAYOUT,homeLayoutKey} from './src/homeLayout';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.home-report-cards-test.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);let m;try{m=await import(file.href)}finally{await fs.unlink(file)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=dashboard',pretendToBeVisual:true});
for(const key of ['window','document','location','history','Event','HTMLElement','localStorage','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const fixture=homeReportFixture();let status=200,report=fixture,calls=0,held;
const c={go(){},refresh:async()=>{},reloadVersion:0,s:{mode:'lark',workspace_id:'reports-test',user:{id:'pm',role:'pm'},features:{node_assignment:true}},w:{version:1,scope:'shell',environment:'test',projects:[],users:[]}};
globalThis.fetch=async(url,init)=>{
 if(String(url)==='/api/reports/home'){calls++;if(held)await held.promise;return new Response(JSON.stringify(status===200?report:{}),{status})}
 if(String(url).includes('company-dashboard'))return new Response(JSON.stringify({as_of:'2026-10-12',source:{status:'ready'},complete:true,totals:{execution_status_counts:{},tasks_overdue:0,pending_local_reviews:0,pending_native_reviews:0},groups:[],cases:[]}));
 if(String(url).includes('attendance'))return new Response(JSON.stringify({status:'not-connected'}));
 const q=new URL(url,'http://localhost').searchParams;
 return new Response(JSON.stringify({panel:q.get('panel'),scope:q.get('scope'),readState:'ready',snapshot_version:'test',as_of:null,freshness:{status:'fresh',last_success_at:null,refreshing:false},counts:{node_assignments:0,tasks:0,local_workflow:0,complete:true},items:[],next_cursor:null,has_more:false,complete:true,total_count:0,manager_view_available:true}));
};
const root=createRoot(document.getElementById('root'));
const render=async(context=c)=>{await act(async()=>{root.render(React.createElement(React.StrictMode,null,React.createElement(m.UnifiedHome,{c:context})));await new Promise(resolve=>setTimeout(resolve,10))});await act(async()=>new Promise(resolve=>setTimeout(resolve,10)))};
const fresh=async(context=c)=>{await act(async()=>root.render(null));await render(context)};
let checks=0;const equal=(a,b)=>{assert.deepEqual(a,b);checks++};
const cardIds=()=>[...document.querySelectorAll('[data-home-card]')].map(el=>el.dataset.homeCard);
const reportIds=['attention','qualityTrend','qualityGroups','funnel','receivables','achievement','instruments','vehicles'];
try{
 await render();equal(document.querySelector('[data-home-section="people"]'),null);equal(calls,1);equal(reportIds.every(id=>cardIds().includes(id)),true);
 equal([...document.querySelectorAll('[data-home-section]')].map(el=>el.dataset.homeSection),['todo','quality','business','progress','resources','shortcuts']);
 equal(document.querySelector('[data-home-card="qualityTrend"] .home-report-sentence').textContent,'報告週 11.5%，較前一週 +2.1pt。47 筆已退回中，測量二組 佔 38%');
 equal(document.querySelectorAll('.home-report-attention a').length,4);
 equal(document.querySelector('[data-home-card="qualityGroups"] .home-bar i').style.width,'100%');
 equal(document.querySelectorAll('.home-report-attention [data-tone="warning"]').length,1);
 let copied;Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{copied=text}},configurable:true});
 const button=text=>[...document.querySelectorAll('button')].find(el=>el.textContent.trim()===text);
 await act(async()=>button('複製週報摘要').click());equal(copied,m.copySummary(fixture));equal(document.body.textContent.includes('已複製週報摘要'),true);
 Object.defineProperty(navigator,'clipboard',{value:undefined,configurable:true});await act(async()=>button('複製週報摘要').click());equal(document.querySelector('textarea').value,m.copySummary(fixture));equal(document.querySelector('textarea').readOnly,true);
 report={...fixture,meta:{...fixture.meta,stale:true}};await render({...c,reloadVersion:1});equal(document.querySelectorAll('.home-section>header small').length,5);
 report={...fixture,meta:{...fixture.meta,refresh_error:true}};await render({...c,reloadVersion:2});equal(document.querySelectorAll('.home-section>header small').length,5);
 status=500;await render({...c,reloadVersion:3});equal(document.body.textContent.includes('週報資料暫時無法更新；已保留上次資料。'),true);equal(document.querySelector('[data-home-card="qualityTrend"] .home-report-sentence').textContent,'報告週 11.5%，較前一週 +2.1pt。47 筆已退回中，測量二組 佔 38%');
 status=403;await render({...c,reloadVersion:4});equal(reportIds.some(id=>cardIds().includes(id)),false);await act(async()=>button('自訂首頁').click());equal([...document.querySelectorAll('#home-customize strong')].some(el=>el.textContent==='週報待追蹤'),false);const before=calls;
 await render({...c,reloadVersion:5});await fresh({...c,reloadVersion:6});equal(calls,before);
 status=200;m.invalidateSessionEpoch();await fresh();equal(calls,before+1);equal(cardIds().includes('attention'),true);
 await fresh({...c,s:{...c.s,user:{id:'manager',role:'manager'}}});equal(cardIds().includes('qualityTrend'),true);
 const beforeMember=calls;await fresh({...c,s:{...c.s,user:{id:'business-member',role:'member',department:'業務'}}});equal(calls,beforeMember);equal(reportIds.some(id=>cardIds().includes(id)),false);
 await act(async()=>button('自訂首頁').click());equal([...document.querySelectorAll('#home-customize strong')].some(el=>el.textContent==='週報待追蹤'),false);
 const key=m.homeLayoutKey(c.s.workspace_id,'assign-pm','pm','lark');localStorage.setItem(key,JSON.stringify({version:2,view:'assign',layouts:{}}));await fresh({...c,s:{...c.s,user:{id:'assign-pm',role:'pm'}}});equal(calls,beforeMember);equal(reportIds.some(id=>cardIds().includes(id)),false);
 const hiddenKey=m.homeLayoutKey(c.s.workspace_id,'hidden-pm','pm','lark');localStorage.setItem(hiddenKey,JSON.stringify({version:2,view:'company',layouts:{company:{...m.DEFAULT_LAYOUT.company,hidden:reportIds}}}));await fresh({...c,s:{...c.s,user:{id:'hidden-pm',role:'pm'}}});equal(calls,beforeMember);await act(async()=>button('自訂首頁').click());equal([...document.querySelectorAll('#home-customize strong')].filter(el=>['週報待追蹤','儀器','車輛','預排達成率'].includes(el.textContent)).map(el=>el.textContent),['週報待追蹤','預排達成率','儀器','車輛']);
 status=404;await fresh({...c,s:{...c.s,user:{id:'404-pm',role:'pm'}}});const before404=calls;await render({...c,reloadVersion:1,s:{...c.s,user:{id:'404-pm',role:'pm'}}});equal(calls,before404);equal(reportIds.some(id=>cardIds().includes(id)),false);
 let release;status=200;held={promise:new Promise(resolve=>{release=resolve})};await fresh({...c,s:{...c.s,user:{id:'slow-pm',role:'pm'}}});await render({...c,s:{...c.s,user:{id:'new-member',role:'member'}}});held=undefined;await act(async()=>release());equal(reportIds.some(id=>cardIds().includes(id)),false);
 const withGap={...fixture,quality:{...fixture.quality,trend:[{week:'1',error_rate:.1,total:1,passed:1,returned:0},{week:'2',error_rate:null,total:1,passed:1,returned:0},{week:'3',error_rate:.2,total:1,passed:1,returned:0}]}};
 await act(async()=>root.render(React.createElement(m.ReportCard,{id:'qualityTrend',read:{data:withGap,loading:false,error:'',unavailable:false}})));equal(document.querySelectorAll('.home-report-line').length,0);equal(document.querySelectorAll('circle').length,1);
 const gaps=['第一項缺口','第二項缺口','第三項缺口'].map((message,i)=>({id:'sales-'+i,severity:'warn',message}));
 for(const [cardGaps,expected] of [[[],['僅涵蓋週報已納入的案件與金額。']],[[gaps[0]],['第一項缺口']],[gaps,['第一項缺口','另有 2 項資料缺口，詳見 PM 週報']]]){
  const data={...fixture,sales:{...fixture.sales,by_status:[],gaps:cardGaps}};
  await act(async()=>root.render(React.createElement(m.ReportCard,{id:'funnel',read:{data,loading:false,error:'',unavailable:false}})));
  equal([...document.querySelectorAll('.home-source-note')].map(el=>el.textContent),expected);
 }
 const data={...fixture,assets:{instrument:{...fixture.assets.instrument,gaps:[{id:'instrument-category',severity:'warn',message:'儀器專屬缺口'}]},vehicle:{...fixture.assets.vehicle,gaps:[]}}};
 await act(async()=>root.render(React.createElement(m.ReportCard,{id:'vehicles',read:{data,loading:false,error:'',unavailable:false}})));
 equal([...document.querySelectorAll('.home-source-note')].map(el=>el.textContent),['依週報資源狀態統計。']);
 console.log(`Home report cards: ${checks} rendered access, request, stale, cancellation, trend-gap and clipboard checks passed.`);
}finally{await act(async()=>root.unmount())}
