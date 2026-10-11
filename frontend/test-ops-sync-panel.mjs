// Ops-sync panel: distinct wording for the six delivery states, explicit conflict resolution, hidden when the flag is off (404).
// PLAYWRIGHT_MODULE and CHROME_EXECUTABLE may select existing installations.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {createServer} from 'node:http';
import {build} from 'esbuild';
import {workspace} from './session-epoch-fixture.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const viewCode=(await build({entryPoints:['src/opsSyncView.ts'],bundle:true,write:false,format:'esm',platform:'node'})).outputFiles[0].text;
const {STATES,STATE_ORDER,MOCK_NOTICE,valueText}=await import('data:text/javascript;base64,'+Buffer.from(viewCode).toString('base64'));
const bundle=await build({entryPoints:['src/main.tsx'],bundle:true,write:false,format:'iife',platform:'browser',jsx:'automatic',loader:{'.css':'empty'},define:{'process.env.NODE_ENV':'"development"'}});

// -- wording contract: six distinct labels; nothing claims live Lark sync; only confirmed is positive ----------------
assert.equal(new Set(STATE_ORDER.map(s=>STATES[s].label)).size,6);
assert.equal(new Set(STATE_ORDER.map(s=>STATES[s].detail)).size,6);
const all=[MOCK_NOTICE,...STATE_ORDER.flatMap(s=>[STATES[s].label,STATES[s].detail])].join('\n');
assert.doesNotMatch(all,/已同步|已儲存至 Lark|已寫入 Lark|同步成功|儲存成功/);
assert.match(MOCK_NOTICE,/本機模擬/);assert.match(MOCK_NOTICE,/未連線 Lark/);
assert.deepEqual(STATE_ORDER.filter(s=>STATES[s].tone==='positive'),['confirmed']);
assert.equal(valueText({kind:'clear',value:null}),'（空白）');assert.equal(valueText({kind:'unknown',value:null}),'無法讀取');

const set=v=>({kind:'set',value:v}),clear={kind:'clear',value:null};
const cmd=(id,state,extra={})=>({command_id:id,entity_id:'case:p1',field_id:'case.pm',state,reason:null,actor:'u-pm',expected:clear,expected_revision:0,intended:set('ou_test_pm_2'),attempts:0,reconcile:null,...extra});
let on=true,statusBody,posts=[],stale409=false;
const fixture=()=>({notice:MOCK_NOTICE,live:false,commands:[
 cmd('c-wait','waiting_approval',{field_id:'case.deadline',reason:'awaiting_approval',intended:set('2026-10-20')}),
 cmd('c-pend','pending'),cmd('c-ok','confirmed',{attempts:1}),
 cmd('c-conf','conflict',{reason:'baseline_changed'}),cmd('c-fail','failed',{reason:'permission_denied'}),
 cmd('c-unk','unknown',{reason:'timeout',attempts:1,reconcile:{phase:'pending',reads:0,blocker:'timeout'}})],
 conflicts:[{conflict_id:'conflict:c-conf',command_id:'c-conf',entity_id:'case:p1',field_id:'case.pm',reason:'baseline_changed',open:true,
  expected:{...clear,revision:0},current:{...set('ou_test_pm_9'),revision:3},intended:set('ou_test_pm_2'),resolution:null}]});
const server=createServer((request,response)=>{
 response.setHeader('Content-Type',request.url==='/app.js'?'text/javascript':'text/html');
 response.end(request.url==='/app.js'?bundle.outputFiles[0].text:'<!doctype html><title>Ops sync</title><div id="root"></div><script src="/app.js"></script>');
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
try{
 browser=await chromium.launch(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{});
 const w=structuredClone(workspace);
 const open=async()=>{
  const page=await browser.newPage({viewport:{width:1100,height:1400}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/**',route=>{
   const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
   if(path.startsWith('/api/ops-sync/')){
    if(!on)return route.fulfill({status:404,json:{detail:'API 不存在'}});
    if(method==='POST'&&stale409){posts.push({path,body:route.request().postDataJSON()});stale409=false;
     statusBody={...statusBody,conflicts:statusBody.conflicts.map(k=>({...k,current:{...set('ou_test_pm_10'),revision:4}}))};   // someone changed the field meanwhile
     return route.fulfill({status:409,json:{detail:'基準值已被更動'}});}
    if(method==='POST'){posts.push({path,body:route.request().postDataJSON()});
     statusBody={...statusBody,commands:statusBody.commands.map(c=>c.command_id==='c-conf'?{...c,state:'confirmed'}:c),conflicts:statusBody.conflicts.map(k=>({...k,open:false,resolution:posts.at(-1).body.resolution}))}}
    return route.fulfill({json:statusBody});
   }
   return route.fulfill({json:path==='/api/session'?{user:w.users.find(u=>u.role==='manager')||w.users[0],users:w.users,mode:'demo',auth_configured:false}:w});
  });
  await page.goto(`http://127.0.0.1:${server.address().port}/#view=admin&tab=settings`);
  await page.getByRole('heading',{name:'管理設定'}).waitFor();
  return {page,errors};
 };
 // flag OFF: server 404 => panel hidden
 on=false;statusBody=fixture();
 let {page,errors}=await open();
 await page.waitForLoadState('networkidle');
 assert.equal(await page.getByText('營運同步狀態').count(),0,'flag off: panel hidden');
 assert.equal(await page.locator('.ops-sync').count(),0);
 assert.deepEqual(errors,[]);await page.close();
 // flag ON: six states
 on=true;statusBody=fixture();posts=[];
 ({page,errors}=await open());
 await page.getByRole('heading',{name:'營運同步狀態（本機模擬）'}).waitFor();
 assert.match(await page.getByRole('note').first().innerText(),/本機模擬.*未連線 Lark/);
 for(const [state,id] of [['waiting_approval','c-wait'],['pending','c-pend'],['confirmed','c-ok'],['conflict','c-conf'],['failed','c-fail'],['unknown','c-unk']]){
  const item=page.locator(`.ops-sync-item[data-state="${state}"]`);
  assert.equal(await item.count(),1,state);
  const text=await item.innerText();
  assert.ok(text.includes(STATES[state].label)&&text.includes(STATES[state].detail),`${state} wording`);
  assert.equal(await item.locator('.ds-badge').innerText(),STATES[state].label,`${state} badge`);
 }
 assert.equal(await page.locator('.ds-badge[data-tone=positive]').count(),1,'only confirmed is positive');
 assert.equal(await page.locator('.ops-sync-item[data-state=confirmed]').getByRole('button').count(),0);
 const conflict=await page.locator('.ops-sync-item[data-state=conflict]').innerText();
 assert.ok(conflict.includes('預期（送出時）')&&conflict.includes('ou_test_pm_9（版本 3）')&&conflict.includes('擬變更')&&conflict.includes('ou_test_pm_2'));
 assert.equal(await page.locator('.ops-sync-item[data-state=unknown]').getByRole('button',{name:'立即重新核對'}).count(),1);
 assert.equal(await page.locator('.ops-sync-item[data-state=failed]').getByRole('button').count(),0);
 await page.screenshot({path:process.env.OPS_SYNC_SCREENSHOT||undefined}).catch(()=>{});
 // explicit resolve: nothing is sent until the user chooses; the request carries the freshly read baseline
 assert.equal(posts.length,0);
 // 409 / reload: the data moved under the user. Latest state is shown, their choice stays visible, nothing is auto-resubmitted.
 stale409=true;
 await page.getByRole('button',{name:'套用擬變更值'}).click();
 await page.getByRole('alert').waitFor();
 assert.match(await page.getByRole('alert').innerText(),/已被更新.*尚未送出/);
 await page.locator('.ops-sync-intent').waitFor();
 assert.match(await page.locator('.ops-sync-intent').innerText(),/套用擬變更值.*尚未送出/);
 assert.equal(await page.locator('.ops-sync-intent').getAttribute('data-intent'),'apply_intended');
 const reloaded=await page.locator('.ops-sync-item[data-state=conflict]').innerText();
 assert.ok(reloaded.includes('ou_test_pm_10（版本 4）')&&reloaded.includes('ou_test_pm_2'),'fresh current value and the intended value are both on screen');
 assert.equal(await page.locator('.ops-sync-item[data-state=conflict]').getByRole('button',{name:'套用擬變更值'}).isEnabled(),true);
 await page.waitForTimeout(300);
 assert.equal(posts.length,1,'no automatic resubmission after a 409');
 // explicit retry carries the freshly read baseline
 await page.getByRole('button',{name:'套用擬變更值'}).click();
 await page.locator('.ops-sync-item[data-state=confirmed]').nth(1).waitFor();
 assert.equal(posts.length,2);
 assert.equal(await page.locator('.ops-sync-intent').count(),0,'intent note cleared after success');
 const {path,body}=posts[1];
 assert.equal(path,'/api/ops-sync/conflicts/conflict%3Ac-conf/resolve');
 assert.deepEqual([body.resolution,body.expected,body.expected_revision,body.intended],['apply_intended',{t:'set',v:'ou_test_pm_10'},4,{t:'set',v:'ou_test_pm_2'}]);
 assert.match(body.command_id,/^c-conf:resolve:/);
 assert.notEqual(posts[0].body.command_id,body.command_id);
 assert.deepEqual(errors,[]);
 console.log('ops-sync panel: ok');
}finally{await browser?.close();server.close()}
