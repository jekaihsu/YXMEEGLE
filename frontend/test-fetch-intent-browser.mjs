import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {chromium} from 'playwright-core';
const bundle=await build({stdin:{resolveDir:import.meta.dirname,contents:`
import React,{useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import {usePageOwner,requestPageData} from './src/pageData';
let owner;
const resource={endpoint:'/api/business',query:{q:'a'}};
const decode=data=>({data,snapshotId:'fixture',fetchedAt:'2026-11-02T15:59:00Z',verifiedAt:null,changedAt:null,completeness:'complete',localRevision:1,empty:false,stale:false});
const read=(intent={reason:'initial_open'})=>requestPageData(owner,resource,intent,decode);
function Owner(){
 owner=usePageOwner({workspace:'fixture',identityFingerprint:'fixture-user:grants-v1',openId:'case-1'});
 useEffect(()=>{window.h={owner,resource,read,query:()=>requestPageData(owner,{...resource,query:{q:'b'}},{reason:'user_query_change'},decode)};window.ready=Promise.all([read(),read()])},[owner]);
 return React.createElement('output',null,'頁面資料擁有者');
}
createRoot(document.querySelector('#root')).render(React.createElement(React.StrictMode,null,React.createElement(Owner)));
document.querySelector('#refresh').onclick=()=>{window.done=read({reason:'explicit_refresh',id:'click-1'})};
document.querySelector('#write').onclick=()=>{window.done=owner.ownWriteCommitted('write-1',[resource,resource])};
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
  return route.fulfill({contentType:'text/html',body:`<!doctype html><div id="root"></div><button id="refresh">重新整理</button><button id="write">模擬寫入完成</button><input aria-label="interaction"><script>${bundle.outputFiles[0].text}</script>`});
 });
 await page.goto('http://127.0.0.1:52879/fixture');await page.waitForFunction(()=>window.ready!==undefined);await page.evaluate(()=>window.ready);assert.equal(log.length,1);
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

// Full built-app backstop. Point only at an isolated demo backend; never staging
// or production. CI opts in via YXMEEGLE_BROWSER_TESTS=1 and this URL.
if(process.env.YX_FETCH_INTENT_API_URL){
 const {readFile}=await import('node:fs/promises');const {resolve,extname}=await import('node:path');
 const backend=new URL(process.env.YX_FETCH_INTENT_API_URL);
 assert(['localhost','127.0.0.1','[::1]'].includes(backend.hostname),'isolated loopback backend required');
 const browser=await chromium.launch({channel:'chrome',headless:true});const results=[];
 try{
  const context=await browser.newContext(),base='http://127.0.0.1:52880';
  const apiResponse=await context.request.get(new URL('/api/session',backend).href);const session=await apiResponse.json();assert.equal(session.mode,'demo','guard requires demo API');
  const workspaceResponse=await context.request.get(new URL('/api/workspace',backend).href);const workspace=await workspaceResponse.json();
  const project=workspace.projects?.[0]?.id;assert(project,'demo case is required');
  for(const [name,hash] of [['Home','#view=dashboard'],['Case','#view=project&project='+encodeURIComponent(project)],['Dispatch','#view=dispatch']]){
   const page=await context.newPage(),requests=[],errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.clock.install({time:new Date('2026-11-02T15:59:00Z')});
   await page.route(base+'/**',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname.startsWith('/api/')){
     if(route.request().method()==='GET')requests.push(url.pathname+url.search);
     return route.fulfill({response:await route.fetch({url:new URL(url.pathname+url.search,backend).href})});
    }
    const file=url.pathname==='/'?'index.html':url.pathname.slice(1);
    try{return route.fulfill({body:await readFile(resolve(import.meta.dirname,'dist',file)),contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[extname(file)]||'application/octet-stream'})}
    catch{return route.fulfill({status:404,body:'Not found'})}
   });
   await page.goto(base+'/'+hash);await page.waitForLoadState('networkidle');
   assert((await page.locator('body').innerText()).length>100,name+' must render the real app');
   assert.equal(await page.locator('vite-error-overlay').count(),0);
   const initial=requests.length;assert(initial>0,name+' must load business data');
   await page.clock.fastForward(24*60*60*1000);
   await page.evaluate(()=>{for(const name of ['focus','focusin','visibilitychange','online','offline','pageshow','popstate','storage','pointerdown','keydown','wheel','yx:mutation-state']){window.dispatchEvent(new Event(name));document.dispatchEvent(new Event(name))}});
   await page.mouse.move(20,20);await page.keyboard.press('Shift');await page.clock.runFor(10000);await page.waitForLoadState('networkidle');
   results.push({route:name,coverage:name==='Dispatch'&&!session.features?.dispatch_board&&!session.features?.dispatch_write?'feature-disabled (board untested)':'rendered',title:await page.title(),idleRequests:requests.slice(initial),errors});
   await page.close();
  }
  console.log(JSON.stringify({builtApp:results}));
  for(const result of results){assert.equal(result.coverage,'rendered',result.route+' requires an enabled isolated fixture');assert.deepEqual(result.errors,[],result.route+' runtime errors');assert.deepEqual(result.idleRequests,[],result.route+' automatic business GET regression')}
 }finally{await browser.close()}
}else console.log('Built-app guard not run: set YX_FETCH_INTENT_API_URL to the isolated demo backend (requires npm run build).');
