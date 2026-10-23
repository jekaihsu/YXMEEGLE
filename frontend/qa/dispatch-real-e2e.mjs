import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.DISPATCH_PLAYWRIGHT_MODULE??'playwright');
const recoveryOnly=process.env.DISPATCH_E2E_RECOVERY_ONLY==='1';
const base=process.env.DISPATCH_E2E_URL??'http://localhost:5199';
const output=new URL('../../output/dispatch-publish-e2e/',import.meta.url);
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.DISPATCH_CHROME??'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const context=await browser.newContext({viewport:{width:1280,height:900},locale:'zh-TW',timezoneId:'Asia/Taipei'});
const page=await context.newPage(),trace=[],checks=[],errors=[];
page.on('pageerror',error=>errors.push(error.message));
page.on('response',async r=>{if(/\/api\/v2\/(dispatch|commands)\//.test(r.url())){let body;try{body=await r.json()}catch{}trace.push({method:r.request().method(),url:r.url(),status:r.status(),body})}});
const date=days=>{const n=new Date();return new Date(Date.UTC(n.getFullYear(),n.getMonth(),n.getDate()+days)).toISOString().slice(0,10)};
const start=date(1),title='整合驗證 港區全欄位派工';
const loaded=()=>page.getByText('已載入工作清單。',{exact:false}).waitFor();
const dialog=()=>page.getByRole('dialog');
async function shot(name,{fullPage=false,scrollTop=false,anchor}={}){
 for(const width of [1280,390]){await page.setViewportSize({width,height:width===390?844:900});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));if(scrollTop)await page.evaluate(()=>{window.scrollTo(0,0);document.querySelector('[role=dialog]')?.scrollTo(0,0)});if(anchor)await anchor.scrollIntoViewIfNeeded();await page.screenshot({path:new URL(`${name}-${width}.png`,output).pathname,fullPage,animations:'disabled'});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${name} overflow ${width}`)}
 await page.setViewportSize({width:1280,height:900});
}
async function login(alias){await page.goto(`${base}/api/dev/login?as=${alias}&next=${encodeURIComponent('/#view=dispatch&tab=work')}`);await loaded();if(!(await page.locator('.dp-week').innerText()).includes(start))await page.getByRole('button',{name:'下一週',exact:true}).click();await loaded();await page.getByRole('combobox',{name:'範圍',exact:true}).selectOption('all');await loaded()}
async function close(){await dialog().getByRole('button',{name:'關閉',exact:true}).click();await loaded()}
const cards=name=>page.locator('.dp-work-list').last().locator('.dp-work-row').filter({has:page.locator('strong').filter({hasText:name})});
const card=name=>cards(name).last();
async function openPreview(name){const published=cards(name).filter({hasText:'命令 · 已確認'});const target=await published.count()?published:card(name);await target.getByRole('button',{name:'檢視派工提案',exact:true}).click();await dialog().getByRole('button',{name:'更新預覽與核准',exact:true}).waitFor();await page.waitForFunction(()=>!document.querySelector('.dp-dialog .dp-footer button:not(:disabled)')?.disabled)}
async function capturePreview(button='檢核並預覽'){const promise=page.waitForResponse(r=>r.url().endsWith('/api/v2/dispatch/previews')&&r.request().method()==='POST');await dialog().getByRole('button',{name:button,exact:true}).click();const r=await promise;assert.equal(r.status(),200,await r.text());return r.json()}
async function verifyUnknown(){const fields=dialog().locator('.dp-verification textarea');for(let i=0;i<await fields.count();i++)await fields.nth(i).fill('主管已核對資格、請假與資源使用條件，確認可執行。');const p=await capturePreview('重新預覽');assert.equal(p.blockers.some(b=>b.startsWith('unknown:')),false);assert.ok(Object.keys(p.proposal.verifications).length);return p}
async function approvals(name){for(const [alias,label] of [['lead','組長確認'],['manager','經理審核'],['pmfinal','PM 最終確認']]){await login(alias);await cards(name).getByRole('button',{name:'核准',exact:true}).click();await dialog().locator('.dp-proposal-summary').waitFor();assert.equal(await dialog().locator('.dp-proposal-summary dt').count(),20);assert.equal((await dialog().locator('.dp-proposal-summary').innerText()).includes('結束時間不含在本工作時段內'),true);const seat=dialog().locator('.dp-seat').filter({has:page.getByRole('heading',{name:label,exact:true})});const promise=page.waitForResponse(r=>r.url().endsWith('/decisions')&&r.request().method()==='POST');await seat.getByRole('button',{name:'核准此席',exact:true}).click();const r=await promise;assert.equal(r.status(),200,await r.text());await dialog().getByText('席位決定已記錄。',{exact:true}).waitFor()}await shot(recoveryOnly?'real-recovery-seats-approved':'real-three-seats-approved',{scrollTop:true})}
async function publish(name,expectError=false){await login('pm');await openPreview(name);const promise=page.waitForResponse(r=>r.url().endsWith('/commits')&&r.request().method()==='POST');await dialog().getByRole('button',{name:'發布排班',exact:true}).click();const r=await promise,body=await r.json();if(!expectError)assert.match(body.command?.command_id??'',/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);return {status:r.status(),body}}
async function fillAssignment(name,day=start){
 await page.getByRole('button',{name:'新增排班',exact:true}).click();
 await dialog().getByRole('combobox',{name:'負責人',exact:true}).locator('option[value="recP2"]').waitFor({state:'attached'});
 for(const [label,value] of [['工作標題',name],['工作內容','測區量測、原始資料紀錄與成果交付。'],['專案編號','SYN-001'],['工作包編號','PKG-E2E-21']])await dialog().getByRole('textbox',{name:label,exact:true}).fill(value);
 await dialog().getByRole('combobox',{name:'工程確認單',exact:true}).selectOption('recCase1');await dialog().getByLabel('部門',{exact:true}).fill('外業');await dialog().getByLabel('截止日',{exact:true}).fill(date(7));await dialog().getByRole('combobox',{name:'負責人',exact:true}).selectOption('recP2');await dialog().locator('.dp-picker label').filter({hasText:'丙'}).getByRole('checkbox').check();
 await dialog().getByLabel('預定開始',{exact:true}).fill(`${day}T08:00`);await dialog().getByLabel('預定結束',{exact:true}).fill(`${day}T12:00`);await dialog().getByRole('spinbutton',{name:'預估人時',exact:true}).fill('8');await dialog().getByRole('checkbox',{name:'GNSS-01',exact:false}).check();await dialog().getByRole('checkbox',{name:'SYN-001',exact:false}).check();
}
let taskId;
try{
 if(recoveryOnly){
  const recoveryTitle='整合驗證 對帳失敗後修改';
  await login('pm');
  const taskResponse=await context.request.get(`${base}/api/v2/dispatch/tasks/recLegacy`);assert.equal(taskResponse.status(),200);const task=await taskResponse.json();
  assert.equal(task.proposal.parent_task_ref,'recObligationQA');
  const recoveryProposal={...task.proposal,title:recoveryTitle,content:'對帳失敗仍須保留的原始工作內容',phase:'formal',kind:'execution',department:'外業',primary_owner:'recP2',crew:['recP2'],start:`${date(5)}T08:00:00+08:00`,end:`${date(5)}T12:00:00+08:00`,verifications:{'person:recP2':'資格與請假已核實'}};
  const previewResponse=await context.request.post(`${base}/api/v2/dispatch/previews`,{data:recoveryProposal});assert.equal(previewResponse.status(),200,await previewResponse.text());
  await approvals('外業：待指派');await login('pm');
  assert.equal((await context.request.post(`${base}/api/dev/faults`,{data:{fault:'timeout_before_landing'}})).status(),200);
  const unknown=await publish('外業：待指派');assert.equal(unknown.status,202);assert.equal(unknown.body.command.state,'outcome_unknown');await close();
  await login('manager');await cards('外業：待指派').getByRole('button',{name:'重新對帳',exact:true}).click();await dialog().getByRole('button',{name:'重新對帳',exact:true}).waitFor();
  assert.equal((await context.request.post(`${base}/api/dev/faults`,{data:{fault:'error_before_landing'}})).status(),200);
  const failedPromise=page.waitForResponse(r=>r.url().endsWith('/reconcile')&&r.request().method()==='POST');await dialog().getByRole('button',{name:'重新對帳',exact:true}).click();const failed=await failedPromise;assert.equal(failed.status(),502);assert.equal((await failed.json()).command.state,'failed');
  await dialog().getByRole('button',{name:'修改後重新預覽',exact:true}).click();
  assert.equal(await dialog().getByRole('combobox',{name:'負責人',exact:true}).inputValue(),'recP2');
  assert.equal(await dialog().getByRole('combobox',{name:'工程確認單',exact:true}).inputValue(),'recCase1');
  assert.equal(await dialog().getByRole('textbox',{name:'父義務',exact:true}).inputValue(),'recObligationQA');
  assert.equal(await dialog().getByRole('textbox',{name:'工作內容',exact:true}).inputValue(),'對帳失敗仍須保留的原始工作內容');
  await shot('real-reconcile-failed-form',{scrollTop:true});
  await shot('real-reconcile-failed-form-parent',{anchor:dialog().getByRole('textbox',{name:'父義務',exact:true})});
  await shot('real-reconcile-failed-form-pickers',{anchor:dialog().getByRole('combobox',{name:'負責人',exact:true})});
  const retried=await capturePreview();assert.equal(retried.proposal.task_id,'recLegacy');assert.equal(retried.proposal.parent_task_ref,'recObligationQA');
  checks.push('R2 real update command times out before landing. Manager opens command recovery and reconciliation returns 502 failed. 修改後重新預覽 restores people/case pickers and the original proposal, task_id recLegacy and parent obligation recObligationQA. The next real preview preserves both references.');
  assert.deepEqual(errors,[]);await fs.writeFile(new URL('real-recovery-result.json',output),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors},null,2));
 }else{
 if(process.env.DISPATCH_E2E_RESUME){const prior=JSON.parse(await fs.readFile(new URL('real-result.json',output)));taskId=prior.taskId;checks.push(...prior.checks);trace.push(...JSON.parse(await fs.readFile(new URL('real-network.json',output))));await login('pm');await cards(title).getByRole('button',{name:'改派',exact:true}).waitFor();await card(title).locator('.dp-work-open').click();assert.equal(await dialog().locator('.dp-fields dt').count(),26);assert.ok((await dialog().innerText()).includes('已確認'));await shot('real-task-21-fields',{scrollTop:true});await dialog().getByText('接受摘要（系統唯讀）',{exact:true}).scrollIntoViewIfNeeded();await shot('real-task-21-fields-bottom');await close()}else{
 await login('pm');assert.ok(await page.locator('.dp-needs').getByText('等待指派確認',{exact:false}).count());await shot('real-work-needs-me',{fullPage:true,scrollTop:true});checks.push('PM work queue shows progress, needs_me and assignment actions.');
 await fillAssignment(title);await shot('real-full-form',{scrollTop:true});await dialog().getByRole('button',{name:'儲存草稿',exact:true}).click();await dialog().getByText('草稿已儲存，不占用人員或資源。',{exact:true}).waitFor();
 let preview=await capturePreview();assert.equal(preview.booked_person_hours,8);assert.ok(preview.blockers.some(b=>b.startsWith('unknown:person:')));await shot('real-unknown-blocked',{scrollTop:true});preview=await verifyUnknown();assert.ok(preview.required_seats.every(s=>s.configured&&s.names.length));await dialog().getByRole('button',{name:'查看核准席位',exact:true}).click();assert.equal(await dialog().getByRole('button',{name:'發布排班',exact:true}).isEnabled(),false);await shot('real-verification-recorded',{scrollTop:true});checks.push('Full form saves a versioned draft, previews 8 person-hours, blocks unknown and records kind:ref verification reasons.');
 await approvals(title);
 await login('pm');await openPreview(title);
 const changedReason='重開草稿保留的新核實原因，已另行確認現場資格與請假。';
 await dialog().locator('.dp-verification textarea').first().fill(changedReason);
 await dialog().getByRole('button',{name:'儲存草稿',exact:true}).click();await dialog().getByText('草稿已儲存，不占用人員或資源。',{exact:true}).waitFor();await close();
 await page.locator('.dp-drafts summary').click();await page.locator('.dp-drafts').getByRole('button').filter({hasText:title}).first().click();
 await dialog().getByRole('button',{name:'更新預覽與核准',exact:true}).waitFor();
 assert.equal(await dialog().locator('.dp-verification textarea').first().inputValue(),changedReason);
 assert.equal(await dialog().getByRole('button',{name:'發布排班',exact:true}).isEnabled(),false);
 assert.equal(await dialog().locator('.dp-seat').filter({hasText:'先前核准已失效'}).count(),3);
 await dialog().getByRole('button',{name:'更新預覽與核准',exact:true}).click();await dialog().getByText('已更新席位決定與發布條件。',{exact:true}).waitFor();
 assert.equal(await dialog().getByRole('button',{name:'發布排班',exact:true}).isEnabled(),false);
 await shot('real-draft-reopened-changed',{scrollTop:true});
 await shot('real-draft-reopened-reason',{anchor:dialog().locator('.dp-verification textarea').first()});
 await shot('real-draft-approvals-void',{anchor:dialog().locator('.dp-seat').first()});
 const fresh=await capturePreview('重新預覽');assert.equal(Object.values(fresh.proposal.verifications).includes(changedReason),true);assert.equal(fresh.required_seats.every(s=>s.decision!=='accepted'),true);
 await close();await approvals(title);checks.push('R1 edited verification on an approved preview, saved, closed and reopened the draft. The new reason survives; all three old approvals are void and refresh cannot enable publication. A fresh preview requires three new decisions.');
 const committed=await publish(title);assert.equal(committed.status,200);assert.equal(committed.body.command.state,'committed');taskId=committed.body.command.task_id;await dialog().getByText('任務寫入後已讀回核對成功。排程版本 1。',{exact:true}).waitFor();await shot('real-confirmed',{scrollTop:true});await close();
 await card(title).filter({hasText:'已確認'}).getByRole('button',{name:'改派',exact:true}).waitFor();assert.equal(await card(title).filter({hasText:'已確認'}).count(),1);await card(title).filter({hasText:'已確認'}).locator('.dp-work-open').click();assert.equal(await dialog().locator('.dp-fields dt').count(),26);assert.ok((await dialog().innerText()).includes('PKG-E2E-21'));await shot('real-task-21-fields',{scrollTop:true});await dialog().getByText('接受摘要（系統唯讀）',{exact:true}).scrollIntoViewIfNeeded();await shot('real-task-21-fields-bottom');checks.push(`Three distinct seat holders approve through the UI. Publication confirms task ${taskId}; work detail exposes all 21 extension fields.`);await close();
 }
 await login('pm');
 await cards(title).getByRole('button',{name:'改派',exact:true}).click();
 await dialog().getByRole('combobox',{name:'負責人',exact:true}).locator('option[value="recP1"]').waitFor({state:'attached'});
 assert.equal(await dialog().getByRole('combobox',{name:'負責人',exact:true}).inputValue(),'recP2');
 await dialog().getByRole('combobox',{name:'負責人',exact:true}).selectOption('recP1');
 for(const name of ['乙','丙'])await dialog().locator('.dp-picker label').filter({hasText:name}).getByRole('checkbox').uncheck();
 await dialog().getByLabel('預定開始',{exact:true}).fill(`${start}T13:00`);await dialog().getByLabel('預定結束',{exact:true}).fill(`${start}T17:00`);await dialog().getByRole('spinbutton',{name:'預估人時',exact:true}).fill('4');
 let revised=await capturePreview();assert.equal(revised.proposal.task_id,taskId);revised=await verifyUnknown();await close();await approvals(title);
 const reassigned=await publish(title);assert.equal(reassigned.status,200);assert.equal(reassigned.body.command.task_id,taskId);assert.equal(reassigned.body.command.revision,2);await dialog().getByText('任務寫入後已讀回核對成功。排程版本 2。',{exact:true}).waitFor();await shot('real-reassigned',{scrollTop:true});await close();checks.push('Reassignment prefills from /tasks, changes crew and interval, obtains three new decisions and updates the same task to revision 2.');
 const taskForm=await (await context.request.get(`${base}/api/v2/dispatch/tasks/${taskId}`)).json();
 const proposalA={...taskForm.proposal,title:'整合驗證 競爭提案甲',content:'第一份競爭改派',start:`${date(3)}T08:00:00+08:00`,end:`${date(3)}T12:00:00+08:00`,verifications:{'person:recP1':'主管核對資格與請假，確認可出勤'}};
 const aResponse=await context.request.post(`${base}/api/v2/dispatch/previews`,{data:proposalA});assert.equal(aResponse.status(),200);const a=await aResponse.json();await approvals(title);
 await login('pm');const bResponse=await context.request.post(`${base}/api/v2/dispatch/previews`,{data:{...proposalA,title:'整合驗證 競爭提案乙',content:'第二份競爭改派'}});assert.equal(bResponse.status(),200);const b=await bResponse.json();assert.notEqual(a.preview_hash,b.preview_hash);await approvals(title);await login('pm');
 const {randomUUID}=await import('node:crypto');const win=await context.request.post(`${base}/api/v2/dispatch/commits`,{data:{command_id:randomUUID(),preview_id:a.preview_id}});assert.equal(win.status(),200,await win.text());
 const conflict=await publish(proposalA.title,true);assert.equal(conflict.status,409);assert.ok(['preview_stale','stale_revision'].includes(conflict.body.code));await dialog().getByText(/草稿已保留/).waitFor();await shot('real-competing-proposal-409',{scrollTop:true});await close();checks.push(`Two approved proposals for the same task compete. The second publish returns 409 ${conflict.body.code} and the UI retains the draft.`);
 await login('pm');const timeoutTitle='整合驗證 逾時後對帳';await fillAssignment(timeoutTitle,date(4));await capturePreview();await verifyUnknown();await close();await approvals(timeoutTitle);await login('pm');assert.equal((await context.request.post(`${base}/api/dev/faults`,{data:{fault:'timeout_after_success'}})).status(),200);
 const unknown=await publish(timeoutTitle);assert.equal(unknown.status,202);assert.equal(unknown.body.command.state,'outcome_unknown');await dialog().getByRole('heading',{name:'結果不明',exact:true}).waitFor();await shot('real-timeout-unknown',{scrollTop:true});await close();
 await login('manager');await cards(timeoutTitle).getByRole('button',{name:'重新對帳',exact:true}).click();await dialog().getByRole('button',{name:'重新對帳',exact:true}).waitFor();const reconcilePromise=page.waitForResponse(r=>r.url().endsWith('/reconcile')&&r.request().method()==='POST');await dialog().getByRole('button',{name:'重新對帳',exact:true}).click();const reconciledResponse=await reconcilePromise,reconciled=await reconciledResponse.json();assert.equal(reconciledResponse.status(),200);assert.equal(reconciled.command.state,'committed');assert.equal(reconciled.command.command_id,unknown.body.command.command_id);await dialog().getByRole('heading',{name:'已確認',exact:true}).waitFor();await shot('real-reconciled',{scrollTop:true});await close();
 const finalWork=await (await context.request.get(`${base}/api/v2/dispatch/work?from=${start}&to=${date(7)}&scope=all`)).json();const landed=finalWork.rows.filter(r=>r.command?.command_id===unknown.body.command.command_id);assert.equal(landed.length,1);assert.equal(landed[0].source,'v4_task');assert.equal(landed[0].command.state,'committed');checks.push('timeout_after_success returns 202 and 結果不明. A manager follows next_action to reconcile the same command to 已確認. Exactly one v4_task row carries that command.');
 await shot('real-final-queue',{fullPage:true,scrollTop:true});
 await fs.writeFile(new URL('real-final-work.json',output),JSON.stringify(finalWork,null,2));assert.deepEqual(errors,[]);
 await fs.writeFile(new URL('real-result.json',output),JSON.stringify({checks,taskId,title,errors},null,2));console.log(JSON.stringify({checks,taskId,title,errors},null,2));
 }
}catch(error){await shot(recoveryOnly?'real-recovery-failure':'real-failure');throw error}
finally{await fs.writeFile(new URL(recoveryOnly?'real-recovery-network.json':'real-network.json',output),JSON.stringify(trace,null,2));await browser.close()}
