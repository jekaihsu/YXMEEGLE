import assert from 'node:assert/strict';
import {test,afterEach} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','Element','HTMLElement','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement','navigator','DOMException'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.getComputedStyle=dom.window.getComputedStyle;globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.IS_REACT_ACT_ENVIRONMENT=true;
HTMLElement.prototype.getClientRects=function(){return [{width:40,height:40}]};
const React=await import('react'),{act}=React,{createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {QuoteCreateSheet} from './src/QuoteCreateSheet';export {Quotes} from './src/Quotes';",resolveDir:import.meta.dirname},bundle:true,write:false,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.quote-ui-test.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);let m;try{m=await import(path.href)}finally{await fs.unlink(path)}
const x=JSON.parse(await fs.readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8'));
const reply=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
const tick=()=>new Promise(r=>setTimeout(r,10));let root;
afterEach(async()=>{if(root)await act(async()=>root.unmount());root=null;document.body.innerHTML='<div id="root"></div>'});
const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent===text);
const click=async el=>{assert.ok(el);assert.equal(el.disabled,false);await act(async()=>{el.click();await tick()})};
const type=async(el,value)=>act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));await tick()});
async function sheet(fetcher,extra={}){globalThis.fetch=fetcher;root=createRoot(document.getElementById('root'));await act(async()=>{root.render(React.createElement(m.QuoteCreateSheet,{users:[],canImport:true,onClose(){},onCreated(){},onOpen(){},...extra}));await tick()});}
test('ambiguous creation recovers and retries the exact request with explicit unassigned PM and default SOP',async()=>{const calls=[];let creates=0;let receipt;await sheet(async(url,init={})=>{const body=init.body?JSON.parse(init.body):null;calls.push({url,body});if(url.endsWith('/preview'))return reply(x.quote_preview);if(url.includes('/requests/'))return reply({code:'run_not_found'},404);if(url==='/api/quotes'){creates++;return creates===1?reply({code:'unavailable'},500):reply(x.quote_create)}throw Error(url)},{onOpen:ref=>receipt=ref});await type(document.querySelector('input[required]'),'新案件');await click(button('預覽'));assert.deepEqual(calls[0].body,{name:'新案件',pm_id:null,client:'',description:'',official_quote_no:'',import_tasks:true});await click(button('確認建立'));assert.match(document.querySelector('[role=alert]').textContent,/尚未建立/);await click(button('重試建立'));const attempts=calls.filter(c=>c.url==='/api/quotes');assert.equal(attempts.length,2);assert.deepEqual(attempts[0].body,attempts[1].body);assert.equal(calls.find(c=>c.url.includes('/requests/')).url,`/api/quotes/requests/${attempts[0].body.request_id}`);await click(button('開啟案件'));assert.equal(receipt,x.quote_create.local_reference)});
test('number conflict stays inline and creation without SOP sends no import selection',async()=>{let body;await sheet(async(url,init)=>{body=JSON.parse(init.body);return reply({code:'quote_number_taken'},409)},{canImport:false});assert.equal(document.querySelectorAll('input[type=radio]').length,1);await type(document.querySelector('input[required]'),'新案件');await type(document.querySelector('input[aria-label="報價編號"]'),'115600');await click(button('預覽'));assert.equal(body.import_tasks,false);assert.equal('node_keys' in body,false);assert.equal(document.querySelector('input[aria-invalid=true]').getAttribute('aria-describedby'),'quote-number-error');assert.equal(document.getElementById('quote-number-error').textContent,'報價編號已使用')});
test('create entry is absent without both flag and capability',async()=>{globalThis.fetch=async()=>reply({total:0,items:[]});const c={s:{user:{capabilities:['create_local_case']}},w:{users:[]},route:{view:'quotes'},go(){}};root=createRoot(document.getElementById('root'));await act(async()=>{root.render(React.createElement(m.Quotes,{c}));await tick()});assert.equal(button('建立報價'),undefined);await act(async()=>{root.render(React.createElement(m.Quotes,{c:{...c,s:{features:{local_case_creation:true},user:{capabilities:[]}}}}));await tick()});assert.equal(button('建立報價'),undefined);await act(async()=>{root.render(React.createElement(m.Quotes,{c:{...c,s:{features:{local_case_creation:true},user:{capabilities:['create_local_case']}}}}));await tick()});assert.ok(button('建立報價'))});
test('register reads all API pages before sorting, paginates and resets the page after search',async()=>{const offsets=[];const rows=Array.from({length:101},(_,i)=>({...x.quotes.items[0],quote_no:String(115000+i),name:`案件${i}`,contract_amount:i}));globalThis.fetch=async url=>{const offset=Number(new URL(url,'http://localhost').searchParams.get('offset'));offsets.push(offset);return reply({total:rows.length,items:rows.slice(offset,offset+100)})};root=createRoot(document.getElementById('root'));const c={s:{user:{}},w:{users:[]},route:{view:'quotes'},go(){}};await act(async()=>{root.render(React.createElement(m.Quotes,{c}));await tick()});assert.deepEqual(offsets,[0,100]);assert.equal(document.querySelectorAll('tbody tr').length,25);assert.match(document.querySelector('tbody tr').textContent,/115100/);await click(button('下一頁'));assert.match(document.querySelector('tbody tr').textContent,/115075/);await type(document.querySelector('[aria-label="搜尋報價"]'),'案件100');assert.equal(document.querySelectorAll('tbody tr').length,1);assert.match(document.querySelector('tbody tr').textContent,/115100/);assert.equal(button('上一頁').disabled,true)});

async function registerDetail(quote,allowed=true) {
 const calls=[];let imported=false;
 globalThis.fetch=async url=>{calls.push(url);if(url.endsWith('/sop-import/preview'))return reply(x.preview);if(url.endsWith('/sop-import/apply')){imported=true;return reply(x.apply)}if(url.includes('/sop-assignees'))return reply(x.sop_assignees);if(url.includes('/sop-tasks'))return reply({...x.sop_tasks,allowed_actions:{...x.sop_tasks.allowed_actions,import:allowed}});if(url==='/api/sop-templates')return reply(x.templates);if(url.startsWith('/api/quotes?'))return reply({total:1,items:[quote]});if(url===`/api/quotes/${quote.quote_no}`)return reply({...quote,sop_counts:imported?{done:0,total:1}:quote.sop_counts,facts:{},records:[]});throw Error(url)};
 root=createRoot(document.getElementById('root'));
 const destinations=[];
 const c={s:{workspace_id:`quote-${quote.quote_no}-${allowed}`,features:{sop_task_writes:true},user:{capabilities:['sop_task_import']}},w:{users:[]},route:{view:'quotes'},go:route=>destinations.push(route)};
 await act(async()=>{root.render(React.createElement(m.Quotes,{c}));await tick()});
 assert.deepEqual([...document.querySelectorAll('thead th')].map(th=>th.textContent.replace(/ [↑↓]/,'')),['報價編號','案件名稱','業主','合約金額','階段','負責人']);
 assert.equal(document.querySelectorAll('.quote-stage-filter option').length,12,'all stage choices remain available');
 await click(button(quote.quote_no));
 for(const label of ['工程編號','報價日期','報價期限','PM','SOP 進度'])assert.ok(document.querySelector('[role=dialog]').textContent.includes(label),`${label} retained in detail`);
 return {calls,destinations};
}
test('source quote starts SOP at 報價 with all nodes and opens its canonical case',async()=>{
 const quote={...x.quotes.items[0],quote_no:'115701',sop_counts:null};
 const {destinations}=await registerDetail(quote);
 await click(button('開始 SOP'));
 const sheet=[...document.querySelectorAll('[role=dialog]')].at(-1);
 assert.match(sheet.textContent,/從 報價 開始/);
 assert.equal(sheet.querySelectorAll('.sop-nodes [aria-pressed=true]').length,9);
 await click([...sheet.querySelectorAll('button')].find(b=>b.textContent==='取消'));
 await click(button('開啟流程'));
 assert.deepEqual(destinations,[{view:'project',project:quote.project_id,tab:'flow'}]);
});
test('no-case quote has plain admission label and makes no case or import request',async()=>{
 const {calls}=await registerDetail(x.quote_without_case);
 assert.equal(document.querySelector('tbody .col-sop'),null,'SOP admission belongs in detail');
 assert.match(document.querySelector('[role=dialog]').textContent,/未納入案件/);
 assert.equal(Boolean(button('開始 SOP')),false);
 assert.equal(button('開啟流程'),undefined);
 assert.equal(calls.some(url=>url.includes('/api/projects/')),false);
});
test('start action follows server import authority',async()=>{
 await registerDetail({...x.quotes.items[0],quote_no:'115703',sop_counts:null},false);
 assert.equal(Boolean(button('開始 SOP')),false);
 assert.ok(button('開啟流程'));
});
test('quote with imported tasks offers open without a second start action',async()=>{
 await registerDetail({...x.quotes.items[0],quote_no:'115704'});
 assert.ok(button('開啟流程'));
 assert.equal(Boolean(button('開始 SOP')),false);
});

test('completed import refreshes the open detail and removes the start action',async()=>{
 await registerDetail({...x.quotes.items[0],quote_no:'115705',sop_counts:null});
 await click(button('開始 SOP'));
 await click(button('下一步'));
 await click(button('下一步'));
 await click(button('確認匯入'));
 await click(button('關閉'));
 assert.equal(Boolean(button('開始 SOP')),false);
 assert.match(document.querySelector('[role=dialog]').textContent,/0\/1/);
});

test('stage dropdown filters rows and can restore all stages',async()=>{
 const base=x.quotes.items[0];
 globalThis.fetch=async()=>reply({total:2,items:[{...base,quote_no:'115801',stage:'inquiry'},{...base,quote_no:'115802',stage:'quoted'}]});
 root=createRoot(document.getElementById('root'));
 await act(async()=>{root.render(React.createElement(m.Quotes,{c:{s:{user:{}},w:{users:[]},route:{view:'quotes'},go(){}}}));await tick()});
 const select=document.querySelector('.quote-stage-filter select');
 const change=async value=>act(async()=>{Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(select,value);select.dispatchEvent(new Event('change',{bubbles:true}));await tick()});
 assert.equal(document.querySelectorAll('tbody tr').length,2);
 await change('quoted');assert.equal(document.querySelectorAll('tbody tr').length,1);assert.match(document.querySelector('tbody').textContent,/115802/);
 await change('');assert.equal(document.querySelectorAll('tbody tr').length,2);
});
