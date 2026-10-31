import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const result=await build({stdin:{contents:"export {default as App} from './src/App';export {default as Dashboard} from './src/TokenDashboard';",resolveDir:import.meta.dirname},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.token-dashboard-test.mjs',import.meta.url);await fs.writeFile(path,result.outputFiles[0].text);
let ui;try{ui=await import(path.href)}finally{await fs.unlink(path)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/token_dashboard/',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','FormData','Event','HTMLElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
window.scrollTo=()=>{};globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(resolve=>setTimeout(resolve,15))});
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json'}});
let role='member',requests=[];
globalThis.fetch=(url,init)=>{requests.push({url,init});return Promise.resolve(json({user:{id:'a',role,name:'王'},users:[],mode:'demo',environment:'development',workspace_id:'test'}))};
let root=createRoot(document.getElementById('root'));
await flush(()=>root.render(React.createElement(ui.App)));await flush();
assert.match(document.body.textContent,/403 · 無權查看/);assert.equal(document.querySelector('.app-shell'),null);
assert.equal(document.querySelector('meta[name=robots]').content,'noindex, nofollow');
assert.deepEqual(requests.map(row=>row.url),['/api/session']);assert.equal(location.hash,'');
assert.equal(document.querySelector('header a').getAttribute('href'),'/');
await flush(()=>root.unmount());assert.equal(document.querySelector('meta[name=robots]'),null);
const fixture={range:{from:'2026-10-01',to:'2026-10-31'},totals:{questions:1,input_tokens:1234,output_tokens:50,cost_usd:.02,unpriced_calls:1},by_person:[{actor_id:'a',name:'王小明',questions:1,input_tokens:1234,output_tokens:50,cost_usd:.02,unpriced_calls:2,last_at:'2026-10-31T00:00:00Z'}],by_day:[],by_provider:[{provider:"gpt",questions:1,input_tokens:1234,output_tokens:50,cost_usd:.02,unpriced_calls:3}],people:[{actor_id:'a',name:'王小明'}],recent:[]};
requests=[];globalThis.fetch=(url,init)=>new Promise(resolve=>requests.push({url,init,resolve}));
history.replaceState(null,'','/token_dashboard?from=2026-10-01&to=2026-10-31');root=createRoot(document.getElementById('root'));
await flush(()=>root.render(React.createElement(ui.Dashboard)));
assert.equal(requests.length,1);await flush(()=>requests[0].resolve(json(fixture)));
assert.match(document.body.textContent,/尚無評分/);assert.equal(document.querySelector('.td-reasons'),null);assert.doesNotMatch(document.querySelector('.td-satisfaction').textContent,/%/);
assert.match(document.body.textContent,/未計價 1 次/);assert.match(document.querySelector('.td-person').closest('tbody').textContent,/未計價 2 次/);assert.match(document.querySelector('.td-providers').textContent,/未計價 3 次/);assert.match(document.body.textContent,/1,234/);
await flush(()=>document.querySelector('.td-person').click());assert.equal(new URLSearchParams(location.search).get('actor'),'a');
assert.equal(requests.length,2);const stale=requests[1];
await flush(()=>{const select=document.querySelectorAll('select')[1];select.value='gpt';select.dispatchEvent(new Event('change',{bubbles:true}))});
assert.equal(stale.init.signal.aborted,true,'filter change aborts the actual fetch signal');
await flush(()=>stale.resolve(json({...fixture,totals:{...fixture.totals,questions:99999}})));
assert.doesNotMatch(document.body.textContent,/99,999/);
await flush(()=>requests[2].resolve(json({detail:'no access'},403)));assert.match(document.body.textContent,/403 · 無權查看/);
await flush(()=>{window.history.pushState(null,'','?from=2026-10-01&to=2026-10-31');window.dispatchEvent(new Event('popstate'))});
await flush(()=>requests[3].resolve(json({detail:'offline'},503)));assert.match(document.body.textContent,/用量讀取失敗/);
await flush(()=>[...document.querySelectorAll('button')].find(el=>el.textContent==='重新嘗試').click());
await flush(()=>requests[4].resolve(json({...fixture,totals:{...fixture.totals,questions:0}})));assert.match(document.body.textContent,/這段期間尚無提問/);
const feedbackFixture={...fixture,totals:{...fixture.totals,questions:12,feedback:{up:7,down:3,rated:10,up_rate:.7}},
 by_person:[{...fixture.by_person[0],up:7,down:0},{...fixture.by_person[0],actor_id:'b',name:'陳雅文',up:0,down:3}],
 by_provider:[{...fixture.by_provider[0],provider:'claude',up:7,down:3},{...fixture.by_provider[0],up:0,down:0}],
 by_day:[{day:'2026-10-31',questions:12,input_tokens:1234,output_tokens:50,cost_usd:.02,up:7,down:3}],
 reasons:{wrong:2,incomplete:1,slow:0,other:0},
 recent:[{created_at:'2026-10-31T00:00:00Z',name:'陳雅文',actor_id:'b',provider:'claude',input_tokens:200,output_tokens:30,cost_usd:.01,latency_ms:2000,status:'ok',rating:'down',reason:'wrong'},
 {created_at:'2026-10-30T00:00:00Z',name:'王小明',actor_id:'a',provider:'claude',input_tokens:300,output_tokens:40,cost_usd:.01,latency_ms:1000,status:'ok',rating:'up',reason:null},
 {created_at:'2026-10-29T00:00:00Z',name:'王小明',actor_id:'a',provider:'gpt',input_tokens:100,output_tokens:20,cost_usd:.01,latency_ms:1000,status:'ok'}]};
await flush(()=>{history.pushState(null,'','?from=2026-10-01&to=2026-10-31&rating=down');window.dispatchEvent(new Event('popstate'))});
assert.equal(new URL(requests[5].url,'http://localhost').searchParams.get('rating'),'down');
await flush(()=>requests[5].resolve(json(feedbackFixture)));
assert.match(document.querySelector('.td-satisfaction').textContent,/70.0%.*👍 7 \/ 👎 3.*已評分 10 次/);
assert.match(document.querySelector('.td-providers').textContent,/Claude.*70.0%.*👍 7 \/ 👎 3.*GPT.*尚無評分/s);
assert.deepEqual([...document.querySelectorAll('.td-reasons li')].map(row=>row.textContent),['答錯2 次','不完整1 次','太慢0 次','其他0 次','未填寫0 次']);
assert.equal(document.querySelectorAll('.td-dislike-marker').length,1);
const dailyBar=document.querySelector('rect[aria-label*="3 次倒讚"]');
assert.match(dailyBar.getAttribute('aria-label'),/7 次按讚/);
await flush(()=>dailyBar.focus());
assert.match(document.querySelector('.td-chart-tooltip').textContent,/👍 7 次按讚.*👎 3 次倒讚/);
const dailyTable=document.querySelector('[aria-label="每日用量表，可左右捲動"] table');
assert.deepEqual([...dailyTable.querySelectorAll('th')].map(cell=>cell.textContent),['日期','提問數','👍 按讚','👎 倒讚','輸入 tokens','輸出 tokens','費用 USD']);
assert.deepEqual([...dailyTable.querySelector('tbody tr:last-child').cells].map(cell=>cell.textContent),['2026-10-31','12','7','3','1,234','50','US$0.0200']);
assert.match(document.querySelector('rect[aria-label*="3 次倒讚"]').getAttribute('aria-label'),/12 次提問/);
assert.equal(document.querySelector('span[aria-label="倒讚"]').nextElementSibling.textContent,'答錯');
assert.ok(document.querySelector('span[aria-label="按讚"]'));assert.ok(document.querySelector('span[aria-label="未評分"]'));
const personTable=document.querySelector('.td-person').closest('table');
await flush(()=>[...personTable.querySelectorAll('th button')].find(el=>el.textContent.includes('👎')).click());
assert.equal(personTable.querySelector('tbody tr td').textContent,'陳雅文');
const providerTable=document.querySelector('[aria-label="供應商評分表，可左右捲動"] table');
await flush(()=>[...providerTable.querySelectorAll('th button')].find(el=>el.textContent.includes('👍')).click());
assert.equal(providerTable.querySelector('tbody tr td').textContent,'Claude');
for(const [index,rating] of ['up','none',''].entries()) {
 await flush(()=>{const select=[...document.querySelectorAll('label')].find(el=>el.textContent.startsWith('評分')).querySelector('select');select.value=rating;select.dispatchEvent(new Event('change',{bubbles:true}))});
 assert.equal(new URLSearchParams(location.search).get('rating'),rating||null);
 assert.equal(new URL(requests[6+index].url,'http://localhost').searchParams.get('rating'),rating||null);
 await flush(()=>requests[6+index].resolve(json(feedbackFixture)));
}
await flush(()=>{history.pushState(null,'','?from=2026-10-01&to=2026-10-31&rating=none');window.dispatchEvent(new Event('popstate'))});
await flush(()=>requests[9].resolve(json({...fixture,totals:{...fixture.totals,feedback:{up:0,down:0,rated:0,up_rate:0}}})));
assert.doesNotMatch(document.querySelector('.td-satisfaction').textContent,/%/);
assert.equal(document.querySelectorAll('select')[2].value,'none','popstate restores the rating control');
for(const reasons of [{unspecified:3},undefined]){
 await flush(()=>{history.pushState(null,'',`?from=2026-10-01&to=2026-10-31&rating=${reasons?'up':'down'}`);window.dispatchEvent(new Event('popstate'))});
 await flush(()=>requests.at(-1).resolve(json({...feedbackFixture,reasons})));
 assert.match(document.querySelector('.td-reasons').textContent,/倒讚原因/);
 assert.equal(document.querySelector('.td-reasons li:last-child').textContent,`未填寫3 次`);
}
const countBeforeRange=requests.length;
await flush(()=>{history.pushState(null,'','?from=2025-01-01&to=2026-10-31');window.dispatchEvent(new Event('popstate'))});
assert.match(document.body.textContent,/日期範圍最多 366 天/);assert.equal(requests.length,countBeforeRange,'oversized custom range does not fetch');
await flush(()=>root.unmount());dom.window.close();
assert.doesNotMatch(await fs.readFile(new URL('./src/AppShell.tsx',import.meta.url),'utf8'),/token_dashboard|TokenDashboard/);
const manifest=JSON.parse(await fs.readFile(new URL('./dist/.vite/manifest.json',import.meta.url),'utf8'));
const entry=Object.values(manifest).find(row=>row.name==='TokenDashboard');assert.equal(entry.isDynamicEntry,true);
assert.ok((await fs.stat(new URL('./dist/'+manifest['index.html'].file,import.meta.url))).size<300000,'entry JS stays below 300000 bytes');
const initial=new Set();function visit(key){initial.add(key);for(const child of manifest[key].imports||[])if(!initial.has(child))visit(child)}visit('index.html');assert.ok(![...initial].some(key=>manifest[key]===entry));
console.log('Token dashboard permission, query navigation, stale abort, 403, retry, empty, noindex, hidden navigation, lazy chunk, feedback sorting, reasons and rating navigation passed');
