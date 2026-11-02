import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {chromium} from 'playwright-core';
const bundle=await build({stdin:{resolveDir:import.meta.dirname,contents:`
import {createPageData,requestPageData} from './src/pageData';
const owner=createPageData({workspace:'fixture',identityFingerprint:'fixture-user:grants-v1',openId:'case-1'});
const resource={endpoint:'/api/business',query:{q:'a'}};
const decode=data=>({data,snapshotId:'fixture',fetchedAt:'2026-11-02T15:59:00Z',verifiedAt:null,changedAt:null,completeness:'complete',localRevision:1,empty:false,stale:false});
const read=(intent={reason:'initial_open'})=>requestPageData(owner,resource,intent,decode);
window.h={owner,resource,read,query:()=>requestPageData(owner,{...resource,query:{q:'b'}},{reason:'user_query_change'},decode)};
document.querySelector('#refresh').onclick=()=>{window.done=read({reason:'explicit_refresh',id:'click-1'})};
document.querySelector('#write').onclick=()=>{window.done=owner.ownWriteCommitted('write-1',[resource,resource])};
window.ready=Promise.all([read(),read()]);
`},bundle:true,write:false,format:'iife',platform:'browser'});
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage();const log=[],errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.clock.install({time:new Date('2026-11-02T15:59:00Z')});
 await page.route('http://127.0.0.1:52879/**',async route=>{
  const request=route.request();
  if(new URL(request.url()).pathname.startsWith('/api/')){
   log.push({url:request.url(),headers:request.headers()});
   return route.fulfill({contentType:'application/json',body:JSON.stringify({count:log.length})});
  }
  return route.fulfill({contentType:'text/html',body:`<!doctype html><button id="refresh">重新整理</button><button id="write">模擬寫入完成</button><input aria-label="interaction"><script>${bundle.outputFiles[0].text}</script>`});
 });
 await page.goto('http://127.0.0.1:52879/fixture');await page.evaluate(()=>window.ready);assert.equal(log.length,1);
 await page.clock.fastForward(24*60*60*1000);
 await page.evaluate(()=>{
  for(const event of ['focus','visibilitychange','online','pointerdown','keydown','wheel']){window.dispatchEvent(new Event(event));document.dispatchEvent(new Event(event))}
 });
 await page.locator('input').click();await page.keyboard.press('a');await page.evaluate(()=>window.h.read());assert.equal(log.length,1,'24h incl midnight and real input never refetch');
 await page.locator('#refresh').click();await page.evaluate(()=>window.done);assert.equal(log.length,2);
 assert.equal(log.at(-1).headers['x-yx-fetch-intent'],'explicit_refresh');assert.equal(log.at(-1).headers['cache-control'],'no-cache');
 await page.locator('#write').click();await page.evaluate(()=>window.done);assert.equal(log.length,3);assert.equal(log.at(-1).headers['x-yx-fetch-intent'],'own_write_committed');
 await page.evaluate(()=>window.h.query());assert.equal(log.length,4);
 await page.evaluate(()=>window.h.owner.unknownOutcome(window.h.resource,'unknown-write'));
 await page.clock.fastForward(24*60*60*1000);assert.equal(log.length,4,'unknown outcome does not repeat reads or writes');
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({status:'passed',businessRequests:log.map(({url,headers})=>({url,reason:headers['x-yx-fetch-intent']})),idleRequests:0}));
}finally{await browser.close()}
