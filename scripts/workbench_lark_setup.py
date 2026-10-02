"""Fixed-target browser steps for the workbench Lark acceptance setup.

Only the dedicated workbench30 browser and named backup/QA tabs are used.
No arbitrary JavaScript, paths, credentials or URLs are accepted as arguments.
"""
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path
import subprocess
import sys
from browser_step import public_output

ROOT=Path(__file__).resolve().parents[1]
STEPS={
    'backup-folder-permission-prepare':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-folder')throw Error('Exact backup folder unavailable');
 if(!await p.getByRole('menu').isVisible())await p.getByRole('dialog').getByRole('button',{name:'可閱讀',exact:true}).click();
 const option=p.getByRole('menu').locator('.member-auth-type-menu-comp__item_content').filter({hasText:'可管理'});
 if(await option.count()!==1) return {menu:await p.getByRole('menu').innerText(),options:await p.getByRole('menu').locator('*').evaluateAll(es=>es.filter(e=>e.children.length===0).map(e=>({tag:e.tagName,cls:e.className,text:e.textContent})))};
 await option.click();
 return {dialogs:await p.getByRole('dialog').allInnerTexts()};
}''',
    'backup-folder-grant':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-folder')throw Error('Exact backup folder unavailable');
 const d=p.getByRole('dialog').filter({hasText:'新增協作者'});
 if(await d.getByText('詠翔工作台備份',{exact:true}).count()!==1||await d.getByText('可管理',{exact:true}).count()!==1||await d.getByRole('checkbox',{name:'傳送通知',exact:true}).isChecked())throw Error('Backup grant form changed');
 await d.getByRole('button',{name:'完成',exact:true}).click();
 await d.waitFor({state:'hidden'});
 return {target:'S6lqfyItLlr42OdCidWjgkLEpic',grant_submitted:true,dialogs:await p.getByRole('dialog').allInnerTexts()};
}''',
    'backup-folder-permission-options':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-folder')throw Error('Exact backup folder unavailable');
 const d=p.getByRole('dialog').filter({hasText:'新增協作者'});
 await d.getByRole('checkbox',{name:'傳送通知',exact:true}).uncheck();
 await d.getByText('可閱讀',{exact:true}).click();
 return {text:(await p.locator('body').innerText()).slice(-5000)};
}''',
    'backup-folder-select-bot':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-folder')throw Error('Exact backup folder unavailable');
 await p.getByRole('dialog').getByText('詠翔工作台備份',{exact:true}).click();
 return {dialogs:await p.getByRole('dialog').allInnerTexts(),checkboxes:await p.getByRole('checkbox').evaluateAll(es=>es.map(e=>({checked:e.checked,label:e.closest('label')?.innerText})))};
}''',
    'backup-folder-search-bot':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-folder')throw Error('Exact backup folder unavailable');
 await p.getByPlaceholder('搜尋使用者、群組、部門、使用者群組或代理',{exact:true}).fill('詠翔工作台備份');
 await p.waitForTimeout(1000);
 return {dialogs:await p.getByRole('dialog').allInnerTexts(),text:(await p.locator('body').innerText()).slice(-6000)};
}''',
    'backup-folder-add-form':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-folder')throw Error('Exact backup folder unavailable');
 const d=p.getByRole('dialog').filter({hasText:'管理協作者'});
 const rows=await d.getByRole('listitem').allInnerTexts();
 if(rows.length!==2||!rows.some(t=>t.startsWith('詠翔專案工作台\n擁有者'))||!rows.some(t=>t.startsWith('jekai\n')))throw Error('Unexpected existing collaborators');
 await d.getByRole('button',{name:'新增協作者',exact:true}).click();
 return {dialogs:await p.getByRole('dialog').allInnerTexts(),inputs:await p.getByRole('textbox').evaluateAll(es=>es.map(e=>({placeholder:e.getAttribute('placeholder')})))};
}''',
    'backup-folder-member-control':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-folder')throw Error('Exact backup folder unavailable');
 await p.screenshot({path:'output/playwright/backup-folder-current-20260930.png'});
 return await p.getByRole('dialog').locator('svg[data-icon="GroupOutlined"]').evaluate(e=>{let n=e;const result=[];for(let i=0;i<4&&n;i++,n=n.parentElement)result.push({tag:n.tagName,cls:n.getAttribute('class'),text:n.textContent,html:n.tagName==='DIV'?n.outerHTML.slice(0,7000):undefined});return result;});
}''',
    'backup-folder-all-members':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-folder')throw Error('Exact backup folder unavailable');
 await p.getByRole('dialog').locator('svg[data-icon="ExpandRightFilled"]').click();
 await p.getByText('所有可存取此資料夾的使用者',{exact:true}).waitFor();
 const d=p.getByRole('dialog').filter({hasText:'管理協作者'});
 return {observed_at:new Date().toISOString(),folder_token:'S6lqfyItLlr42OdCidWjgkLEpic',text:await d.innerText(),members:await d.getByRole('listitem').allInnerTexts(),lists:await d.locator('ul').evaluateAll(es=>es.map(e=>({scrollHeight:e.scrollHeight,clientHeight:e.clientHeight,scrollTop:e.scrollTop})))};
}''',
    'backup-folder-share-controls':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-folder')throw Error('Exact backup folder unavailable');
 return await p.getByRole('dialog').evaluate(e=>[...e.querySelectorAll('button,[data-e2e],input,svg')].map(n=>({tag:n.tagName,label:n.getAttribute('aria-label'),title:n.getAttribute('title'),e2e:n.getAttribute('data-e2e'),icon:n.getAttribute('data-icon'),cls:n.getAttribute('class'),text:n.tagName==='BUTTON'?n.innerText:undefined})));
}''',
    'backup-folder-share':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-folder')throw Error('Exact backup folder unavailable');
 await p.locator('[data-e2e="folder-share-btn"]').click();
 await p.getByRole('dialog').waitFor();
 return {dialogs:await p.getByRole('dialog').allInnerTexts()};
}''',
    'backup-folder-inspect':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-folder')throw Error('Exact backup folder unavailable');
 return {text:(await p.locator('body').innerText()).slice(-10000),dialogs:await p.getByRole('dialog').allInnerTexts(),lists:await p.getByRole('dialog').locator('ul').evaluateAll(es=>es.map(e=>({text:e.innerText,scrollHeight:e.scrollHeight,clientHeight:e.clientHeight,children:e.children.length})))};
}''',
    'backup-folder-members':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-folder')throw Error('Exact backup folder unavailable');
 await p.locator('.explorer-v3-rightbar-folder').getByText('協作者',{exact:true}).locator('..').locator('ul').click();await p.waitForTimeout(500);
 return {dialogs:await p.getByRole('dialog').allInnerTexts()};
}''',
    'backup-folder-open':r'''async(current)=>{
 const target='https://yong-xiang-survey.jp.larksuite.com/drive/folder/S6lqfyItLlr42OdCidWjgkLEpic';
 let p=current.context().pages().find(tab=>tab.url().startsWith(target));
 if(!p)p=await current.context().newPage();
 await p.goto(target);await p.evaluate(()=>window.name='yx-backup-folder');await p.waitForTimeout(800);
 return {url:p.url(),text:(await p.locator('body').innerText()).slice(-12000),buttons:await p.getByRole('button').allInnerTexts()};
}''',
    'qa-definition-identify':r'''async(current)=>{
 for(const p of current.context().pages()){
  if(!p.url().includes('/approval/admin/approvalList')||await p.evaluate(()=>window.name)!=='yx-native-qa-definition')continue;
  const row=p.locator('li.ApprovalGroup_item').filter({has:p.getByText('詠翔工作台－串接驗收測試',{exact:true})});
  const link=row.locator('a[href*="createApproval?id="]');
  const target=await link.getAttribute('href');if(!target.includes('7691275502535413275'))throw Error('QA id changed');
  const records=[];const pending=[];
  const listener=r=>{if(r.url().includes('/approval/')&&r.request().method()==='GET'&&(r.headers()['content-type']||'').includes('json'))pending.push(r.json().then(x=>{const raw=JSON.stringify(x);if(raw.includes('詠翔工作台－串接驗收測試'))records.push({url:r.url(),data:x});}).catch(()=>{}));};
  p.on('response',listener);
  await p.goto(new URL(target,p.url()).href);await p.waitForTimeout(1800);p.off('response',listener);await Promise.all(pending);
  return {url:p.url(),records,text:(await p.locator('body').innerText()).slice(0,7000)};
 }throw Error('QA list unavailable');
}''',
    'qa-row-controls':r'''async(current)=>{
 for(const p of current.context().pages()){
  if(!p.url().includes('/approval/admin/approvalList')||await p.evaluate(()=>window.name)!=='yx-native-qa-definition')continue;
  const name=p.getByText('詠翔工作台－串接驗收測試',{exact:true});await name.hover();
  return await name.evaluate(e=>{let n=e;const rows=[];for(let i=0;i<5&&n;i++,n=n.parentElement)rows.push({tag:n.tagName,cls:n.className,text:n.innerText,links:[...n.querySelectorAll('a')].map(a=>({text:a.innerText,href:a.href})),buttons:[...n.querySelectorAll('button')].map(a=>({text:a.innerText,label:a.getAttribute('aria-label')}))});return rows;});
 }throw Error('QA list unavailable');
}''',
    'qa-links-inspect':r'''async(current)=>{
 const result=[];
 for(const p of current.context().pages()){
  if(!p.url().startsWith('https://www.larksuite.com/approval/'))continue;
  result.push({url:p.url(),name:await p.evaluate(()=>window.name),text:(await p.locator('body').innerText()).slice(-9000)});
 }return result;
}''',
    'qa-published-open':r'''async(current)=>{
 for(const p of current.context().pages()){
  if(!p.url().includes('/approval/admin/approvalList')||await p.evaluate(()=>window.name)!=='yx-native-qa-definition')continue;
  await p.getByText('詠翔工作台－串接驗收測試',{exact:true}).click();await p.waitForTimeout(600);
  return {url:p.url(),text:(await p.locator('body').innerText()).slice(0,5000)};
 }throw Error('Published QA list unavailable');
}''',
    'qa-publish':r'''async(current)=>{
 for(const p of current.context().pages()){
  if(!p.url().endsWith('/approval/admin/createApproval')||await p.evaluate(()=>window.name)!=='yx-native-qa-definition')continue;
  if(!(await p.locator('body').innerText()).startsWith('詠翔工作台－串接驗收測試'))throw Error('QA identity changed');
  if(!await p.getByRole('radio',{name:"Auto approval won't apply. All steps need to be approved.",exact:true}).isChecked())throw Error('Auto approval must be disabled');
  await p.getByRole('button',{name:'Publish',exact:true}).click();await p.waitForTimeout(1000);
  return {url:p.url(),text:(await p.locator('body').innerText()).slice(-16000)};
 }throw Error('QA creation form unavailable');
}''',
    'qa-more-configure':r'''async(current)=>{
 for(const p of current.context().pages()){
  if(!p.url().endsWith('/approval/admin/createApproval')||await p.evaluate(()=>window.name)!=='yx-native-qa-definition')continue;
  await p.getByRole('radio',{name:"Auto approval won't apply. All steps need to be approved.",exact:true}).check();
  return {checkboxes:await p.getByRole('checkbox').evaluateAll(es=>es.map(e=>({checked:e.checked,label:e.closest('label')?.innerText}))),radios:await p.getByRole('radio').evaluateAll(es=>es.map(e=>({checked:e.checked,label:e.closest('label')?.innerText})))};
 }throw Error('QA creation form unavailable');
}''',
    'qa-process-save':r'''async(current)=>{
 for(const p of current.context().pages()){
  if(!p.url().endsWith('/approval/admin/createApproval')||await p.evaluate(()=>window.name)!=='yx-native-qa-definition')continue;
  await p.getByRole('radio',{name:'Manual approval',exact:true}).check();
  await p.getByRole('radio',{name:'Multi-select',exact:true}).check();
  await p.getByRole('radio',{name:'Everyone assigned (all approvers need to agree)',exact:true}).check();
  await p.getByRole('radio',{name:'Requester reviews the request',exact:true}).check();
  await p.getByRole('button',{name:'Save',exact:true}).first().click();
  await p.getByText('More',{exact:true}).click();
  return {text:(await p.locator('body').innerText()).slice(-15000),checkboxes:await p.getByRole('checkbox').evaluateAll(es=>es.map(e=>({checked:e.checked,label:e.closest('label')?.innerText})))};
 }throw Error('QA creation form unavailable');
}''',
    'qa-process-open':r'''async(current)=>{
 for(const p of current.context().pages()){
  if(!p.url().endsWith('/approval/admin/createApproval')||await p.evaluate(()=>window.name)!=='yx-native-qa-definition')continue;
  await p.getByText('ApprovalApprover：Requester self-selection',{exact:true}).click();
  return {text:(await p.locator('body').innerText()).slice(-15000),radios:await p.getByRole('radio').evaluateAll(es=>es.map(e=>({checked:e.checked,label:e.closest('label')?.innerText})))};
 }throw Error('QA creation form unavailable');
}''',
    'qa-fields-process':r'''async(current)=>{
 for(const p of current.context().pages()){
  if(!p.url().endsWith('/approval/admin/createApproval')||await p.evaluate(()=>window.name)!=='yx-native-qa-definition')continue;
  if(await p.getByRole('textbox').nth(0).inputValue()!=='Paragraph')throw Error('Unexpected first field');
  await p.getByRole('textbox').nth(0).fill('驗收識別');await p.getByRole('textbox').nth(1).fill('僅供測試，不綁定正式案件。');
  await p.getByRole('tabpanel').getByText('Paragraph',{exact:true}).click();
  await p.getByRole('textbox').nth(0).fill('驗收測試內容');await p.getByRole('textbox').nth(1).fill('不影響案件、財務、薪資或工程進度。');
  await p.getByText('Process Design',{exact:true}).click();await p.waitForTimeout(500);
  return {text:(await p.locator('body').innerText()).slice(-14000)};
 }throw Error('QA creation form unavailable');
}''',
    'qa-add-first-field':r'''async(current)=>{
 for(const p of current.context().pages()){
  if(!p.url().endsWith('/approval/admin/createApproval')||await p.evaluate(()=>window.name)!=='yx-native-qa-definition')continue;
  await p.getByRole('tabpanel').getByText('Paragraph',{exact:true}).click();
  return {text:(await p.locator('body').innerText()).slice(-10000),inputs:await p.getByRole('textbox').evaluateAll(es=>es.map(e=>({placeholder:e.getAttribute('placeholder'),value:e.value})))};
 }throw Error('QA creation form unavailable');
}''',
    'qa-basic-fill':r'''async(current)=>{
 for(const p of current.context().pages()){
  if(!p.url().endsWith('/approval/admin/createApproval')||await p.evaluate(()=>window.name)!=='yx-native-qa-definition')continue;
  await p.getByPlaceholder('Enter a name',{exact:true}).fill('詠翔工作台－串接驗收測試');
  await p.getByPlaceholder('Description',{exact:true}).fill('僅供工作台串接驗收測試，不對應正式案件、不改工程進度、不產生財務或薪資效力。須兩位不同人共同核准，由本人操作。');
  await p.getByText('Form Design',{exact:true}).click();
  return {text:(await p.locator('body').innerText()).slice(0,14000),inputs:await p.getByRole('textbox').evaluateAll(es=>es.map(e=>({placeholder:e.getAttribute('placeholder')})))};
 }throw Error('QA creation form unavailable');
}''',
    'qa-custom-form':r'''async(current)=>{
 for(const p of current.context().pages()){
  if(!p.url().startsWith('https://www.larksuite.com/approval/admin/')||await p.evaluate(()=>window.name)!=='yx-native-qa-definition')continue;
  await p.getByText('Create custom approval',{exact:true}).click();await p.waitForTimeout(700);
  return {url:p.url(),text:(await p.locator('body').innerText()).slice(0,14000),inputs:await p.getByRole('textbox').evaluateAll(es=>es.map(e=>({placeholder:e.getAttribute('placeholder')})))};
 }throw Error('QA tab unavailable');
}''',
    'qa-create-form':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url().startsWith('https://www.larksuite.com/approval/admin/approvalList'));
 if(!p||await p.evaluate(()=>window.name)!=='yx-native-qa-definition')throw Error('Dedicated QA approval list unavailable');
 if(await p.getByText('詠翔工作台－串接驗收測試',{exact:true}).count())throw Error('Existing QA definition needs reconciliation');
 await p.getByText('Create Approval',{exact:true}).click();await p.waitForTimeout(500);
 return {url:p.url(),text:(await p.locator('body').innerText()).slice(0,16000),inputs:await p.getByRole('textbox').evaluateAll(es=>es.map(e=>({placeholder:e.getAttribute('placeholder')})))};
}''',
    'backup-credentials-capture':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://open.larksuite.com/app/cli_aa361fea3678de13/baseinfo');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup credentials unavailable');
 const row=p.locator('.auth-info__secret');
 const show=row.locator('.secret-code__btn').nth(1);
 await show.hover();await p.waitForTimeout(300);
 if(!(await p.getByRole('tooltip').allInnerTexts()).includes('显示'))throw Error('Expected show control');
 await show.click();
 try {
   const value=(await row.locator('.secret-code__code').innerText()).trim();
   if(!/^[A-Za-z0-9_-]{16,128}$/.test(value))throw Error('Unexpected credential format');
   return {private_credential:value};
 }finally{await show.click();}
}''',
    'backup-secret-button-labels':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://open.larksuite.com/app/cli_aa361fea3678de13/baseinfo');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup credentials unavailable');
 const buttons=p.locator('.auth-info__secret .secret-code__btn');const result=[];
 for(let i=0;i<await buttons.count();i++){await buttons.nth(i).hover();await p.waitForTimeout(350);result.push({index:i,tooltips:await p.getByRole('tooltip').allInnerTexts()});}
 return result;
}''',
    'backup-secret-controls':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://open.larksuite.com/app/cli_aa361fea3678de13/baseinfo');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup credentials unavailable');
 return await p.getByText('App Secret',{exact:true}).evaluate(e=>{
   let parent=e;const levels=[];
   for(let i=0;i<6&&parent;i++,parent=parent.parentElement)levels.push({tag:parent.tagName,cls:parent.className,children:[...parent.querySelectorAll('*')].slice(0,55).map(n=>({tag:n.tagName,cls:n.getAttribute('class'),title:n.getAttribute('title'),'aria-label':n.getAttribute('aria-label'),role:n.getAttribute('role')}))});
   return levels;
 });
}''',
    'backup-credentials-layout':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url().startsWith('https://open.larksuite.com/app/cli_aa361fea3678de13/'));
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup application unavailable');
 await p.getByText('凭证与基础信息',{exact:true}).click();await p.waitForTimeout(600);
 return {url:p.url(),buttons:await p.getByRole('button').allInnerTexts(),inputs:await p.locator('input').evaluateAll(es=>es.map(e=>({type:e.type,placeholder:e.placeholder}))),secretLabels:await p.getByText('App Secret',{exact:true}).count()};
}''',
    'backup-version-submit':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url().startsWith('https://open.larksuite.com/app/cli_aa361fea3678de13/version/'));
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup version unavailable');
 const d=p.getByRole('dialog').filter({hasText:'确认提交发布申请？'});
 if(await d.count()!==1)throw Error('Expected publish confirmation');
 await d.getByRole('button',{name:'申请线上发布',exact:true}).click();
 await p.waitForTimeout(1500);
 return {url:p.url(),text:(await p.locator('body').innerText()).slice(0,15000)};
}''',
    'backup-version-scope-confirm':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://open.larksuite.com/app/cli_aa361fea3678de13/version/create');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup version form unavailable');
 const d=p.getByRole('dialog').filter({hasText:'可用范围设置'});
 const text=(await d.innerText()).replace(/\s/g,'');
 if(!text.includes('已选：1个成员')||!text.includes('jekai'))throw Error('Expected jekai-only availability');
 await d.getByRole('button',{name:'确定',exact:true}).click();
 return {url:p.url(),text:(await p.locator('body').innerText()).slice(0,13000)};
}''',
    'backup-version-save':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://open.larksuite.com/app/cli_aa361fea3678de13/version/create');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup version form unavailable');
 if(await p.getByPlaceholder('对用户展示的正式版本号',{exact:true}).inputValue()!=='1.0.0')throw Error('Version mismatch');
 const text=(await p.locator('body').innerText()).replace(/\s/g,'');
 if(!text.includes('部分成员编辑成员：jekai')||!text.includes('待上线'))throw Error('Backup visibility or state changed');
 await p.getByRole('button',{name:'保存',exact:true}).click();
 await p.waitForTimeout(1000);
 return {url:p.url(),text:(await p.locator('body').innerText()).slice(0,15000)};
}''',
    'backup-version-fill':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://open.larksuite.com/app/cli_aa361fea3678de13/version/create');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup version form unavailable');
 await p.getByPlaceholder('对用户展示的正式版本号',{exact:true}).fill('1.0.0');
 await p.getByPlaceholder('该内容将展示在应用的更新日志中',{exact:true}).fill('工作台加密異地備份專用身分；僅上傳檔案與唯讀清單／下載核實。不授刪除、Base、薪資或通知權限。');
 await p.getByPlaceholder('帮助审核人员了解此应用的附加信息，例如：1. 为什么需要开通这些高级权限；2. 为什么需要申请相关可用范围。',{exact:true}).fill('依業主核定建立獨立備份身分，還原金鑰由 jekai 保管；資料夾權限另行限定，不啟用正式備份排程。');
 await p.getByText('编辑',{exact:true}).click();
 return {dialogs:await p.getByRole('dialog').allInnerTexts(),inputs:await p.getByRole('textbox').evaluateAll(es=>es.map(e=>({placeholder:e.getAttribute('placeholder')})))};
}''',
    'backup-version-form':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url().startsWith('https://open.larksuite.com/app/cli_aa361fea3678de13/'));
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup application unavailable');
 await p.getByText('创建版本',{exact:true}).click();
 return {url:p.url(),text:(await p.locator('body').innerText()).slice(0,18000),inputs:await p.getByRole('textbox').evaluateAll(es=>es.map(e=>({placeholder:e.getAttribute('placeholder'),label:e.getAttribute('aria-label')})))};
}''',
    'backup-add-bot':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url().startsWith('https://open.larksuite.com/app/cli_aa361fea3678de13/capability'));
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup capability tab unavailable');
 const card=p.getByText('机器人',{exact:true}).locator('xpath=ancestor::*[.//button[normalize-space()="添加"]][1]');
 const add=card.getByRole('button',{name:'添加',exact:true});if(await add.count()!==1)throw Error('Robot capability card changed');
 await add.click();
 return {url:p.url(),text:(await p.locator('body').innerText()).slice(0,14000)};
}''',
    'backup-capabilities':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url().startsWith('https://open.larksuite.com/app/cli_aa361fea3678de13/'));
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup application unavailable');
 await p.getByText('添加应用能力',{exact:true}).click();
 return {text:(await p.locator('body').innerText()).slice(0,15000)};
}''',
    'backup-grant-scopes':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://open.larksuite.com/app/cli_aa361fea3678de13/auth');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup permissions tab unavailable');
 const d=p.getByRole('dialog').filter({hasText:'开通权限例如：查看群信息、im:chat:read'});
 const selected=(await d.innerText()).replace(/\s/g,'');
 if(!selected.includes('已选：应用身份权限(2)')||selected.includes('用户身份权限(2)'))throw Error('Expected exactly two application scopes');
 await d.getByRole('button',{name:'确认开通权限',exact:true}).click();await d.waitFor({state:'hidden'});
 return {text:(await p.locator('body').innerText()).slice(0,14000)};
}''',
    'backup-select-scopes':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://open.larksuite.com/app/cli_aa361fea3678de13/auth');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup permissions tab unavailable');
 const d=p.getByRole('dialog').filter({hasText:'开通权限例如：查看群信息、im:chat:read'});
 for(const scope of ['drive:file:upload','drive:drive:readonly']){
   await d.getByPlaceholder('例如：查看群信息、im:chat:read',{exact:true}).fill(scope);
   const token=d.getByText(scope,{exact:true});await token.waitFor();
   const row=token.locator('xpath=ancestor::div[contains(@class,"virtual-table__row")][1]');
   if(await row.count()!==1)throw Error('Exact scope row cannot be verified');
   await row.getByRole('checkbox').check();
 }
 return {text:(await d.innerText()).slice(-16000)};
}''',
    'backup-scope-search':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://open.larksuite.com/app/cli_aa361fea3678de13/auth');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup permissions tab unavailable');
 const notice=p.getByText('我知道了',{exact:true});if(await notice.isVisible().catch(()=>false))await notice.click();
 const d=p.getByRole('dialog').filter({hasText:'开通权限例如：查看群信息、im:chat:read'});
 const search=d.getByPlaceholder('例如：查看群信息、im:chat:read',{exact:true});
 await search.fill('drive:file');await p.waitForTimeout(350);
 return {text:(await d.innerText()).slice(0,17000)};
}''',
    'backup-scope-form':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url()==='https://open.larksuite.com/app/cli_aa361fea3678de13/auth');
 if(!p||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')throw Error('Exact backup permissions tab unavailable');
 await p.getByText('开通权限',{exact:true}).click();
 const d=p.getByRole('dialog');await d.waitFor();
 return {text:(await d.innerText()).slice(0,16000),inputs:await d.getByRole('textbox').evaluateAll(es=>es.map(e=>({placeholder:e.getAttribute('placeholder')})))};
}''',
    'company-reauth':r'''async(current)=>{
 const origin='https://yongxiang-projects-20260925.zeabur.app';
 const p=current.context().pages().find(tab=>tab.url().startsWith(origin));
 if(!p)throw Error('Company tab unavailable');
 await p.goto(origin+'/api/auth/lark/login');await p.waitForLoadState('domcontentloaded');
 const url=new URL(p.url());
 return {origin:url.origin,path:url.pathname,text:(await p.locator('body').innerText()).slice(0,2000)};
}''',
    'company-consent-existing':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url().startsWith('https://accounts.larksuite.com/open-apis/authen/v1/authorize'));
 if(!p)throw Error('Existing company OAuth consent page unavailable');
 const url=new URL(p.url());
 if(url.searchParams.get('app_id')!=='cli_aa3cab98b2789e17')throw Error('Wrong app');
 const text=await p.locator('body').innerText();
 if(!text.includes('詠翔專案工作台')||!text.includes('jekai')||!text.includes('無新增需授予的權限'))throw Error('Previously approved account/scopes not confirmed');
 await p.getByRole('button',{name:'授權',exact:true}).click();
 await p.waitForLoadState('domcontentloaded');await p.waitForTimeout(1500);
 const after=new URL(p.url());
 return {origin:after.origin,path:after.pathname,text:(await p.locator('body').innerText()).slice(0,800)};
}''',
    'company-switch-production':r'''async(current)=>{
 const origin='https://yongxiang-projects-20260925.zeabur.app';
 const p=current.context().pages().find(tab=>tab.url().startsWith(origin));
 if(!p)throw Error('Company tab unavailable');
 return await p.evaluate(async()=>{
  const session=await (await fetch('/api/session')).json();
  if(session.mode!=='lark'||session.user?.name!=='jekai')throw Error('Verified account required');
  if(session.environment==='test'){
   const result=await fetch('/api/workspace/switch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({environment:'production'})});
   if(!result.ok)throw Error('Workspace switch not verified');
  }
  const current=await (await fetch('/api/session')).json();
  return {logged_in:!!current.user,environment:current.environment,formal_namespace:current.workspace_id?.startsWith('lark-')===true};
 });
}''',
    'company-source-refresh':r'''async(current)=>{
 const origin='https://yongxiang-projects-20260925.zeabur.app';
 const p=current.context().pages().find(tab=>tab.url().startsWith(origin));
 if(!p)throw Error('Company tab unavailable');
 return await p.evaluate(async()=>{
  const session=await (await fetch('/api/session')).json();
  if(session.mode!=='lark'||session.user?.name!=='jekai'||!session.workspace_id?.startsWith('lark-'))throw Error('Verified formal namespace required');
  const response=await fetch('/api/sources/sync',{method:'POST'});
  if(!response.ok)return {http_status:response.status,verified:false};
  const data=await response.json();
  return {http_status:response.status,status:data.status,mapping_status:data.mapping_status,source_record_count:data.records?.length,
   table_count:data.tables?.length,all_tables_ready:data.tables?.every(t=>t.status==='ready')};
 });
}''',
    'company-cockpit-diagnose':r'''async(current)=>{
 const origin='https://yongxiang-projects-20260925.zeabur.app';
 const p=current.context().pages().find(tab=>tab.url().startsWith(origin));
 if(!p)throw Error('Company tab unavailable');
 await p.screenshot({path:'output/playwright/company-cockpit-diagnostic.png',fullPage:true});
 return await p.evaluate(()=>({path:location.pathname,hash:location.hash,
  headings:[...document.querySelectorAll('h1,h2')].map(e=>e.textContent),
  alerts:[...document.querySelectorAll('[role=alert]')].map(e=>e.textContent),
  loading:document.querySelector('.loading-page')?.textContent,
  body_length:document.body.innerText.length,
  assets:[...document.querySelectorAll('script[src]')].map(e=>new URL(e.src).pathname)}));
}''',
    'company-cockpit-ui':r'''async(current)=>{
 const origin='https://yongxiang-projects-20260925.zeabur.app';
 const p=current.context().pages().find(tab=>tab.url().startsWith(origin));
 if(!p)throw Error('Company tab unavailable');
 const errors=[];const record=e=>errors.push(e.name);p.on('pageerror',record);
 try{
  await p.setViewportSize({width:1440,height:1000});
  await p.goto(origin+'/#view=company');
  await p.reload();
  await p.getByRole('heading',{name:'公司駕駛艙',exact:true}).waitFor();
  await p.locator('.cockpit-case-total strong').waitFor();
  const result=await p.evaluate(async()=>{
   const session=await (await fetch('/api/session')).json();
   if(session.mode!=='lark'||!session.workspace_id?.startsWith('lark-'))throw Error('Formal company login required');
   const response=await fetch('/api/company-dashboard?limit=40');const data=await response.json();
   const w=await (await fetch('/api/workspace')).json();
   return {http_status:response.status,formal_namespace:true,visible_projects:w.projects?.length,
    totals:data.totals,source:data.source,pagination:data.pagination,
    unique_case_ids:new Set((w.projects||[]).map(p=>p.id)).size,
    dashboard_matches_workspace:data.totals?.cases===(w.projects||[]).filter(p=>p.source_kind==='lark').length,
    rendered_total:document.querySelector('.cockpit-case-total strong')?.textContent,
    desktop_overflow:document.documentElement.scrollWidth>innerWidth,
    assets:[...document.querySelectorAll('script[src]')].map(e=>new URL(e.src).pathname)};
  });
  await p.screenshot({path:'output/playwright/company-cockpit-live-desktop.png',fullPage:true});
  const next=p.getByRole('button',{name:'下一頁',exact:true});
  if(await next.isEnabled()){
   await next.click();await p.waitForFunction(()=>document.querySelector('.cockpit-pagination')?.textContent.includes('41–'));
   result.pagination_works=true;
   await p.getByRole('button',{name:'上一頁',exact:true}).click();
   await p.waitForFunction(()=>document.querySelector('.cockpit-pagination')?.textContent.includes('1–'));
  }
  await p.setViewportSize({width:390,height:844});
  result.mobile_overflow=await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  await p.screenshot({path:'output/playwright/company-cockpit-live-mobile.png',fullPage:true});
  await p.setViewportSize({width:1440,height:1000});
  return {...result,page_error_types:errors};
 }finally{p.off('pageerror',record);}
}''',
    'company-release-ui':r'''async(current)=>{
 const origin='https://yongxiang-projects-20260925.zeabur.app';
 const p=current.context().pages().find(tab=>tab.url().startsWith(origin));
 if(!p)throw Error('Company tab unavailable');
 const errors=[];const record=e=>errors.push(e.name);p.on('pageerror',record);
 try{
  await p.goto(origin);await p.waitForLoadState('networkidle');
  const result=await p.evaluate(async()=>{
   const session=await (await fetch('/api/session')).json();
   const response=await fetch('/api/workspace');const workspace=response.ok?await response.json():{};
   return {logged_in:!!session.user,account_matches:session.user?.name==='jekai',mode:session.mode,environment:session.environment,
    formal_namespace:session.workspace_id?.startsWith('lark-')===true,
    workspace_status:response.status,visible_projects:workspace.projects?.length,
    baseline_status:workspace.source_case_baseline_status?.status,
    source_status:workspace.source_status?.status,mapping_status:workspace.source_status?.mapping_status,
    demo_visible:document.body.innerText.includes('DEMO'),
    assets:[...document.querySelectorAll('script[src]')].map(e=>new URL(e.src).pathname),
    horizontal_overflow:document.documentElement.scrollWidth>innerWidth};
  });
  await p.screenshot({path:'output/playwright/company-release-20260930.png',fullPage:true});
  return {...result,page_error_types:errors};
 }finally{p.off('pageerror',record);}
}''',
    'company-session-check':r'''async(current)=>{
 const origin='https://yongxiang-projects-20260925.zeabur.app';
 const p=current.context().pages().find(tab=>tab.url().startsWith(origin));
 if(!p)throw Error('Company tab unavailable');
 return await p.evaluate(async()=>{
  const response=await fetch('/api/session');const session=await response.json();
  const workspace=await fetch('/api/workspace');
  return {session_status:response.status,mode:session.mode,logged_in:!!session.user,environment:session.environment,
   formal_namespace:session.workspace_id?.startsWith('lark-')===true,
   account_matches:session.user?.name==='jekai',role:session.user?.role,
   workspace_status:workspace.status};
 });
}''',
    'company-login':r'''async(current)=>{
 const origin='https://yongxiang-projects-20260925.zeabur.app';
 const p=current.context().pages().find(tab=>tab.url().startsWith(origin));
 if(!p)throw Error('Company entry tab unavailable');
 const link=p.getByRole('link',{name:'使用 Lark 登入',exact:true});
 if(await link.count()===1){await link.click();await p.waitForLoadState('domcontentloaded');await p.waitForTimeout(1500);}
 const url=new URL(p.url());
 return {origin:url.origin,path:url.pathname,text:(await p.locator('body').innerText()).slice(0,3000)};
}''',
    'company-entry':r'''async(current)=>{
 const origin='https://yongxiang-projects-20260925.zeabur.app';
 let p=current.context().pages().find(tab=>tab.url().startsWith(origin));
 if(!p)p=await current.context().newPage();
 await p.goto(origin);await p.waitForLoadState('networkidle');await p.bringToFront();
 await p.screenshot({path:'output/playwright/company-login-20260930.png',fullPage:true});
 const text=await p.locator('body').innerText();
 return {origin,text:text.slice(0,4000),demo_visible:text.includes('DEMO'),lark_login_link:await p.getByRole('link',{name:'使用 Lark 登入',exact:true}).count()};
}''',
    'staging-project-ui':r'''async(current)=>{
 const p=current.context().pages().find(tab=>tab.url().startsWith('https://yongxiang-workbench-staging.zeabur.app'));
 if(!p)throw Error('Staging UI tab unavailable');
 await p.getByText('桃園捷運綠線控制點測量',{exact:true}).last().click();await p.waitForTimeout(600);
 await p.screenshot({path:'output/playwright/staging-project-desktop-20260930.png',fullPage:true});
 const desktop=await p.evaluate(()=>({width:innerWidth,contentWidth:document.documentElement.scrollWidth,text:document.body.innerText.slice(-10000)}));
 await p.setViewportSize({width:390,height:844});await p.waitForTimeout(350);
 await p.screenshot({path:'output/playwright/staging-project-mobile-20260930.png',fullPage:true});
 const mobile=await p.evaluate(()=>({width:innerWidth,contentWidth:document.documentElement.scrollWidth}));
 await p.keyboard.press('Tab');
 const focus=await p.evaluate(()=>({tag:document.activeElement?.tagName,label:document.activeElement?.textContent?.trim().slice(0,120)}));
 await p.setViewportSize({width:1440,height:1000});
 return {desktop,mobile,focus};
}''',
    'staging-ui':r'''async(current)=>{
 const origin='https://yongxiang-workbench-staging.zeabur.app';
 let p=current.context().pages().find(tab=>tab.url().startsWith(origin));
 if(!p){p=await current.context().newPage();await p.goto(origin);}
 const errors=[];p.on('pageerror',error=>errors.push(error.message));
 await p.setViewportSize({width:1440,height:1000});await p.waitForLoadState('networkidle');
 await p.screenshot({path:'output/playwright/staging-desktop-20260930.png',fullPage:true});
 const desktop=await p.evaluate(()=>({width:innerWidth,contentWidth:document.documentElement.scrollWidth,text:document.body.innerText.slice(0,5500)}));
 await p.setViewportSize({width:390,height:844});await p.waitForTimeout(350);
 await p.screenshot({path:'output/playwright/staging-mobile-20260930.png',fullPage:true});
 const mobile=await p.evaluate(()=>({width:innerWidth,contentWidth:document.documentElement.scrollWidth}));
 await p.setViewportSize({width:1440,height:1000});
 return {desktop,mobile,errors};
}''',
    'backup-permissions':r'''async(current)=>{
 for(const p of current.context().pages()){
   if(!p.url().startsWith('https://open.larksuite.com/app/cli_aa361fea3678de13/')||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')continue;
   await p.getByText('权限管理',{exact:true}).click();
   return {url:p.url(),text:(await p.locator('body').innerText()).slice(0,14000)};
 }
 throw Error('Exact backup application tab unavailable');
}''',
    'backup-create':r'''async(current)=>{
 for(const p of current.context().pages()){
   if(!p.url().startsWith('https://open.larksuite.com/app')||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')continue;
   const dialog=p.getByRole('dialog');if(await dialog.count()!==1)throw Error('Expected the prepared application form');
   const fields=dialog.getByRole('textbox');
   if(await fields.count()!==2||await fields.nth(0).inputValue()!=='詠翔工作台備份')throw Error('Backup application identity mismatch');
   if(!(await fields.nth(1).inputValue()).startsWith('專案工作台加密異地備份專用身分。'))throw Error('Backup application purpose mismatch');
   const create=dialog.getByRole('button',{name:'创建',exact:true});
   if(!await create.isEnabled())throw Error('Prepared application form is incomplete');
   await create.click();
   await p.waitForURL(/\/app\/cli_[a-z0-9]+\//,{timeout:25000});
   return {url:p.url(),text:(await p.locator('body').innerText()).slice(0,12000)};
 }
 throw Error('Dedicated backup setup tab unavailable');
}''',
    'backup-fill':r'''async(current)=>{
 for(const p of current.context().pages()){
   if(!p.url().startsWith('https://open.larksuite.com/app')||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')continue;
   const dialog=p.getByRole('dialog');if(await dialog.count()!==1)throw Error('Expected one application form');
   const fields=dialog.getByRole('textbox');if(await fields.count()!==2)throw Error('Application fields changed');
   await fields.nth(0).fill('詠翔工作台備份');
   await fields.nth(1).fill('專案工作台加密異地備份專用身分。僅存取核定備份資料夾，上傳與讀回核實；不讀寫案件、報價、日報、薪資或能力資料，不發送通知。');
   return {text:await dialog.innerText(),buttons:await dialog.getByRole('button').allInnerTexts()};
 }
 throw Error('Dedicated backup setup tab unavailable');
}''',
    'backup-form':r'''async(current)=>{
 for(const p of current.context().pages()){
   if(!p.url().startsWith('https://open.larksuite.com/app')||await p.evaluate(()=>window.name)!=='yx-backup-app-setup')continue;
   if(await p.getByPlaceholder('搜索应用名称或 App ID',{exact:true}).inputValue()!=='詠翔工作台備份'||!await p.getByText('暂无搜索结果',{exact:true}).isVisible())throw Error('Existing backup application must be reconciled first');
   await p.getByRole('button',{name:'创建企业自建应用',exact:true}).click();
   return {text:(await p.locator('body').innerText()).slice(-15000),inputs:await p.getByRole('textbox').evaluateAll(es=>es.map(e=>({placeholder:e.getAttribute('placeholder'),label:e.getAttribute('aria-label')})))};
 }
 throw Error('Dedicated backup setup tab unavailable');
}''',
    'find-existing':r'''async(current)=>{
 const result={};
 for(const p of current.context().pages()){
   const named=await p.evaluate(()=>window.name).catch(()=>'');
   if(named==='yx-backup-app-setup'&&p.url().startsWith('https://open.larksuite.com/app')){
     await p.getByPlaceholder('搜索应用名称或 App ID',{exact:true}).fill('詠翔工作台備份');
     await p.waitForTimeout(1200);
     result.backup=(await p.locator('body').innerText()).slice(0,12000);
   }
   if(named==='yx-native-qa-definition'&&p.url().startsWith('https://www.larksuite.com/approval/admin/')){
     const second=p.getByText('2',{exact:true});if(await second.count()===1)await second.click();
     await p.waitForTimeout(800);
     result.qa=(await p.locator('body').innerText()).slice(0,16000);
   }
 }
 return result;
}''',
    'inspect':r'''async(current)=>{
 const result={};
 for(const p of current.context().pages()){
   const named=await p.evaluate(()=>window.name).catch(()=>'');
   if(named==='yx-backup-app-setup'&&p.url().startsWith('https://open.larksuite.com/app')){
     result.backup={text:(await p.locator('body').innerText()).slice(0,18000),
       inputs:await p.getByRole('textbox').evaluateAll(es=>es.map(e=>({placeholder:e.getAttribute('placeholder'),label:e.getAttribute('aria-label')})))};
   }
   if(named==='yx-native-qa-definition'&&p.url().startsWith('https://www.larksuite.com/approval/admin/'))
     result.qa={text:(await p.locator('body').innerText()).slice(0,18000)};
 }
 return result;
}''',
}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step',choices=sorted(STEPS))
    args=parser.parse_args()
    secret_path=ROOT/'.runtime/backup-independent-app-private.json'
    if args.step=='backup-credentials-capture' and secret_path.exists():
        raise SystemExit('Backup credentials already saved; do not overwrite')
    if args.step in {'backup-version-save','backup-version-submit','qa-publish','backup-folder-grant'}:
        marker=ROOT/'.runtime'/('workbench-'+args.step+'-attempt.json')
        with marker.open('x',encoding='utf-8') as f:
            json.dump({'target':'詠翔工作台－串接驗收測試' if args.step=='qa-publish' else 'cli_aa361fea3678de13','attempted_at':datetime.now(timezone.utc).isoformat()},f)
    if args.step=='backup-create':
        marker=ROOT/'.runtime/workbench-backup-create-attempt.json'
        if marker.exists():raise SystemExit('Prior backup application creation must be reconciled; not repeated')
        marker.write_text(json.dumps({'name':'詠翔工作台備份','attempted_at':datetime.now(timezone.utc).isoformat()}),encoding='utf-8')
    cli=next((Path.home()/'AppData/Local/npm-cache/_npx').glob('*/node_modules/@playwright/cli/playwright-cli.js'))
    result=subprocess.run(['node',str(cli),'-s=workbench30','run-code',STEPS[args.step]],
                          capture_output=True,text=True,encoding='utf-8',errors='replace')
    if args.step=='backup-credentials-capture':
        import re
        found=re.search(r'\{"private_credential":"([A-Za-z0-9_-]{16,128})"\}',result.stdout)
        if not found:
            print('Credential capture did not return a verified value; raw output withheld')
            return 1
        formal=json.loads((ROOT/'.runtime/login-cutover/company-intended.json').read_text(encoding='utf-8'))
        tenants=[v.strip() for v in formal.get('LARK_ALLOWED_TENANTS','').split(',') if v.strip()]
        if len(tenants)!=1 or formal.get('LARK_APP_ID')!='cli_aa3cab98b2789e17':
            raise SystemExit('Verified company identity unavailable; credential withheld')
        with secret_path.open('x',encoding='utf-8') as f:
            json.dump({'BACKUP_LARK_APP_ID':'cli_aa361fea3678de13','BACKUP_LARK_APP_SECRET':found.group(1),'BACKUP_LARK_ORGANIZATION':tenants[0]},f)
        safe='Independent backup credentials saved privately; value omitted.'
    else:
        safe=public_output(result.stdout)+'\n'+public_output(result.stderr)
    (ROOT/'.runtime'/('workbench-lark-'+args.step+'.txt')).write_text(safe,encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    print(safe)
    return result.returncode

if __name__=='__main__':raise SystemExit(main())
