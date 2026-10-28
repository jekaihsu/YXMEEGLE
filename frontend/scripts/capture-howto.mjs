/** Regenerate: start the isolated demo per isolated-review-instance.md (DEMO_MODE=true,
 * LARK_LIVE_READ_TRANSPORT=deny, private /tmp/next-howto DB; no flag changes), then run
 * HOWTO_URL=http://localhost:5298 node frontend/scripts/capture-howto.mjs from the worktree.
 * Needs frontend npm ci, installed Chrome and cwebp on PATH. Optional HOWTO_SCRATCH.
 * All API reads go to that localhost demo. No writes or external requests are allowed.
 * Demo seed names are replaced with explicit fictional labels. SOP task/assignee responses
 * and the unassigned mapping-node owner are synthetic fixtures (same technique as next-table/render.mjs); no real Lark is used.
 */
import {chromium} from 'playwright-core';
import {readFile,mkdir,writeFile,stat} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';

const root=fileURLToPath(new URL('../../',import.meta.url));
const assets=join(root,'frontend/public/howto');
const scratch=process.env.HOWTO_SCRATCH||'/tmp/next-howto';
const origin=new URL(process.env.HOWTO_URL||'http://localhost:5298');
if(!['localhost','127.0.0.1'].includes(origin.hostname))throw Error('Capture requires an isolated localhost demo');
await mkdir(assets,{recursive:true});await mkdir(scratch,{recursive:true});
const seed=await readFile(join(root,'backend/seed.py'),'utf8');
const demoNames=['林育寬','陳柏翰','李家彬','王怡婷','黃雅雯','張智偉','周子安'];
if(!demoNames.every(name=>seed.includes(name)))throw Error('Demo seed changed: review fictional-name mapping');
const labels=['示範專管員','示範外業員','示範控制員甲','示範圖資員','示範報告員','示範管理員','示範控制員乙'];
const clean=value=>{
 if(typeof value==='string')return demoNames.reduce((s,name,i)=>s.replaceAll(name,labels[i]),value);
 if(Array.isArray(value))return value.map(clean);
 if(value?.id==='p1-mapping')value={...value,owner_id:''};
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,v])=>[key,key==='avatar'?'示':clean(v)]));
 return value;
};
const examples=JSON.parse(await readFile(join(root,'backend/sop_import/api-examples.json'),'utf8'));
const base=examples.sop_tasks.tasks[0],zero={done:0,total:0,unresolved:0,not_applicable:0,archived:0};
const task=(id,title,state,executor,due)=>({...base,id,title,state,project_id:'p1',revision:7,instructions:'核對本案觀測紀錄與成果附件，完成後交由節點主管確認。',source_snapshot:null,applicability:'applicable',participants:executor?{executor}:{},allowed_actions:['edit'],overdue:!!due,nodes:[{node_key:'control',node_id:'p1-control',order:0}],node_keys:['control'],local:{...base.local,due_date:due,date_status:due?'scheduled':'unscheduled'},lark_sync:{state:'已同步',synced_at:1793145600,record_id:null}});
const tasks=[task('demo-sop-1','現場成果核對','in_progress','u-control','2026-10-27'),task('demo-sop-2','整理控制成果與交付附件','pending',null,null),task('demo-sop-3','確認觀測紀錄與坐標基準','blocked','u-agent','2026-10-26')];
const overview={...examples.sop_tasks,project_id:'p1',local_nodes:[],tasks,case_counts:{...zero,total:3},node_counts:Object.fromEntries(['sales','pm','confirmation','field','control','mapping','report','pricing','settlement'].map(k=>[k,{...zero,total:k==='control'?3:0}]))};
const assignees={people:[{id:'u-control',name:labels[2],case_roles:[],department:'控制組',teams:['控制組']},{id:'u-agent',name:labels[6],case_roles:[],department:'控制組',teams:['控制組']}],next_cursor:null};
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:900},deviceScaleFactor:1,colorScheme:'light',locale:'zh-TW',timezoneId:'Asia/Taipei',reducedMotion:'reduce'});
let page=await context.newPage();
const errors=[],blockedWrites=[],shots=[];
const observe=()=>{
 page.on('pageerror',error=>errors.push(error.message));
 page.on('console',message=>{if(message.type()==='error')errors.push(message.text())});
};
observe();
const freshPage=async(viewport,colorScheme='light')=>{
 await page.close();page=await context.newPage();await page.setViewportSize(viewport);
 await page.emulateMedia({colorScheme});observe();
};
await context.route('**/*',async route=>{
 const request=route.request(),url=new URL(request.url());
 if(url.origin!==origin.origin){await route.abort();throw Error(`External request blocked: ${url.origin}`)}
 if(!url.pathname.startsWith('/api/'))return route.continue();
 if(!['GET','HEAD'].includes(request.method())){blockedWrites.push(url.pathname);return route.fulfill({status:403,json:{detail:'Screenshot demo is read-only'}})}
 if(url.pathname==='/api/projects/p1/sop-tasks')return route.fulfill({json:overview});
 if(url.pathname==='/api/projects/p1/sop-assignees')return route.fulfill({json:assignees});
 const response=await route.fetch();
 if(!response.headers()['content-type']?.includes('application/json'))return route.fulfill({response});
 const data=await response.json();
 if(url.pathname==='/api/session'&&(data.mode!=='demo'||data.environment!=='demo'))throw Error('Refusing non-demo session');
 return route.fulfill({response,json:clean(data)});
});
const checkPrivacy=async()=>{
 const text=await page.locator('body').innerText();
 if(demoNames.some(name=>text.includes(name))||/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/.test(text)||/09\d{2}[- ]?\d{3}[- ]?\d{3}/.test(text))throw Error('Unexpected personal data in capture');
};
const shot=async(name,synthetic)=>{
 await page.evaluate(()=>document.fonts.ready);await checkPrivacy();
 const png=join(scratch,`${name}.png`);await page.screenshot({path:png,fullPage:false,animations:'disabled'});
 const output=join(assets,`${name}.webp`);
 execFileSync('cwebp',['-quiet','-q','85',png,'-o',output]);
 const bytes=(await stat(output)).size;
 if(bytes>=200000)throw Error(`Screenshot too large: ${name}: ${bytes}`);
 shots.push({file:`${name}.webp`,width:page.viewportSize().width,height:page.viewportSize().height,bytes,synthetic});
};
const open=async(hash)=>{await page.goto(new URL(`/#${hash}`,origin).href);await page.locator('.po-todos').waitFor();await page.locator('.po-task-row').first().waitFor();await page.locator('text=SOP 已啟動').first().waitFor();await page.evaluate(()=>document.fonts.ready);};
try{
 await open('view=project&project=p1&tab=overview');
 await shot('overview',true);
 await page.getByText('SOP 已啟動',{exact:true}).scrollIntoViewIfNeeded();
 await page.getByText('SOP 已啟動',{exact:true}).evaluate(el=>el.scrollIntoView({block:'start'}));await shot('sop',true);
 await page.locator('.po-todos').evaluate(el=>el.scrollIntoView({block:'start'}));await shot('tasks',true);
 const picker=page.locator('.po-task-row [aria-haspopup="listbox"]').nth(1);
 await picker.click();await page.getByRole('option',{name:`${labels[2]} · 控制組`}).waitFor();await shot('assignee',true);
 await page.getByRole('combobox').press('Escape');
 const menu=page.locator('.po-task-row [aria-haspopup="menu"]').first();
 await menu.focus();await menu.press('ArrowDown');await page.getByRole('menuitem',{name:'編輯詳情'}).waitFor();await shot('menu',true);
 await page.getByRole('menuitem').first().press('Escape');
 if(!await menu.evaluate(e=>e===document.activeElement))throw Error('Menu did not restore keyboard focus');
 await page.locator('.pf-node').filter({hasText:'控制'}).click();
 await page.locator('#flow-selected').waitFor();await page.locator('#flow-selected').scrollIntoViewIfNeeded();await shot('node',true);
 await page.goto(new URL('/#view=project&project=p1&tab=flow&node=control&section=all-tasks',origin).href);
 await page.getByRole('button',{name:'重新整理',exact:true}).first().waitFor();
 await page.getByRole('button',{name:'重新整理',exact:true}).first().scrollIntoViewIfNeeded();await shot('refresh',true);
 await open('view=project&project=p1&tab=overview');
 await page.locator('.po-task-row [aria-haspopup="menu"]').first().click();
 await page.getByRole('menuitem',{name:'編輯詳情'}).click();
 await page.getByRole('dialog').waitFor();await page.getByRole('dialog').getByText('已同步',{exact:true}).waitFor();await shot('sync',true);
 await freshPage({width:390,height:844});await open('view=project&project=p1&tab=overview');await shot('overview-mobile',true);
 await freshPage({width:1440,height:900});
 await page.goto(new URL('/#view=howto',origin).href);await page.getByRole('heading',{name:'使用說明',exact:true}).waitFor();
 await page.getByRole('navigation',{name:'使用說明目錄'}).getByRole('link',{name:'指派人員',exact:true}).click();
 await page.waitForFunction(()=>document.activeElement?.id==='assign');
 if(!page.url().endsWith('view=howto&section=assign'))throw Error('TOC route did not resolve');
 await page.getByRole('link',{name:'回到目錄 ↑'}).first().click();
 await page.waitForFunction(()=>window.scrollY===0);
 await page.locator('.howto img').evaluateAll(images=>Promise.all(images.map(img=>{img.loading='eager';return img.decode()})));
 await checkPrivacy();await page.screenshot({path:join(scratch,'guide.png'),fullPage:false,animations:'disabled'});
 await page.screenshot({path:join(scratch,'guide-full.png'),fullPage:true,animations:'disabled'});
 await freshPage({width:390,height:844});
 await page.goto(new URL('/#view=howto',origin).href);await page.getByRole('heading',{name:'使用說明',exact:true}).waitFor();
 await page.evaluate(()=>document.fonts.ready);
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile guide overflows');
 await page.screenshot({path:join(scratch,'guide-mobile.png'),fullPage:false,animations:'disabled'});
 await freshPage({width:1440,height:900},'dark');
 await page.goto(new URL('/#view=howto',origin).href);await page.getByRole('heading',{name:'使用說明',exact:true}).waitFor();
 await page.evaluate(()=>document.fonts.ready);
 await page.screenshot({path:join(scratch,'guide-dark.png'),fullPage:false,animations:'disabled'});
 if(errors.length)throw Error(`Browser errors: ${errors.join('; ')}`);
 if(blockedWrites.length)throw Error(`Unexpected write attempts: ${blockedWrites.join(', ')}`);
 await writeFile(join(scratch,'capture.json'),JSON.stringify({origin:origin.origin,title:await page.title(),shots,errors,blockedWrites,privacy:'Only demo seed data; all person labels replaced; no email or mobile phone visible',checks:['TOC click focuses destination','Back to TOC returns to top','menu keyboard focus restored','all images decoded','mobile has no horizontal overflow','light/dark screenshots captured']},null,2));
 console.log(`Captured ${shots.length} guide assets, all <200 KB; browser errors: 0; writes: 0; privacy and TOC checks passed. Evidence: ${scratch}/guide.png`);
}finally{await browser.close()}
