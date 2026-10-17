// Real browser events are required: jsdom dispatchEvent misses the microtask
// checkpoint between document capture and React's listener.
// PLAYWRIGHT_MODULE and CHROME_EXECUTABLE may select existing installations.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {createServer} from 'node:http';
import {build} from 'esbuild';
import {workspace} from './session-epoch-fixture.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const bundle=await build({entryPoints:['src/main.tsx'],bundle:true,write:false,format:'iife',platform:'browser',jsx:'automatic',loader:{'.css':'empty'},define:{'process.env.NODE_ENV':'"development"'}});
const server=createServer((request,response)=>{
 response.setHeader('Content-Type',request.url==='/app.js'?'text/javascript':'text/html');
 response.end(request.url==='/app.js'?bundle.outputFiles[0].text:'<!doctype html><title>Search regression</title><div id="root"></div><script src="/app.js"></script>');
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
try{
 browser=await chromium.launch(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{});
 const w=structuredClone(workspace);
 w.projects=Array.from({length:3},(_,i)=>({...structuredClone(w.projects[0]),id:`p${i}`,code:`YX-00${i+1}`,case_type:'formal',name:`Survey ${i+1}`}));
 for(const width of [1440,1024]){
  const page=await browser.newPage({viewport:{width,height:1000}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const requests=[];
  await page.route('**/api/**',route=>{
   requests.push(new URL(route.request().url()).pathname);
   return route.fulfill({json:requests.at(-1)==='/api/session'?{user:w.users[0],users:w.users,mode:'demo',auth_configured:false}:w});
  });
  await page.goto(`http://127.0.0.1:${server.address().port}/#view=projects`);
  await page.getByRole('heading',{name:'案件總覽',exact:true}).waitFor();
  const input=page.getByRole('textbox',{name:'搜尋案件'});
  await input.click();
  for(const [index,character] of [...'YX-002'].entries()){
   await input.pressSequentially(character);
   assert.equal(await input.inputValue(),'YX-002'.slice(0,index+1),`${width}: each native keystroke survives React's onChange`);
  }
  assert.equal(await page.locator('.projects-table tbody tr').count(),1,`${width}: search filters rows`);
  assert.match(await page.locator('.projects-table tbody').innerText(),/YX-002/);
  const reads=requests.length;
  await page.getByRole('button',{name:'重新整理資料',exact:true}).click();
  assert.equal(requests.length,reads,`${width}: blurred dirty input still blocks workspace reload`);
  await page.getByRole('button',{name:'清除搜尋',exact:true}).click();
  assert.equal(await input.inputValue(),'');
  assert.equal(await page.locator('.projects-table tbody tr').count(),3);
  await Promise.all([
   page.waitForResponse(response=>new URL(response.url()).pathname==='/api/workspace'),
   page.getByRole('button',{name:'重新整理資料',exact:true}).click(),
  ]);
  assert.ok(requests.length>reads,`${width}: clearing to baseline releases reload guard`);
  await input.fill('YX-003');
  assert.equal(await input.inputValue(),'YX-003',`${width}: native replacement also survives`);
  assert.equal(await page.locator('.projects-table tbody tr').count(),1);
  assert.match(await page.locator('.projects-table tbody').innerText(),/YX-003/);
  assert.deepEqual(errors,[],`${width}: no browser runtime errors`);
  console.log(`Search input: ${width}px native typing, replacement, clear, filtering and reload protection passed`);
  await page.close();
 }
}finally{
 await browser?.close();
 await new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()));
}
